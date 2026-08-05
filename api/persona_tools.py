"""
评测 Agent 管理 API —— Tab 4「评测工具」下新增的两个子 tab 的后端。

  · Persona 管理：增删改查、上传文件自定义人设、版本历史与回滚、校准闭环
  · 评测历史：每个 agent 的历史评测任务与结果、人工标注、统计与效度分析

## 注册方式（需要在 api/server.py 里加两行）

    from persona_tools import persona_bp
    app.register_blueprint(persona_bp)

## 路由清单

  Persona 本体
    GET    /api/personas                        列表（?active_only=1&with_stats=1）
    POST   /api/personas                        新建
    GET    /api/personas/<id>                   详情（含版本历史、校准记录、统计）
    PUT    /api/personas/<id>                   更新
    DELETE /api/personas/<id>                   删除
    POST   /api/personas/<id>/upload            上传 txt/md/json 覆盖人设
    POST   /api/personas/<id>/rollback          回滚到指定版本
    GET    /api/personas/<id>/preview-prompt    预览最终发给模型的 system prompt

  校准闭环
    POST   /api/personas/<id>/calibrate         提交校准意见（立刻生效）
    POST   /api/personas/<id>/apply-calibration 把未归纳的校准写进人格/偏好（1 次 LLM）

  评测历史
    GET    /api/eval-runs                       历史列表（?persona_id=&batch_uid=&limit=&offset=）
    GET    /api/eval-runs/<run_uid>             单次详情
    DELETE /api/eval-runs/<run_uid>             删除一条历史
    GET    /api/eval-runs/export.csv            导出 CSV（评测历史 sheet）
    POST   /api/eval-results/<id>/human-score   人工标注基准分
    GET    /api/eval-analysis/correlation       persona 评分 vs 生产 importance_score 相关性

## 关于校准用 LLM 这件事（成本口径）

apply-calibration 是本文件里唯一会花钱的接口，且只在用户主动点击时调一次，
把该 agent 所有未归纳的校准一起喂进去。刻意不做成"每提交一条校准就调一次"：
那样既贵，又会让人设在反复重写中漂移（模型每次都会顺手润色不该动的地方）。

校准提交本身是零成本的——comment 直接进 calib_memory，下一次评测就带上了。
LLM 归纳只是把散落的校准压缩进 personality/preferences 正文，属于优化不是必需。
"""
import csv
import io
import json
import logging
import os
import sys
from functools import wraps

from flask import Blueprint, Response, jsonify, request

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import persona_store as ps  # noqa: E402
from crawler.usage_tracker import UsageTracker  # noqa: E402

logger = logging.getLogger(__name__)

persona_bp = Blueprint("persona_tools", __name__)

# ── 鉴权 ─────────────────────────────────────────────────────────────
#
# 与 lab_tools.py / eval_tools.py / history_tools.py 同一套独立实现。这份重复
# 是项目已知并接受的技术债（README §七.4），代价是"换 token 要五处一起改"——
# 已经因此踩过两次 401，新增 blueprint 时务必把新 token 同步加到这里。
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")
API_TOKENS = {
    "lawrence":  os.environ.get("API_TOKEN_LAWRENCE", ""),
    "team-a":    os.environ.get("API_TOKEN_TEAM_A", ""),
    "team-b":    os.environ.get("API_TOKEN_TEAM_B", ""),
    "partner-1": os.environ.get("API_TOKEN_PARTNER1", ""),
    "partner-2": os.environ.get("API_TOKEN_PARTNER2", ""),
    "web":       os.environ.get("API_TOKEN_WEB", ""),
}
# 2026-08-05 仓库转 public：所有凭据的**硬编码兜底一律删除**，只从环境变量读。
# 取不到就是空字符串，而空值**必须被剔除**——否则空 token 会成为一个合法凭据，
# 把"忘了配 .env"直接变成"任何人空手就能过鉴权"，是最典型的 fail-open。
VALID_API_KEYS = {k for k in (API_SECRET_KEY, *API_TOKENS.values()) if k}

MODEL = "gpt-5.4"          # 网关切换尝试见 crawler/pipeline.py 同名常量的注释（已回退，未生效）
MAX_UPLOAD_BYTES = 512 * 1024      # 人设文件 512KB 上限，纯文本足够用了
MAX_FIELD_CHARS = 8000             # 单个人设字段的长度上限，防止把整本小说塞进 prompt


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not key:
            key = request.args.get("token", "")
        if key not in VALID_API_KEYS:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


_client = None


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
            timeout=90.0, max_retries=1,
        )
    return _client


def _body() -> dict:
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def _clip_fields(d: dict) -> dict:
    """人设各字段做长度截断。超长的字段每次评测都会进 prompt，直接推高每一次
    调用的成本，且模型对超长人设的遵循度反而下降。"""
    out = dict(d)
    for k in [*ps.PERSONA_FIELDS, "prompt_override"]:
        if isinstance(out.get(k), str) and len(out[k]) > MAX_FIELD_CHARS:
            out[k] = out[k][:MAX_FIELD_CHARS]
    return out


# ══════════════════════════════════════════════════════════════════════
# Persona CRUD
# ══════════════════════════════════════════════════════════════════════

@persona_bp.route("/api/personas", methods=["GET"])
@require_api_key
def api_list_personas():
    try:
        ps.ensure_seeded()
        rows = ps.list_personas(
            active_only=request.args.get("active_only") in ("1", "true"),
            with_stats=request.args.get("with_stats") in ("1", "true"),
        )
        return jsonify({"personas": rows, "total": len(rows),
                        "fields": ps.PERSONA_FIELDS,
                        "field_labels": ps.PERSONA_FIELD_LABELS})
    except Exception as e:
        logger.exception("list personas failed")
        return jsonify({"error": f"读取 persona 失败：{e}"}), 500


@persona_bp.route("/api/personas", methods=["POST"])
@require_api_key
def api_create_persona():
    data = _clip_fields(_body())
    if not (data.get("name") or "").strip():
        return jsonify({"error": "name 必填"}), 400
    pid = (data.get("id") or "").strip()
    if pid and ps.get_persona(pid):
        return jsonify({"error": f"id={pid} 已存在，换一个或直接编辑它"}), 409
    try:
        return jsonify({"persona": ps.create_persona(data)}), 201
    except Exception as e:
        logger.exception("create persona failed")
        return jsonify({"error": f"创建失败：{e}"}), 500


@persona_bp.route("/api/personas/<persona_id>", methods=["GET"])
@require_api_key
def api_get_persona(persona_id):
    p = ps.get_persona(persona_id)
    if p is None:
        return jsonify({"error": f"找不到 persona: {persona_id}"}), 404
    return jsonify({
        "persona": p,
        "system_prompt": ps.compose_system_prompt(p),
        "versions": ps.list_versions(persona_id, limit=30),
        "calibrations": ps.list_calibrations(persona_id, limit=50),
        "stats": ps.persona_stats(persona_id),
        "version_comparison": ps.version_comparison(persona_id),
    })


@persona_bp.route("/api/personas/<persona_id>", methods=["PUT", "PATCH"])
@require_api_key
def api_update_persona(persona_id):
    data = _clip_fields(_body())
    note = (data.pop("change_note", "") or "").strip()
    try:
        p = ps.update_persona(persona_id, data, note=note)
    except Exception as e:
        logger.exception("update persona failed")
        return jsonify({"error": f"更新失败：{e}"}), 500
    if p is None:
        return jsonify({"error": f"找不到 persona: {persona_id}"}), 404
    return jsonify({"persona": p, "system_prompt": ps.compose_system_prompt(p)})


@persona_bp.route("/api/personas/<persona_id>", methods=["DELETE"])
@require_api_key
def api_delete_persona(persona_id):
    p = ps.get_persona(persona_id)
    if p is None:
        return jsonify({"error": f"找不到 persona: {persona_id}"}), 404
    # 最后一个 persona 不让删——删光了 LLM 评测室会变成一个点了没反应的按钮，
    # 而且错误发生在评测时而不是删除时，排查起来绕远路。
    if len(ps.list_personas()) <= 1:
        return jsonify({"error": "这是最后一个 persona，删掉后评测室就没法用了；"
                                 "请先新建一个再删这个"}), 409
    ok = ps.delete_persona(persona_id)
    return jsonify({"deleted": ok, "id": persona_id,
                    "note": "该 agent 的历史评测记录已保留（历史是既成事实，"
                            "不随 agent 删除而消失），在评测历史里会标为「已删除的 agent」"})


@persona_bp.route("/api/personas/<persona_id>/preview-prompt", methods=["GET"])
@require_api_key
def api_preview_prompt(persona_id):
    p = ps.get_persona(persona_id)
    if p is None:
        return jsonify({"error": f"找不到 persona: {persona_id}"}), 404
    prompt = ps.compose_system_prompt(p)
    return jsonify({
        "system_prompt": prompt,
        "char_count": len(prompt),
        "uses_override": bool((p.get("prompt_override") or "").strip()),
    })


# ══════════════════════════════════════════════════════════════════════
# 文件上传自定义人设
# ══════════════════════════════════════════════════════════════════════

def _parse_persona_file(raw: str, filename: str) -> dict:
    """人设文件 -> 字段字典。支持两种格式：

      1) JSON：直接是 {"personality": "...", "story": "...", ...}
      2) Markdown/纯文本：用 `## 人格` / `## 故事` 这样的小标题分段，
         认中文标签也认英文字段名。整篇没有任何可识别小标题时，
         整体塞进 story——那是最合理的兜底（一段没有结构的人物描述，
         本质上就是"故事"）。

    做两种是因为实际使用里这两种都会出现：从别的系统导出的是 JSON，
    人手写的是 Markdown。要求用户先转格式是没必要的摩擦。
    """
    text = raw.strip()
    if filename.lower().endswith(".json") or text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {k: v for k, v in data.items()
                        if k in ps.EDITABLE_COLUMNS and isinstance(v, (str, int))}
        except Exception:
            pass  # JSON 解析失败就退回按文本切段，不直接报错

    label_to_field = {v: k for k, v in ps.PERSONA_FIELD_LABELS.items()}
    label_to_field.update({k: k for k in ps.PERSONA_FIELDS})
    label_to_field.update({"背景": "story", "人设": "personality",
                           "喜好": "preferences", "情绪": "mood"})

    out, current, buf = {}, None, []

    def flush():
        if current and buf:
            out[current] = "\n".join(buf).strip()

    for line in text.split("\n"):
        stripped = line.strip().lstrip("#").strip().rstrip("：:").strip()
        hit = label_to_field.get(stripped)
        # 只把"短行且整行就是一个标签"当小标题——否则正文里出现"我的偏好是……"
        # 这种句子会被误判成分段标记，把人设切得七零八落。
        if hit and len(stripped) <= 12 and (line.strip().startswith("#") or len(line.strip()) <= 14):
            flush()
            current, buf = hit, []
            continue
        if current:
            buf.append(line)
    flush()

    if not out:
        out["story"] = text
    return out


@persona_bp.route("/api/personas/<persona_id>/upload", methods=["POST"])
@require_api_key
def api_upload_persona(persona_id):
    p = ps.get_persona(persona_id)
    if p is None:
        return jsonify({"error": f"找不到 persona: {persona_id}"}), 404

    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "请上传 file 字段（txt / md / json）"}), 400
    content = f.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return jsonify({"error": f"文件超过 {MAX_UPLOAD_BYTES // 1024}KB 上限"}), 400
    try:
        raw = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            raw = content.decode("gbk")   # Windows 上导出的中文 txt 常见编码
        except UnicodeDecodeError:
            return jsonify({"error": "文件编码无法识别，请存成 UTF-8 再上传"}), 400

    parsed = _clip_fields(_parse_persona_file(raw, f.filename or ""))
    if not parsed:
        return jsonify({"error": "文件里没解析出任何人设字段"}), 422

    mode = request.form.get("mode", "replace")   # replace 覆盖 / append 追加
    if mode == "append":
        for k, v in list(parsed.items()):
            if k in ps.PERSONA_FIELDS and (p.get(k) or "").strip():
                parsed[k] = (p[k].rstrip() + "\n" + str(v).lstrip())[:MAX_FIELD_CHARS]

    updated = ps.update_persona(
        persona_id, parsed,
        note=f"从文件导入（{f.filename}，{mode}，命中字段：{'、'.join(parsed.keys())}）",
        source="file_import",
    )
    return jsonify({
        "persona": updated,
        "parsed_fields": list(parsed.keys()),
        "mode": mode,
        "system_prompt": ps.compose_system_prompt(updated),
    })


@persona_bp.route("/api/personas/<persona_id>/rollback", methods=["POST"])
@require_api_key
def api_rollback_persona(persona_id):
    version = _body().get("version")
    if version is None:
        return jsonify({"error": "version 必填"}), 400
    p = ps.rollback_persona(persona_id, int(version))
    if p is None:
        return jsonify({"error": f"找不到 persona {persona_id} 的 v{version}"}), 404
    return jsonify({"persona": p, "versions": ps.list_versions(persona_id, limit=30)})


# ══════════════════════════════════════════════════════════════════════
# 校准闭环
# ══════════════════════════════════════════════════════════════════════

@persona_bp.route("/api/personas/<persona_id>/calibrate", methods=["POST"])
@require_api_key
def api_calibrate(persona_id):
    p = ps.get_persona(persona_id)
    if p is None:
        return jsonify({"error": f"找不到 persona: {persona_id}"}), 404

    data = _body()
    comment = (data.get("comment") or "").strip()
    if not comment:
        return jsonify({"error": "comment 必填"}), 400
    if len(comment) > 2000:
        return jsonify({"error": "comment 太长（上限 2000 字）"}), 400

    suggested = data.get("suggested_score")
    if suggested is not None:
        try:
            suggested = int(suggested)
        except (TypeError, ValueError):
            return jsonify({"error": "suggested_score 必须是 1-10 的整数"}), 400
        if not 1 <= suggested <= 10:
            return jsonify({"error": "suggested_score 必须在 1-10 之间"}), 400

    result_id = data.get("result_id")
    try:
        out = ps.add_calibration(persona_id, comment,
                                 result_id=int(result_id) if result_id else None,
                                 suggested_score=suggested)
        # 用户给了"应该打几分"，同时把它写成人工标注基准——这是同一个判断的两种用途
        # （校准文本喂给模型，数字用来算 MAE），让用户填两遍是多余的。
        if suggested is not None and result_id:
            ps.set_human_score(int(result_id), suggested)
    except Exception as e:
        logger.exception("calibrate failed")
        return jsonify({"error": f"提交校准失败：{e}"}), 500

    return jsonify({
        "calibration_id": out["id"],
        "calib_memory": out["calib_memory"],
        "effective": "immediate",
        "note": "已立刻写入该 agent 的校准记忆，下一次评测就会生效（零成本）。"
                "攒够几条后可以点「归纳进人格」把它们压缩进人格/偏好正文。",
        "stats": ps.persona_stats(persona_id),
    })


_CALIB_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "persona_calibration_merge",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "personality": {"type": "string"},
                "preferences": {"type": "string"},
                "change_summary": {"type": "string"},
            },
            "required": ["personality", "preferences", "change_summary"],
            "additionalProperties": False,
        },
    },
}


@persona_bp.route("/api/personas/<persona_id>/apply-calibration", methods=["POST"])
@require_api_key
def api_apply_calibration(persona_id):
    """把未归纳的校准意见压进 personality / preferences，产出新版本。

    只改这两列是刻意的：story（故事）和 memory（记忆）是这个人的既成事实，
    不该因为"他这次判得不准"就被改写；mood（心情）是短期状态，由用户手动调。
    校准要修正的是"这个人的性格底色和偏好倾向"，靶点就是这两列。
    """
    p = ps.get_persona(persona_id)
    if p is None:
        return jsonify({"error": f"找不到 persona: {persona_id}"}), 404

    pending = ps.list_calibrations(persona_id, pending_only=True, limit=200)
    if not pending:
        return jsonify({"error": "没有待归纳的校准意见。先在评测结果下面写几条 comment 再来。"}), 400

    lines = []
    for c in pending:
        line = f"- {c['comment']}"
        if c.get("suggested_score") is not None:
            line += f"（当时 agent 打了 {c.get('result_score')} 分，实际应该是 {c['suggested_score']} 分）"
        if c.get("news_title"):
            line += f"　[针对新闻：{c['news_title'][:60]}]"
        lines.append(line)
    calib_text = "\n".join(lines)

    tracker = UsageTracker()
    try:
        resp = get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": (
                    "你在维护一个用于新闻评测的虚拟用户人设。用户（产品负责人）积累了一批"
                    "校准意见，指出这个人设在实际评测中的偏差。你的任务是把这些校准意见"
                    "融进人设的「人格」和「偏好」两段文字里。\n\n"
                    "硬性要求：\n"
                    "1. 保留原文中与校准无关的所有内容，逐字保留，不要润色、不要重写、"
                    "不要调整语序——只做必要的增改。\n"
                    "2. 校准指出的倾向要具体地写进去（比如「对交易所安全事故要比一般负面"
                    "新闻更敏感，这类打分应明显偏高」），不要写成「要更准确地评估」这种空话。\n"
                    "3. 如果多条校准互相矛盾，以时间较新的为准，并在 change_summary 里说明。\n"
                    "4. 不要改变这个人的身份、资产规模、经历等事实设定。\n"
                    "5. change_summary 用中文，30-120 字，说清楚具体改了什么倾向。"
                )},
                {"role": "user", "content": (
                    f"人设名称：{p.get('name')}（{p.get('tagline')}）\n\n"
                    f"【当前 人格】\n{p.get('personality') or '（空）'}\n\n"
                    f"【当前 偏好】\n{p.get('preferences') or '（空）'}\n\n"
                    f"【需要融入的校准意见（共 {len(pending)} 条）】\n{calib_text}"
                )},
            ],
            response_format=_CALIB_SCHEMA,
            max_completion_tokens=3000,
        )
        tracker.record_chat(getattr(resp, "usage", None))
        merged = json.loads(resp.choices[0].message.content)
    except Exception as e:
        logger.exception("apply calibration failed")
        return jsonify({"error": f"归纳失败（上游模型调用出错）：{e}"}), 502

    before = {"personality": p.get("personality"), "preferences": p.get("preferences")}
    updated = ps.update_persona(
        persona_id,
        {"personality": merged["personality"][:MAX_FIELD_CHARS],
         "preferences": merged["preferences"][:MAX_FIELD_CHARS]},
        note=f"归纳 {len(pending)} 条校准：{merged['change_summary']}"[:512],
        source="calibration",
    )
    ps.mark_calibrations_applied(persona_id, [c["id"] for c in pending],
                                 int(updated["version"]))

    # 价格表不在这里重抄一份——UsageTracker.snapshot() 已经用仓库统一的
    # PRICING_USD_PER_MILLION_TOKENS 算好了，抄一份必然随官方调价而漂移。
    cost = tracker.snapshot()["estimated_cost_usd"]

    return jsonify({
        "persona": updated,
        "applied_count": len(pending),
        "change_summary": merged["change_summary"],
        "before": before,
        "after": {"personality": merged["personality"], "preferences": merged["preferences"]},
        "new_version": updated["version"],
        "cost_usd": round(float(cost), 6),
        "note": "校准记忆（calib_memory）保持不变——它是审计留痕，"
                "归纳只是把结论固化进人格/偏好正文。改坏了可以回滚到上一版。",
    })


# ══════════════════════════════════════════════════════════════════════
# 评测历史
# ══════════════════════════════════════════════════════════════════════

@persona_bp.route("/api/eval-runs", methods=["GET"])
@require_api_key
def api_list_runs():
    try:
        limit = min(200, max(1, int(request.args.get("limit", 30))))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"error": "limit/offset 必须是整数"}), 400
    try:
        out = ps.list_runs(persona_id=request.args.get("persona_id") or None,
                           batch_uid=request.args.get("batch_uid") or None,
                           limit=limit, offset=offset)
        # 让前端能把 persona_id 显示成名字，同时识别出已被删除的 agent
        out["persona_names"] = {p["id"]: p["name"] for p in ps.list_personas()}
        return jsonify(out)
    except Exception as e:
        logger.exception("list runs failed")
        return jsonify({"error": f"读取评测历史失败：{e}"}), 500


@persona_bp.route("/api/eval-runs/export.csv", methods=["GET"])
@require_api_key
def api_export_runs():
    persona_id = request.args.get("persona_id") or None
    data = ps.list_runs(persona_id=persona_id, limit=5000, offset=0)
    names = {p["id"]: p["name"] for p in ps.list_personas()}

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["评测时间", "run_uid", "输入方式", "event_id", "新闻标题",
                "生产重要性分", "Agent", "Agent版本", "评分", "人工标注分",
                "是否看得懂", "定性评估", "看懂原因", "优化建议", "成本USD", "模型"])
    for run in data["runs"]:
        for r in run.get("results", []):
            w.writerow([
                run.get("created_at"), run.get("run_uid"), run.get("input_mode"),
                run.get("event_id") or "", run.get("news_title") or "",
                run.get("importance_score") if run.get("importance_score") is not None else "",
                names.get(r.get("persona_id"), f"{r.get('persona_id')}（已删除）"),
                r.get("persona_version"),
                r.get("score") if r.get("score") is not None else f"失败：{r.get('error') or ''}",
                r.get("human_score") if r.get("human_score") is not None else "",
                "" if r.get("is_understandable") is None else ("是" if r["is_understandable"] else "否"),
                r.get("qualitative_assessment") or "", r.get("understandable_reason") or "",
                r.get("improvement_suggestion") or "",
                run.get("cost_usd"), run.get("model") or "",
            ])
    # BOM：不加的话 Excel 打开中文列会乱码，这是 Windows Excel 的既定行为
    csv_bytes = ("﻿" + buf.getvalue()).encode("utf-8")
    return Response(csv_bytes, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="persona_eval_history.csv"',
    })


@persona_bp.route("/api/eval-runs/<run_uid>", methods=["GET"])
@require_api_key
def api_get_run(run_uid):
    run = ps.get_run(run_uid)
    if run is None:
        return jsonify({"error": f"找不到评测记录: {run_uid}"}), 404
    run["persona_names"] = {p["id"]: p["name"] for p in ps.list_personas()}
    return jsonify(run)


@persona_bp.route("/api/eval-runs/<run_uid>", methods=["DELETE"])
@require_api_key
def api_delete_run(run_uid):
    if not ps.delete_run(run_uid):
        return jsonify({"error": f"找不到评测记录: {run_uid}"}), 404
    return jsonify({"deleted": True, "run_uid": run_uid})


@persona_bp.route("/api/eval-results/<int:result_id>/human-score", methods=["POST"])
@require_api_key
def api_human_score(result_id):
    score = _body().get("human_score")
    if score is not None:
        try:
            score = int(score)
        except (TypeError, ValueError):
            return jsonify({"error": "human_score 必须是 1-10 的整数，或 null 表示撤销"}), 400
        if not 1 <= score <= 10:
            return jsonify({"error": "human_score 必须在 1-10 之间"}), 400
    if not ps.set_human_score(result_id, score):
        return jsonify({"error": f"找不到评测结果 id={result_id}"}), 404
    return jsonify({"result_id": result_id, "human_score": score})


# ══════════════════════════════════════════════════════════════════════
# 效度分析：persona 评分 vs 生产 importance_score
# ══════════════════════════════════════════════════════════════════════

@persona_bp.route("/api/eval-analysis/correlation", methods=["GET"])
@require_api_key
def api_correlation():
    """我们排序模型给高分的事件，真实人群是不是也觉得有价值？

    这是排序策略的**外部效度**检验。相关性高说明模型的重要性排序和真实用户感受
    一致；某个 persona 的相关性显著低，说明当前排序对这类人群不适配——那本身就是
    个产品结论（比如「排序对小白不友好」）。

    只统计 input_mode='event_id' 的评测——只有走库内事件这条路径才有生产
    importance_score 可比。样本太少时不给相关系数，返回 null 并说明原因，
    不返回一个基于 3 个点算出来的、看起来很唬人的 0.97。
    """
    import numpy as np

    min_n = 5
    conn = ps._conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT res.persona_id, res.score, run.importance_score "
            "FROM persona_eval_results res "
            "JOIN persona_eval_runs run ON run.id = res.run_id "
            "WHERE run.importance_score IS NOT NULL AND res.score IS NOT NULL "
            "  AND res.error IS NULL"
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    by_persona = {}
    for r in rows:
        by_persona.setdefault(r["persona_id"], []).append(
            (float(r["score"]), float(r["importance_score"])))

    names = {p["id"]: p["name"] for p in ps.list_personas()}
    out = []
    for pid, pairs in by_persona.items():
        n = len(pairs)
        entry = {"persona_id": pid, "name": names.get(pid, f"{pid}（已删除）"),
                 "sample_size": n, "pearson_r": None, "note": None}
        if n < min_n:
            entry["note"] = f"样本仅 {n} 条，不足 {min_n} 条，不给相关系数（样本太小算出来的数没有意义）"
        else:
            a = np.array([p[0] for p in pairs]); b = np.array([p[1] for p in pairs])
            if a.std() == 0 or b.std() == 0:
                entry["note"] = "其中一侧评分完全无变化（方差为 0），相关系数无定义"
            else:
                entry["pearson_r"] = round(float(np.corrcoef(a, b)[0, 1]), 3)
                entry["avg_persona_score"] = round(float(a.mean()), 2)
                entry["avg_importance"] = round(float(b.mean()), 4)
        out.append(entry)

    out.sort(key=lambda x: (x["pearson_r"] is None, -(x["pearson_r"] or 0)))
    return jsonify({
        "correlations": out,
        "total_pairs": len(rows),
        "min_sample_size": min_n,
        "interpretation": "Pearson r 衡量「该 agent 的主观评分」与「生产排序模型的 importance_score」"
                          "的线性相关性。r 越高说明排序越贴合这类人群的真实感受；某个 agent 的 r "
                          "明显偏低，说明当前排序策略对这类用户不适配——这本身就是一个可汇报的产品结论。"
                          "只统计通过「库内事件（event_id）」方式发起的评测，其它输入方式没有生产分可比。",
    })
