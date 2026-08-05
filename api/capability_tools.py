"""原子能力申请与审批 —— api/capability_tools.py（ADR-003，2026-08-06）

策略实验室「新增原子能力」tab 的后端。三类申请（label / quota / rag）走同一个
状态机：pending → approved / rejected(必带原因) →（Claude Code 开发上线后）applied。

## 本期刻意不做的事

批准**不会**自动改任何生产配置或排序行为——批准的产物是一份**变更单**
（change_order，markdown），由 Claude Code 按正常流程开发落地：需求理解 →
代码开发 → 测试通过 → 上线。这是用户的明确要求，也让本模块对线上排序的
影响严格为零：它只是一张带状态机的表。

## 鉴权分档（为什么审批不能用页面 token）

页面 token 由服务端注入进 HTML，打开网页就拿得到。审批走 api/auth.py 的
require_approver（独立 secret、手输、fail-closed），否则"能打开页面"就等于
"能批准架构变更"。提交与查看用普通档——申请人人可提、状态人人可见是产品要求。

## fail-open 读

列表接口在表不存在（迁移没跑）时返回空列表而不是 500——照抄 strategy_config
"读要宽"的原则：这个 tab 坏了不能连累实验室其它功能的页面渲染。

接入 server.py（与其它 blueprint 同一模式）：
    from capability_tools import capability_bp
    app.register_blueprint(capability_bp)
"""
import json
import logging
import os
import re
import sys
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector  # noqa: E402

from auth import require_approver  # noqa: E402

logger = logging.getLogger(__name__)

capability_bp = Blueprint("capability_tools", __name__)

# ── 普通档鉴权（与其它 blueprint 同源的复制版；approver 档不在此列）─────────
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")
API_TOKENS = {
    "lawrence":  os.environ.get("API_TOKEN_LAWRENCE", ""),
    "team-a":    os.environ.get("API_TOKEN_TEAM_A", ""),
    "team-b":    os.environ.get("API_TOKEN_TEAM_B", ""),
    "partner-1": os.environ.get("API_TOKEN_PARTNER1", ""),
    "partner-2": os.environ.get("API_TOKEN_PARTNER2", ""),
    "web":       os.environ.get("API_TOKEN_WEB", ""),
}
VALID_API_KEYS = {k for k in (API_SECRET_KEY, *API_TOKENS.values()) if k}


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


def _db():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "crypto_news"),
        charset="utf8mb4",
    )


# ── 表单校验（写要严）──────────────────────────────────────────────────────

KINDS = ("label", "quota", "rag")
LABEL_VALUE_TYPES = ("binary", "continuous", "categorical")
LABEL_CATEGORIES = ("base_factor", "bonus_factor", "tag_only")
RAG_MODES = ("upload", "describe")

# RAG 上传约束。pdf 二进制内容不做解析（那是落地开发时的事），只落盘保存。
RAG_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "rag_uploads")
RAG_ALLOWED_EXT = (".txt", ".md", ".csv", ".pdf")
RAG_MAX_BYTES = 5 * 1024 * 1024

_MAX_TEXT = 4000            # 各长文本字段的统一上限，防把表当网盘用


def _clip(s, limit=_MAX_TEXT) -> str:
    return str(s or "").strip()[:limit]


def _validate_payload(kind: str, p: dict) -> tuple[dict, str]:
    """返回 (清洗后的 payload, 错误信息)。错误信息为空串表示通过。

    原则与 strategy_config.validate 相同：只接受认识的字段与取值，
    错了给能直接照着改的报错，而不是 500。
    """
    if kind == "label":
        out = {"description": _clip(p.get("description")),
               "problem": _clip(p.get("problem")),
               "value_type": p.get("value_type"),
               "category": p.get("category")}
        if not out["description"]:
            return {}, "label 申请缺「标签描述」"
        if not out["problem"]:
            return {}, "label 申请缺「想解决的问题」"
        if out["value_type"] not in LABEL_VALUE_TYPES:
            return {}, f"标签类型必须是 {LABEL_VALUE_TYPES} 之一（0/1=binary）"
        if out["category"] not in LABEL_CATEGORIES:
            return {}, f"标签分类必须是 {LABEL_CATEGORIES} 之一"
        return out, ""

    if kind == "quota":
        out = {"position": _clip(p.get("position"), 200),
               "content": _clip(p.get("content"))}
        if not out["position"]:
            return {}, "quota 申请缺「保量位置」（如 Top1 / Top3 / 每10条N条）"
        if not out["content"]:
            return {}, "quota 申请缺「保量内容」"
        return out, ""

    if kind == "rag":
        mode = p.get("mode")
        if mode not in RAG_MODES:
            return {}, f"rag 申请的 mode 必须是 {RAG_MODES} 之一"
        out = {"mode": mode, "description": _clip(p.get("description"))}
        if mode == "describe" and not out["description"]:
            return {}, "describe 模式必须填写描述（用于自动生成 RAG 语料）"
        # upload 模式的文件在 route 层处理（multipart），这里只留占位
        out["files"] = []
        return out, ""

    return {}, f"kind 必须是 {KINDS} 之一"


# ── 变更单生成（M3 的核心；批准那一刻落进 change_order 字段）────────────────

def _estimate_label_cost(conn) -> str:
    """label 类变更单里的成本估算。按当前展示窗口的事件数 × 轻量单价。
    数字只求量级正确（b9-estimates-good-enough），估不出来时如实写估不出来。"""
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM news_events "
                    "WHERE date >= NOW() - INTERVAL 7 DAY")
        n = cur.fetchone()[0]
        cur.close()
        # 独立小 prompt 单条约为完整 enrich 的 1/10（backfill_price_move 实测口径）
        return (f"存量回填约 {n} 条 × ~$0.001/条 ≈ **${n * 0.001:.0f}**"
                f"（走公司网关额度；增量随主流水线摊薄，可忽略）")
    except Exception:
        return "估算失败（库不可达），落地前人工估"


def _build_change_order(kind: str, title: str, payload: dict, conn) -> str:
    """按 kind 生成变更单 markdown。写给两个读者：审批人（看影响与成本）
    和落地的 Claude Code（看既定架构路径，不必重新做方案）。"""
    head = (f"# 变更单：{title}\n\n"
            f"- **类型**：{kind}\n"
            f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"- **落地方式**：Claude Code 正常开发流程（需求理解 → 代码开发 → 测试通过 → 上线）\n\n"
            f"## 需求原文\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n\n")

    if kind == "label":
        cat = payload.get("category")
        wiring = {
            "base_factor": ("接入 `crawler/scoring.py` 的 `BASE_KEYS` 全链路：权重表、"
                            "`strategy_config.DEFAULTS['base_weights']`、实验室滑杆、"
                            "lab_tools.FACTOR_KEYS、前端因子明细 —— **五处联动，这是"
                            "『改架构』的部分，必须整体过一遍 QA 的公式一致性断言**"),
            "bonus_factor": ("接入 `strategy_config.DEFAULTS['bonus']` + "
                             "`lab_tools.BONUS_KEYS`（自动派生，勿再手写第二份）+ "
                             "实验室加分调节器 + cap 峰值校验"),
            "tag_only": "只出前端 tag 与筛选，不进任何分数——改动面最小",
        }[cat]
        return head + (
            "## 既定落地路径（独立标签计算通道）\n\n"
            "**不改主 enrich prompt**（改了 `PROMPT_VERSION_HASH` 会失效全部缓存、"
            "全库重算 ~$90/次）。走独立通道：\n\n"
            "1. 新表 `label_values(url_hash, label_key, value, model, created_at)`"
            "（migration 随本单走）\n"
            "2. 为该标签写独立小 prompt（严格 json_schema，附真值/反例，"
            "参照 `scripts/backfill_price_move.py` 的模式）\n"
            "3. 经现有 enrich bridge（Mac worker → 公司网关）批量计算，"
            "复用增量提交与新旧优先次序\n"
            f"4. 按标签分类接线：{wiring}\n\n"
            f"## 成本估算\n\n{_estimate_label_cost(conn)}\n\n"
            "## 预计改动文件\n\n"
            "`config/migrations/0xx_*.sql`、`api/enrich_bridge.py`（派活扩展）、"
            "`scripts/local_enrich_worker.py`、`crawler/scoring.py` 或 "
            "`api/strategy_config.py`（按分类）、`web/index.html`、`scripts/qa_suite.py`\n\n"
            "## 测试与回滚\n\n"
            "- 真实网关跑 ≥12 条边界样本；QA 加「有字段用字段/无字段兜底」双路径断言\n"
            "- 回滚：标签表纯新增可直接停用；进分数的部分回滚 strategy_config 版本\n")

    if kind == "quota":
        return head + (
            "## 既定落地路径\n\n"
            "泛化 `api/lab_tools.py::apply_mix_strategy`（已有 per-10 配额与 Top 置顶"
            "骨架）：把写死的 `_has_tradable` 谓词换成受限 DSL "
            "`{field, op, value}`，field 白名单限 "
            "`tradable_count / market_scope / news_type / sentiment_score / event_tier`，"
            "不引入 eval。逐规则 try/except，坏规则跳过并记日志。\n\n"
            "被提上来的条目沿用 `mix_reason` 标注机制（可解释性不减）。\n\n"
            "## 预计改动文件\n\n"
            "`api/lab_tools.py`、`api/strategy_config.py`（mix 节校验）、"
            "`web/index.html`（实验室混排区新开关，沿用 Apply 按钮范式）、"
            "`scripts/qa_suite.py`\n\n"
            "## 成本估算\n\n零 LLM 成本（纯重排逻辑）\n\n"
            "## 测试与回滚\n\n"
            "- QA 断言：坏谓词不改变排序；配额窗口不重不漏；生产与实验室同公式\n"
            "- 回滚：mix 配置一键恢复上一基线版本（strategy_config 已有版本化）\n")

    # rag
    return head + (
        "## 既定落地路径\n\n"
        "**如实说明**：检索链路当前零基础（代码里无任何向量库/检索），这是本单"
        "最大的一块。分两步：\n\n"
        "1. 语料入库：上传文件已落 `data/rag_uploads/<request_id>/`；describe 模式"
        "由 Claude Code 用公司网关生成语料初稿，**随本单一起人审后**入语料表\n"
        "2. 检索接线：复用去重通道的 embedding（`text-embedding-3-small`, 256 维，"
        "经 bridge 计算）建向量表，enrich『内容理解打标』阶段检索 top-k 注入 prompt"
        "——注意这会改主 prompt，**要与其它待办标签攒批一起做**，摊薄全库重算成本\n\n"
        "## 预计改动文件\n\n"
        "`config/migrations/0xx_rag_corpus.sql`、`crawler/pipeline.py`（检索注入）、"
        "`api/enrich_bridge.py`、`scripts/local_enrich_worker.py`、`scripts/qa_suite.py`\n\n"
        "## 成本估算\n\n"
        "语料 embedding 一次性（条数×~$0.0000x，可忽略）；**主 prompt 变更触发"
        "全库重算 ~$90**——与其它 prompt 变更攒批执行\n\n"
        "## 测试与回滚\n\n"
        "- 检索质量：抽 20 条真实事件人工核对 top-k 相关性\n"
        "- 回滚：语料表可整体停用；prompt 回退到上一 hash（缓存按 hash 隔离，旧缓存仍在）\n")


# ── 路由 ──────────────────────────────────────────────────────────────────

@capability_bp.route("/api/capabilities/requests", methods=["POST"])
@require_api_key
def submit_request():
    """提交申请。JSON 或 multipart（rag upload 模式带文件）。"""
    if request.content_type and "multipart" in request.content_type:
        body = {k: request.form.get(k) for k in
                ("kind", "title", "submitted_by", "mode", "description")}
        body["payload"] = {"mode": body.pop("mode", None),
                           "description": body.pop("description", None)}
        files = request.files.getlist("files")
    else:
        body = request.get_json(silent=True) or {}
        files = []

    kind = body.get("kind")
    title = _clip(body.get("title"), 120)
    if not title:
        return jsonify({"error": "缺 title（列表页显示用，一句话说清这个能力）"}), 400
    payload, err = _validate_payload(kind, body.get("payload") or {})
    if err:
        return jsonify({"error": err}), 400

    # rag upload 模式：文件校验先于任何写库，半途失败不留孤儿记录
    staged_files = []
    if kind == "rag" and payload["mode"] == "upload":
        if not files:
            return jsonify({"error": "upload 模式必须附带 files 字段"}), 400
        for f in files:
            name = os.path.basename(f.filename or "")
            if not name.lower().endswith(RAG_ALLOWED_EXT):
                return jsonify({"error": f"{name}: 只收 {'/'.join(RAG_ALLOWED_EXT)}"}), 400
            blob = f.read()
            if len(blob) > RAG_MAX_BYTES:
                return jsonify({"error": f"{name}: 超过 {RAG_MAX_BYTES // 1024 // 1024}MB 上限"}), 400
            # 防路径穿越：只留安全字符
            safe = re.sub(r"[^A-Za-z0-9._一-鿿-]", "_", name)
            staged_files.append((safe, blob))

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO capability_requests (kind, title, payload, submitted_by) "
            "VALUES (%s, %s, %s, %s)",
            (kind, title, json.dumps(payload, ensure_ascii=False),
             _clip(body.get("submitted_by"), 64)))
        rid = cur.lastrowid
        if staged_files:
            d = os.path.join(RAG_UPLOAD_DIR, str(rid))
            os.makedirs(d, exist_ok=True)
            saved = []
            for safe, blob in staged_files:
                path = os.path.join(d, safe)
                with open(path, "wb") as fh:
                    fh.write(blob)
                saved.append(f"data/rag_uploads/{rid}/{safe}")
            payload["files"] = saved
            cur.execute("UPDATE capability_requests SET payload=%s WHERE id=%s",
                        (json.dumps(payload, ensure_ascii=False), rid))
        conn.commit()
        cur.close()
        return jsonify({"id": rid, "status": "pending"})
    finally:
        conn.close()


@capability_bp.route("/api/capabilities/requests", methods=["GET"])
@require_api_key
def list_requests():
    """全状态列表，含拒绝原因——产品要求所有人可见。fail-open：表缺失回空。"""
    status = request.args.get("status")
    try:
        conn = _db()
        cur = conn.cursor(dictionary=True)
        sql = ("SELECT id, kind, title, payload, status, submitted_by, submitted_at, "
               "decided_at, decide_note, applied_at, "
               "(change_order IS NOT NULL) AS has_change_order "
               "FROM capability_requests ")
        args = []
        if status:
            sql += "WHERE status=%s "
            args.append(status)
        sql += "ORDER BY submitted_at DESC LIMIT 100"
        cur.execute(sql, args)
        rows = cur.fetchall()
        for r in rows:
            if isinstance(r.get("payload"), str):
                try:
                    r["payload"] = json.loads(r["payload"])
                except ValueError:
                    pass
            for k in ("submitted_at", "decided_at", "applied_at"):
                if r.get(k):
                    r[k] = r[k].isoformat()
        cur.close()
        conn.close()
        return jsonify({"data": rows,
                        "pending": sum(1 for r in rows if r["status"] == "pending")})
    except Exception as e:
        # 表还没建（迁移没跑）等一律回空列表：这个 tab 坏了不能连累实验室其它功能
        logger.warning(f"capability list fail-open: {e}")
        return jsonify({"data": [], "pending": 0})


@capability_bp.route("/api/capabilities/requests/<int:rid>/detail", methods=["GET"])
@require_api_key
def request_detail(rid):
    """单条详情（含完整变更单）。Claude Code 落地时读这里。"""
    conn = _db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM capability_requests WHERE id=%s", (rid,))
        row = cur.fetchone()
        cur.close()
        if not row:
            return jsonify({"error": f"无此申请 #{rid}"}), 404
        if isinstance(row.get("payload"), str):
            try:
                row["payload"] = json.loads(row["payload"])
            except ValueError:
                pass
        for k in ("submitted_at", "decided_at", "applied_at"):
            if row.get(k):
                row[k] = row[k].isoformat()
        return jsonify(row)
    finally:
        conn.close()


def _transition(rid: int, expect: str, to: str, note: str | None,
                extra_sql: str = ""):
    """状态迁移的公共实现。校验当前状态（FOR UPDATE 行锁），防止并发的
    批准/拒绝互相覆盖。返回 (row 或 None, 错误响应或 None)，conn 在本函数内闭合。"""
    conn = _db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, kind, title, status "
                    "FROM capability_requests WHERE id=%s FOR UPDATE", (rid,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return None, (jsonify({"error": f"无此申请 #{rid}"}), 404)
        if row["status"] != expect:
            conn.rollback()
            return None, (jsonify({"error": f"#{rid} 当前状态是 {row['status']}，"
                                            f"只能从 {expect} 迁移到 {to}"}), 409)
        cur.execute(
            f"UPDATE capability_requests SET status=%s, decided_at=NOW(), "
            f"decide_note=%s {extra_sql} WHERE id=%s",
            (to, note, rid))
        conn.commit()
        row["status"] = to
        cur.close()
        return row, None
    finally:
        conn.close()


@capability_bp.route("/api/capabilities/requests/<int:rid>/approve", methods=["POST"])
@require_approver
def approve_request(rid):
    """批准：生成变更单存入 change_order，状态 → approved。
    本期批准**不自动改任何生产配置**——落地由 Claude Code 走正常开发流程。"""
    body = request.get_json(silent=True) or {}
    note = _clip(body.get("note"), 500) or None

    conn = _db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, kind, title, payload, status "
                    "FROM capability_requests WHERE id=%s FOR UPDATE", (rid,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({"error": f"无此申请 #{rid}"}), 404
        if row["status"] != "pending":
            conn.rollback()
            return jsonify({"error": f"#{rid} 当前状态是 {row['status']}，只能批准 pending"}), 409
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        order = _build_change_order(row["kind"], row["title"], payload, conn)
        cur.execute(
            "UPDATE capability_requests SET status='approved', decided_at=NOW(), "
            "decide_note=%s, change_order=%s WHERE id=%s", (note, order, rid))
        conn.commit()
        cur.close()
        return jsonify({"id": rid, "status": "approved",
                        "change_order_chars": len(order),
                        "next": "Claude Code 会读取变更单并按正常流程开发落地"})
    finally:
        conn.close()


@capability_bp.route("/api/capabilities/requests/<int:rid>/reject", methods=["POST"])
@require_approver
def reject_request(rid):
    """拒绝：**原因必填**（产品要求 status 更新且原因所有人可见）。"""
    body = request.get_json(silent=True) or {}
    reason = _clip(body.get("reason"), 500)
    if not reason:
        return jsonify({"error": "拒绝必须填写原因（reason）——申请人要能看到为什么被拒"}), 400
    _, err = _transition(rid, "pending", "rejected", reason)
    if err:
        return err
    return jsonify({"id": rid, "status": "rejected", "reason": reason})


@capability_bp.route("/api/capabilities/requests/<int:rid>/mark-applied", methods=["POST"])
@require_approver
def mark_applied(rid):
    """开发上线后回填 applied（Claude Code 交付时调，保持状态机闭环）。"""
    _, err = _transition(rid, "approved", "applied", None,
                         extra_sql=", applied_at=NOW()")
    if err:
        return err
    return jsonify({"id": rid, "status": "applied"})
