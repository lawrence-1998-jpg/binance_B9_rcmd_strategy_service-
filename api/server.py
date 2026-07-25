"""
REST API 服务 - 对外提供新闻数据查询接口
"""
import os, json, logging
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, g
import mysql.connector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "***REMOVED***")


def get_db():
    if "db" not in g:
        g.db = mysql.connector.connect(
            host=os.environ.get("MYSQL_HOST", "localhost"),
            port=int(os.environ.get("MYSQL_PORT", 3306)),
            user=os.environ.get("MYSQL_USER", "root"),
            password=os.environ.get("MYSQL_PASSWORD", "***REMOVED***"),
            database=os.environ.get("MYSQL_DATABASE", "crypto_news"),
            charset="utf8mb4",
        )
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if key != API_SECRET_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# news_events 对外暴露的列。刻意不含 embedding：那是 256 维 float32 向量的二进制
# BLOB，既无法 JSON 序列化，对调用方也没有意义（它只服务于服务端去重）。
EVENT_COLUMNS = """
    id, title_en, title_zh, date, time_event, time_get_data,
    description_short_en, description_short_zh,
    description_long_en, description_long_zh,
    sectors, coins, news_type, event_tier,
    score_market_impact, score_timeliness, score_hotness,
    score_authority, score_quality, importance_score,
    credibility_score, is_rumor, rumor_reason,
    sources, source_names, source_count, is_verified, language_origin,
    cluster_id, merged_sources_count,
    event_subject, event_action, event_fingerprint, social_interactions,
    created_at, updated_at
"""


def row_to_dict(cursor, row):
    cols = [d[0] for d in cursor.description]
    d = dict(zip(cols, row))
    # JSON 字段反序列化
    for field in ["sectors", "coins", "sources", "source_names"]:
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    # datetime 序列化；bytes 兜底剔除，防止任何二进制列漏进 jsonify
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, (bytes, bytearray)):
            d.pop(k)
    return d


# ─── 主新闻列表 ───────────────────────────────────────────────────────────────
@app.route("/api/news", methods=["GET"])
@require_api_key
def get_news():
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    sector = request.args.get("sector")
    source = request.args.get("source")
    news_type = request.args.get("news_type")
    is_rumor = request.args.get("is_rumor")
    event_tier = request.args.get("event_tier")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    sort = request.args.get("sort", "importance")  # importance | date

    where = ["1=1"]
    params = []

    if sector:
        where.append("JSON_CONTAINS(sectors, %s)")
        params.append(json.dumps(sector))
    if source:
        # 按数据源筛选（source_names JSON 数组模糊匹配，如 ?source=BlockBeats快讯 或 ?source=X/WuBlockchain）
        where.append("source_names LIKE %s")
        params.append(f'%"{source}"%' if not source.endswith("*") else f'%"{source[:-1]}%')
    if news_type:
        where.append("news_type = %s")
        params.append(news_type)
    if is_rumor is not None:
        where.append("is_rumor = %s")
        # 支持 ?is_rumor=0/1 或 ?is_rumor=true/false
        if is_rumor.lower() in ("true", "1"):
            params.append(1)
        else:
            params.append(0)
    if event_tier:
        where.append("event_tier = %s")
        params.append(event_tier)
    if date_from:
        where.append("date >= %s")
        params.append(date_from)
    if date_to:
        where.append("date <= %s")
        params.append(date_to)

    order = "importance_score DESC" if sort == "importance" else "time_get_data DESC"
    sql = (f"SELECT {EVENT_COLUMNS} FROM news_events WHERE {' AND '.join(where)} "
           f"ORDER BY {order} LIMIT %s OFFSET %s")
    params += [limit, offset]

    db = get_db()
    cursor = db.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    data = [row_to_dict(cursor, r) for r in rows]

    # 总数
    cursor.execute(f"SELECT COUNT(*) FROM news_events WHERE {' AND '.join(where)}", params[:-2])
    total = cursor.fetchone()[0]
    cursor.close()

    return jsonify({"data": data, "meta": {"total": total, "limit": limit, "offset": offset}})


# ─── 数据源列表（用于前端筛选下拉框）─────────────────────────────────────────
@app.route("/api/sources", methods=["GET"])
@require_api_key
def get_sources():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT source_names FROM news_events WHERE source_names IS NOT NULL")
    counts = {}
    for (sn,) in cursor.fetchall():
        try:
            for name in json.loads(sn):
                counts[name] = counts.get(name, 0) + 1
        except Exception:
            pass
    cursor.close()
    data = [{"source": k, "event_count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return jsonify({"data": data})


# ─── 新闻事件详情 ─────────────────────────────────────────────────────────────
@app.route("/api/news/<event_id>", methods=["GET"])
@require_api_key
def get_news_detail(event_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(f"SELECT {EVENT_COLUMNS} FROM news_events WHERE id = %s", (event_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        return jsonify({"error": "Not found"}), 404
    # row_to_dict 依赖 cursor.description，必须在 close 之前调用
    data = row_to_dict(cursor, row)
    cursor.close()
    return jsonify(data)


# ─── 新闻事件的 X 来源推文 ────────────────────────────────────────────────────
@app.route("/api/news/<event_id>/x-sources", methods=["GET"])
@require_api_key
def get_news_x_sources(event_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM x_raw_posts WHERE news_event_id = %s ORDER BY like_count DESC",
        (event_id,)
    )
    rows = cursor.fetchall()
    data = [row_to_dict(cursor, r) for r in rows]
    cursor.close()
    return jsonify({"data": data})


# ─── X 推文查询 ───────────────────────────────────────────────────────────────
@app.route("/api/x-posts", methods=["GET"])
@require_api_key
def get_x_posts():
    limit = min(int(request.args.get("limit", 20)), 100)
    kol = request.args.get("kol")
    sort = request.args.get("sort", "date")  # date | likes | impressions

    where = ["1=1"]
    params = []
    if kol:
        where.append("kol_username = %s")
        params.append(kol)

    order_map = {"likes": "like_count DESC", "impressions": "impression_count DESC", "date": "published_at DESC"}
    order = order_map.get(sort, "published_at DESC")

    sql = f"SELECT * FROM x_raw_posts WHERE {' AND '.join(where)} ORDER BY {order} LIMIT %s"
    params.append(limit)

    db = get_db()
    cursor = db.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    data = [row_to_dict(cursor, r) for r in rows]
    cursor.close()
    return jsonify({"data": data})


# ─── Pipeline 运行记录 ────────────────────────────────────────────────────────
@app.route("/api/runs", methods=["GET"])
@require_api_key
def get_runs():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM pipeline_runs ORDER BY run_at DESC LIMIT 20")
    rows = cursor.fetchall()
    data = [row_to_dict(cursor, r) for r in rows]
    cursor.close()
    return jsonify({"data": data})


# ─── 健康检查（无需鉴权）────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) FROM news_events")
        count = cursor.fetchone()[0]
        cursor.close()
        return jsonify({"status": "ok", "news_count": count, "time": datetime.utcnow().isoformat()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", 8080))
    app.run(host=host, port=port, debug=False)
