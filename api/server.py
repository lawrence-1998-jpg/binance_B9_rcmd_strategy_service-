"""
REST API 服务 - 对外提供新闻数据查询接口
"""
import os, sys, json, logging
from datetime import datetime
from functools import wraps

# systemd/run_api.sh 都用 `python3 api/server.py` 直接跑这个文件，此时
# sys.path[0] 是 api/ 目录本身（脚本所在目录），项目根目录（api/ 的上一级，
# crawler/ 所在的地方）不在 sys.path 里。子模块（lab_tools.py / eval_tools.py）
# 需要 `from crawler import ...`，必须先把项目根目录塞进 sys.path，否则
# ModuleNotFoundError: No module named 'crawler'。必须放在两个 blueprint
# import 之前。两次 dirname：第一次剥掉文件名到 api/，第二次剥到项目根目录。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify, g, send_from_directory, redirect
import mysql.connector

from lab_tools import lab_bp
from eval_tools import eval_bp
from sector_insight import sector_insight_bp
from history_tools import history_bp
from enrich_bridge import enrich_bridge_bp
from crawler.timeutil import now_local

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "***REMOVED***")

# 2026-07-26：按 Lawrence 要求生成 5 个独立 token，方便分给不同的人/团队用——
# 出问题时可以单独吊销一个，不用所有对接方一起换 token。原 API_SECRET_KEY
# 继续有效（向下兼容，不影响已经在用它的地方），这 5 个是新增的。
# 环境变量可覆盖默认值（生产环境如需轮换，改 config/.env 后重启服务即可）。
API_TOKENS = {
    "lawrence":  os.environ.get("API_TOKEN_LAWRENCE",  "***REMOVED***"),
    "team-a":    os.environ.get("API_TOKEN_TEAM_A",    "***REMOVED***"),
    "team-b":    os.environ.get("API_TOKEN_TEAM_B",    "***REMOVED***"),
    "partner-1": os.environ.get("API_TOKEN_PARTNER1",  "***REMOVED***"),
    "partner-2": os.environ.get("API_TOKEN_PARTNER2",  "***REMOVED***"),
    # 工作台页面自身取数用。单独一条是为了让前端源码里不出现任何人名
    # （老的 legacy secret 里带名字），同时它被吊销也不影响任何下游接入方。
    "web":       os.environ.get("API_TOKEN_WEB",       "***REMOVED***"),
}
VALID_API_KEYS = {API_SECRET_KEY, *API_TOKENS.values()}


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
    """鉴权。支持两种传 token 的方式：

    1. `Authorization: Bearer <token>` 请求头 —— 程序化调用的标准做法
    2. `?token=<token>` URL 查询参数 —— 让非技术同事**直接在浏览器点开链接**
       就能看数据（浏览器地址栏发不出自定义请求头）

    方式 2 的代价是 token 会出现在浏览器历史和服务器访问日志里。当前 API 本身
    就是 HTTP 明文传输、单一静态 token，安全模型已经是"仅供内部可信网络使用"，
    这一项没有实质性降低安全等级。生产化时应连同 HTTPS 与分级 token 一起改造。
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not key:
            key = request.args.get("token", "")
        if key not in VALID_API_KEYS:
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
    -- 真实性校验（crawler/verification.py，五个客观信号，零 LLM 成本）
    verification_status, verification_score, verification_reason,
    verification_flags, independent_source_count,
    -- 币种市值标签（crawler/market_cap.py）：市值、相对 BTC 倍数、市值档位
    coin_metrics, primary_coin, primary_coin_market_cap,
    primary_coin_btc_ratio, coin_cap_tier,
    -- 内容理解增强：结构化实体、情绪、板块相关度明细
    entities, sentiment, sentiment_score, sector_relevance, impact_horizon,
    created_at, updated_at
"""

# 上面列表里值为 JSON 类型的列。mysql-connector 把 JSON 列取回来是字符串，
# 需要显式反序列化才能在响应里得到嵌套对象而不是转义字符串。
_JSON_FIELDS = ["sectors", "coins", "sources", "source_names",
               "verification_flags", "coin_metrics", "entities", "sector_relevance"]


def row_to_dict(cursor, row):
    cols = [d[0] for d in cursor.description]
    d = dict(zip(cols, row))
    # JSON 字段反序列化
    for field in _JSON_FIELDS:
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


def attach_x_posts(events: list[dict], cursor) -> None:
    """给每个事件挂上 `x_posts`：其 X 来源的原贴完整信息（正文/互动量/链接）。

    起因：事件的 `sources` 字段里 X 来源只有 `x_tweet_id`，调用方要看原贴内容
    此前得再调一次 `/api/news/<id>/x-sources`。现在直接内嵌，常见场景不用
    二次请求；`/x-sources` 端点保留，供需要单独按点赞排序或分页的场景使用。

    批量处理：先收集这一批事件里出现的全部 tweet_id 去重后一次查询，而不是
    每个事件单独查一次——避免 `limit=100` 时打出 100 次 x_raw_posts 查询。
    """
    tweet_ids = {
        src.get("x_tweet_id")
        for event in events
        for src in (event.get("sources") or [])
        if src.get("x_tweet_id")
    }
    for event in events:
        event["x_posts"] = []
    if not tweet_ids:
        return

    placeholders = ",".join(["%s"] * len(tweet_ids))
    cursor.execute(
        f"""SELECT tweet_id, kol_username, kol_display_name, kol_verified,
                   kol_followers_count, tweet_body, tweet_url, tweet_lang,
                   like_count, retweet_count, reply_count, quote_count,
                   impression_count, published_at
            FROM x_raw_posts WHERE tweet_id IN ({placeholders})""",
        tuple(tweet_ids),
    )
    cols = [d[0] for d in cursor.description]
    posts_by_id = {}
    for row in cursor.fetchall():
        post = dict(zip(cols, row))
        if isinstance(post.get("published_at"), datetime):
            post["published_at"] = post["published_at"].isoformat()
        posts_by_id[post["tweet_id"]] = post

    for event in events:
        seen = set()
        for src in (event.get("sources") or []):
            tid = src.get("x_tweet_id")
            if tid and tid in posts_by_id and tid not in seen:
                seen.add(tid)
                event["x_posts"].append(posts_by_id[tid])


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
    run_at = request.args.get("run_at")   # 生产轮次节点，见 /api/run-nodes
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
    if run_at:
        # 生产调度是每天 08:00 / 20:00 两轮，所以一个「节点」覆盖它到下一轮之间的 12 小时。
        # 用半开区间 [run_at, run_at+12h)，相邻两个节点既不重叠也不漏。
        where.append("time_get_data >= %s AND time_get_data < %s + INTERVAL 12 HOUR")
        params.extend([run_at, run_at])

    order = "importance_score DESC" if sort == "importance" else "time_get_data DESC"
    sql = (f"SELECT {EVENT_COLUMNS} FROM news_events WHERE {' AND '.join(where)} "
           f"ORDER BY {order} LIMIT %s OFFSET %s")
    params += [limit, offset]

    db = get_db()
    cursor = db.cursor()
    cursor.execute(sql, params)
    rows = cursor.fetchall()
    data = [row_to_dict(cursor, r) for r in rows]
    attach_x_posts(data, cursor)

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
    attach_x_posts([data], cursor)
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
# ─── 生产轮次节点 ─────────────────────────────────────────────────────────────
# 前端「观测时间」筛选器的选项来源。生产调度是每天 08:00 / 20:00 各跑一轮，
# 所以把每条事件的采集时间归到它前面最近的那个节点上：
#   ≥20:00 → 当天 20:00 ｜ ≥08:00 → 当天 08:00 ｜ <08:00 → 前一天 20:00
# 不直接读 pipeline_runs.run_at，是因为那里还混着历史手动跑的零散时间点，
# 列出来会得到一串对不上「一天两轮」认知的时间。
RUN_NODE_EXPR = """
    CASE WHEN HOUR(time_get_data) >= 20 THEN DATE_FORMAT(time_get_data, '%Y-%m-%d 20:00:00')
         WHEN HOUR(time_get_data) >= 8  THEN DATE_FORMAT(time_get_data, '%Y-%m-%d 08:00:00')
         ELSE DATE_FORMAT(DATE_SUB(time_get_data, INTERVAL 1 DAY), '%Y-%m-%d 20:00:00') END
"""


@app.route("/api/run-nodes", methods=["GET"])
@require_api_key
def get_run_nodes():
    limit = min(int(request.args.get("limit", 20)), 60)
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        f"SELECT {RUN_NODE_EXPR} AS run_at, COUNT(*) AS event_count "
        "FROM news_events WHERE time_get_data IS NOT NULL "
        "GROUP BY run_at ORDER BY run_at DESC LIMIT %s",
        (limit,),
    )
    data = [{"run_at": str(r[0]), "event_count": int(r[1])} for r in cursor.fetchall()]
    cursor.close()
    return jsonify({"data": data, "count": len(data)})


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
        return jsonify({"status": "ok", "news_count": count, "time": now_local().isoformat()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ─── 前端展示页（静态，无需鉴权）────────────────────────────────────────────
# web/*.html 是自包含页面（内联 CSS/JS，零外部 CDN 依赖），页面内的数据请求走
# ?token= 参数命中上面的 require_api_key。这里只做静态吐出，不碰既有端点逻辑。
#
# 路径白名单而非通配：通配会把所有拼错的 URL 都吞成 200 首页，掩盖真实的 404。
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
WEB_PAGES = {
    "": "index.html",           # 主页面：生成流程 / 数据展示 / API 接入 / 评测工具（同页 tab）
    "dashboard": "index.html",
    "lab": "lab.html",          # 策略实验室
}

# 2026-07-26：评测工具（原 Tab 4）从独立页面 web/eval.html 合并进 index.html 的
# 同页 tab 结构（不再有单独的 /eval 页面）。旧的 /eval 链接/书签不应该 500 或
# 静默变成一个不相关的页面——302 重定向到主页的第 4 个 tab 锚点，行为对用户来说
# 等价于"点开还是那个功能"，比裸 404 更友好，也不需要保留 eval.html 这个死文件。
_EVAL_REDIRECT_TARGET = "/#tab4"


def _nocache(resp):
    # 页面会频繁迭代，禁掉缓存免得改完刷新还是旧版
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/", methods=["GET"])
@app.route("/<page>", methods=["GET"])
def web_page(page=""):
    if page == "eval":
        return redirect(_EVAL_REDIRECT_TARGET, code=302)
    filename = WEB_PAGES.get(page)
    if not filename:
        return jsonify({"error": "Not found"}), 404
    return _nocache(send_from_directory(WEB_DIR, filename))


@app.route("/assets/<path:filename>", methods=["GET"])
def web_assets(filename):
    """共享静态资源（如 web/assets/app.css）。"""
    return _nocache(send_from_directory(os.path.join(WEB_DIR, "assets"), filename))


app.register_blueprint(lab_bp)
app.register_blueprint(eval_bp)
app.register_blueprint(sector_insight_bp)
app.register_blueprint(history_bp)
app.register_blueprint(enrich_bridge_bp)


if __name__ == "__main__":
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", 8080))
    app.run(host=host, port=port, debug=False)
