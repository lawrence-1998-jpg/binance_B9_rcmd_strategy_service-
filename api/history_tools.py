"""
历史数据 API —— Tab 6「历史数据」的后端，外加全站埋点 + Tell me more 反馈模块。
独立 Flask Blueprint，与 lab_tools.py / sector_insight.py 同一模式。

╔══════════════════════════════════════════════════════════════════════════╗
║ 接入方法 —— 需要在 api/server.py 里加两行（不要改动本文件之外的任何东西，   ║
║ 也不要自己去改 server.py——按用户要求，server.py 的改动由统一的后续步骤处理）║
║                                                                            ║
║   1) 在文件顶部，`from lab_tools import lab_bp` 那几行 import 旁边加：     ║
║        from history_tools import history_bp                             ║
║                                                                            ║
║   2) 在 `app.register_blueprint(lab_bp)` / `app.register_blueprint        ║
║      (eval_bp)` / `app.register_blueprint(sector_insight_bp)` 那几行旁边加：║
║        app.register_blueprint(history_bp)                                ║
║                                                                            ║
║ 加上这两行后，以下路由自动生效：                                          ║
║   POST   /api/history/save              —— 保存一次工具调用结果            ║
║   GET    /api/history/list              —— 分页列出历史记录（不含 payload）║
║   GET    /api/history/<id>              —— 取单条完整记录（含 payload）    ║
║   DELETE /api/history/<id>              —— 删除一条记录                    ║
║   POST   /api/analytics/track           —— 埋点上报（page_view/tab_switch/║
║                                             tool_run 等）                  ║
║   GET    /api/analytics/summary         —— 近 N 天各工具调用次数（近似统计）║
║   POST   /api/feedback                  —— "Tell me more" 反馈提交         ║
╚══════════════════════════════════════════════════════════════════════════╝

## 建表

本文件依赖三张新表（config/migrations/007_history_analytics.sql）：
tool_results / analytics_events / feedback_submissions。部署前需要先跑一次：

    mysql -uroot -p crypto_news < config/migrations/007_history_analytics.sql

## 设计要点

- payload 原样存：`tool_results.payload` 存的是调用方已经拿到手的响应 JSON，
  不做二次加工、不重新调用一次原工具接口——不同 tool 的响应结构差异很大
  （Duplicate Tester 是分组表格，LLM 评测室是多 persona 卡片，AB 对比是重合度
  + GSB，策略实验室两个子工具是排序列表），拆列存储既没必要也会很快过时。
- 列表接口 `/api/history/list` 刻意不返回 payload——历史记录可能几十上百条，
  每条 payload 又可能是几十 KB 的 JSON（尤其 AB 对比/去重检测的结果），列表页
  一次性拖回所有 payload 没有意义，只有展开单条时才按需去详情接口取。
- 埋点 `/api/analytics/track` 和统计 `/api/analytics/summary`：与其它端点一样
  过 require_api_key（页面本身已经把 DEMO_TOKEN 写死在前端 JS 里给自己用，
  所有请求走同一套鉴权，不为埋点单独开一个不鉴权的口子，保持模型一致简单）。
  前端约定 fire-and-forget：失败不重试、不弹错误、不阻塞页面。
  `/api/analytics/summary` 是"近似统计"——按 event_type='tool_run' 的埋点计数，
  不是精确的审计口径（比如同一次点击如果前端重复触发会重复计数），用户原话
  "预估就行不用花太多力气"，这里如实标注在返回结果里，不假装是精确数字。
- 独立实现 require_api_key / get_db，不 import server.py，原因同
  lab_tools.py/sector_insight.py 头部注释：避免和同时在改 server.py 的另一个
  任务耦合。
"""
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, jsonify, request, send_from_directory

from crawler import storage  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify import notify_feedback  # noqa: E402

logger = logging.getLogger(__name__)

# 反馈图片落盘目录（2026-07-26 新增，配合"Tell Lawrence More"的图片上传）。
# 不进 MySQL BLOB——大文件塞数据库既拖慢查询也不利于备份/迁移，落磁盘 + 存
# 文件名是这类附件更常规的做法。目录名固定在项目根下，不随 cwd 变化。
FEEDBACK_UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "feedback_uploads")
os.makedirs(FEEDBACK_UPLOAD_DIR, exist_ok=True)

FEEDBACK_IMAGE_MAX_BYTES = 8 * 1024 * 1024   # 8MB，与其它工具的截图上传上限一致
FEEDBACK_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

history_bp = Blueprint("history_tools", __name__)

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "***REMOVED***")

# 2026-07-26：跟 api/server.py 的 VALID_API_KEYS 保持同步，5 个可分发给不同人的 token。
API_TOKENS = {
    "lawrence":  os.environ.get("API_TOKEN_LAWRENCE",  "***REMOVED***"),
    "team-a":    os.environ.get("API_TOKEN_TEAM_A",    "***REMOVED***"),
    "team-b":    os.environ.get("API_TOKEN_TEAM_B",    "***REMOVED***"),
    "partner-1": os.environ.get("API_TOKEN_PARTNER1",  "***REMOVED***"),
    "partner-2": os.environ.get("API_TOKEN_PARTNER2",  "***REMOVED***"),
}
VALID_API_KEYS = {API_SECRET_KEY, *API_TOKENS.values()}

VALID_TOOLS = {
    "duplicate_tester", "llm_eval", "ab_compare",   # web/index.html Tab 4 三个子工具
    "lab_weight", "lab_ab_compare",                  # web/lab.html 两个子 tab
}

# 中文展示名，供 /api/history/list 消费方（前端历史数据表格）直接用，
# 不用在前端再维护一份同样的映射。
TOOL_LABELS_ZH = {
    "duplicate_tester": "Duplicate Tester · 去重检测",
    "llm_eval": "LLM 评测室",
    "ab_compare": "AB 对比（评测工具）",
    "lab_weight": "策略实验室 · 单版本权重调节",
    "lab_ab_compare": "策略实验室 · 两版本权重对比",
}


def require_api_key(f):
    """与 api/server.py 的 require_api_key 逻辑一致，独立实现不 import server.py。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not key:
            key = request.args.get("token", "")
        if key not in VALID_API_KEYS:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def _row_datetime_to_iso(row: dict, *fields: str) -> None:
    for field in fields:
        v = row.get(field)
        if isinstance(v, datetime):
            row[field] = v.isoformat()


# ══════════════════════════════════════════════════════════════════════
# 需求一：工具结果保存 + 历史数据
# ══════════════════════════════════════════════════════════════════════

@history_bp.route("/api/history/save", methods=["POST"])
@require_api_key
def save_history():
    body = request.get_json(force=True, silent=True) or {}
    tool = str(body.get("tool") or "").strip()
    if tool not in VALID_TOOLS:
        return jsonify({
            "error": f"invalid tool '{tool}', must be one of {sorted(VALID_TOOLS)}"
        }), 400

    payload = body.get("payload")
    if payload is None:
        return jsonify({"error": "missing required field 'payload'"}), 400

    label = str(body.get("label") or "").strip()[:255] or None
    try:
        cost_usd = float(body.get("cost_usd") or 0)
    except (TypeError, ValueError):
        cost_usd = 0.0

    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tool_results (tool, label, payload, cost_usd) VALUES (%s, %s, %s, %s)",
            (tool, label, json.dumps(payload, ensure_ascii=False, default=str), cost_usd),
        )
        conn.commit()
        new_id = cursor.lastrowid
        cursor.close()
    finally:
        conn.close()

    return jsonify({"id": new_id, "tool": tool, "label": label, "cost_usd": cost_usd})


@history_bp.route("/api/history/list", methods=["GET"])
@require_api_key
def list_history():
    tool = request.args.get("tool")
    if tool and tool not in VALID_TOOLS:
        return jsonify({"error": f"invalid tool '{tool}', must be one of {sorted(VALID_TOOLS)}"}), 400

    try:
        limit = min(max(1, int(request.args.get("limit", 20))), 100)
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0

    where = ["1=1"]
    params: list = []
    if tool:
        where.append("tool = %s")
        params.append(tool)

    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        # 列表页刻意不选 payload：避免一次拖回所有历史记录的完整 JSON
        cursor.execute(
            f"SELECT id, tool, label, cost_usd, created_at FROM tool_results "
            f"WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = cursor.fetchall()
        cursor.execute(
            f"SELECT COUNT(*) AS c FROM tool_results WHERE {' AND '.join(where)}", params
        )
        total = cursor.fetchone()["c"]
        cursor.close()
    finally:
        conn.close()

    for r in rows:
        _row_datetime_to_iso(r, "created_at")
        if r.get("cost_usd") is not None:
            r["cost_usd"] = float(r["cost_usd"])
        r["tool_label_zh"] = TOOL_LABELS_ZH.get(r["tool"], r["tool"])

    return jsonify({"data": rows, "meta": {"total": total, "limit": limit, "offset": offset}})


@history_bp.route("/api/history/<int:record_id>", methods=["GET"])
@require_api_key
def get_history(record_id):
    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM tool_results WHERE id = %s", (record_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()

    if not row:
        return jsonify({"error": "not found"}), 404

    _row_datetime_to_iso(row, "created_at")
    if row.get("cost_usd") is not None:
        row["cost_usd"] = float(row["cost_usd"])
    if isinstance(row.get("payload"), str):
        try:
            row["payload"] = json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            pass
    row["tool_label_zh"] = TOOL_LABELS_ZH.get(row["tool"], row["tool"])
    return jsonify(row)


@history_bp.route("/api/history/<int:record_id>", methods=["DELETE"])
@require_api_key
def delete_history(record_id):
    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tool_results WHERE id = %s", (record_id,))
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
    finally:
        conn.close()

    if not affected:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": record_id})


# ══════════════════════════════════════════════════════════════════════
# 需求二：全站埋点 + Tell me more 反馈
# ══════════════════════════════════════════════════════════════════════

@history_bp.route("/api/analytics/track", methods=["POST"])
@require_api_key
def track_event():
    body = request.get_json(force=True, silent=True) or {}
    event_type = str(body.get("event_type") or "").strip()[:32]
    if not event_type:
        return jsonify({"ok": False, "error": "missing event_type"}), 400
    page = str(body.get("page") or "")[:64]
    meta = body.get("meta")

    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO analytics_events (event_type, page, meta) VALUES (%s, %s, %s)",
            (event_type, page, json.dumps(meta, ensure_ascii=False, default=str) if meta is not None else None),
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        # 埋点失败绝不能影响前端正常使用：吞掉异常，仍返回 200。
        logger.warning(f"analytics track insert failed: {e}")
        return jsonify({"ok": False}), 200
    finally:
        conn.close()

    return jsonify({"ok": True})


@history_bp.route("/api/analytics/summary", methods=["GET"])
@require_api_key
def analytics_summary():
    """近 N 天各工具的 tool_run 埋点计数——近似统计，见文件头部说明。"""
    try:
        days = max(1, min(int(request.args.get("days", 7)), 90))
    except (TypeError, ValueError):
        days = 7
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT JSON_UNQUOTE(JSON_EXTRACT(meta, '$.tool')) AS tool, COUNT(*) AS n "
            "FROM analytics_events WHERE event_type = 'tool_run' AND created_at >= %s "
            "GROUP BY tool ORDER BY n DESC",
            (since,),
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    data = [{"tool": r["tool"] or "unknown", "tool_label_zh": TOOL_LABELS_ZH.get(r["tool"], r["tool"] or "unknown"),
             "count": r["n"]} for r in rows]
    return jsonify({
        "data": data, "days": days,
        "note": "近似统计：按 tool_run 埋点事件计数，非精确审计口径。",
    })


@history_bp.route("/api/feedback", methods=["POST"])
@require_api_key
def submit_feedback():
    """"Tell Lawrence More" 反馈提交。

    2026-07-26 改为兼容两种请求体：
    - multipart/form-data（前端现在用这个，支持带图片附件）
    - application/json（向下兼容，早期版本 / 纯文字场景，无附件）

    落库顺序很关键：先写数据库，图片落盘和邮件通知都在写库**成功之后**才做，
    且各自 try/except 不传播——反馈内容本身写库成功就必须给用户成功响应，
    图片存盘失败或邮件发不出去都只降级、不阻断。
    """
    if request.content_type and "multipart/form-data" in request.content_type:
        category = (request.form.get("category") or "").strip()[:32]
        content = (request.form.get("content") or "").strip()
        page_context = (request.form.get("page_context") or "")[:128]
        image_file = request.files.get("image")
    else:
        body = request.get_json(silent=True) or {}
        category = str(body.get("category") or "").strip()[:32]
        content = str(body.get("content") or "").strip()
        page_context = str(body.get("page_context") or "")[:128]
        image_file = None

    if not category or not content:
        return jsonify({"error": "category 和 content 均为必填"}), 400

    image_bytes = None
    image_filename_disk = None
    image_filename_original = None
    if image_file and image_file.filename:
        ext = os.path.splitext(image_file.filename)[1].lower()
        if ext not in FEEDBACK_ALLOWED_EXT:
            return jsonify({"error": f"不支持的图片格式 {ext}，"
                                     f"支持 {', '.join(sorted(FEEDBACK_ALLOWED_EXT))}"}), 400
        image_bytes = image_file.read()
        if len(image_bytes) > FEEDBACK_IMAGE_MAX_BYTES:
            return jsonify({"error": f"图片超过 {FEEDBACK_IMAGE_MAX_BYTES // 1024 // 1024}MB 上限"}), 400
        image_filename_original = image_file.filename
        image_filename_disk = f"{uuid.uuid4().hex}{ext}"

    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO feedback_submissions (category, content, page_context, image_filename) "
            "VALUES (%s, %s, %s, %s)",
            (category, content, page_context, image_filename_disk),
        )
        conn.commit()
        new_id = cursor.lastrowid
        cursor.close()
    finally:
        conn.close()

    # 落库已经成功——下面两步是"锦上添花"，任何一步失败都不影响已经返回给
    # 用户的成功结果，也不会让这条反馈从数据库里消失。
    if image_bytes and image_filename_disk:
        try:
            with open(os.path.join(FEEDBACK_UPLOAD_DIR, image_filename_disk), "wb") as f:
                f.write(image_bytes)
        except OSError as e:
            logger.warning(f"反馈图片落盘失败（反馈记录本身已保存）id={new_id}: {e}")

    notified = notify_feedback(new_id, category, content, page_context,
                               image_bytes=image_bytes,
                               image_filename=image_filename_original)
    if notified:
        try:
            conn2 = storage.get_mysql_conn()
            cur2 = conn2.cursor()
            cur2.execute("UPDATE feedback_submissions SET notified_at = NOW() WHERE id = %s", (new_id,))
            conn2.commit()
            cur2.close()
            conn2.close()
        except Exception as e:
            logger.warning(f"notified_at 回写失败（不影响邮件已发出）id={new_id}: {e}")

    return jsonify({"id": new_id, "has_image": bool(image_filename_disk), "notified": notified})


@history_bp.route("/api/feedback/image/<int:feedback_id>", methods=["GET"])
@require_api_key
def get_feedback_image(feedback_id):
    """按需回看某条反馈的图片附件（鉴权保护，不是公开静态资源）。"""
    conn = storage.get_mysql_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT image_filename FROM feedback_submissions WHERE id = %s", (feedback_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    if not row or not row[0]:
        return jsonify({"error": "该反馈没有图片附件"}), 404
    return send_from_directory(FEEDBACK_UPLOAD_DIR, row[0])
