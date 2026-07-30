"""
REST API 服务 - 对外提供新闻数据查询接口
"""
import os, sys, json, logging, time
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

from lab_tools import (lab_bp, compute_factors as lab_compute_factors,
                       rank_pool as lab_rank_pool,
                       normalize_weights as lab_normalize_weights)
import strategy_config
from eval_tools import eval_bp
from sector_insight import sector_insight_bp
from history_tools import history_bp
from enrich_bridge import enrich_bridge_bp
from source_catalog import source_catalog_bp
from persona_tools import persona_bp
from crawler.timeutil import now_local
from crawler import freshness, market_mood, market_weight, scoring


def _normalize_pool_row(e: dict) -> None:
    """把 row_to_dict 的产出补成 lab_compute_factors 能直接吃的形状。

    与 api/lab_tools.fetch_pool 的行准备逻辑对齐（那边是实验室取数、这边是
    生产取数，喂给的是**同一个** compute_factors）：JSON 列已由 row_to_dict
    反序列化，这里只补 published_at——compute_timeliness 读它；优先真实事件
    时间，缺失退化到入库时间。"""
    if not e.get("published_at"):
        e["published_at"] = e.get("time_event") or e.get("time_get_data")
    for f in ("sectors", "sector_relevance", "coins", "source_names", "sources"):
        if e.get(f) is None:
            e[f] = []

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
    sectors, coins, news_type, market_scope, event_tier,
    score_market_impact, score_timeliness, score_hotness,
    score_authority, score_quality, importance_score,
    -- PRD-03 两因子（2026-07-30 补：此前漏加，"部署到Agent"的查询时重算
    -- 读不到 breadth_level，广度全退化成默认 0.35——三条 B=1.0 的事件在
    -- 生产被压低 0.13 分，与实验室永远对不齐。这四列 tab02 明细也要用。）
    breadth_level, score_breadth, score_punch, punch_magnitude_pct,
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


# ─── 大盘情绪（crawler/market_mood.py）───────────────────────────────────────
#
# 2026-07-28 新增。5 分钟进程内缓存——情绪横幅每次页面加载都会请求，24 小时窗口
# 内的聚合结果几分钟内变化可忽略，缓存能把这个查询从"每次 /api/news 都触发"
# 降到"5 分钟一次"，不需要 Redis 这种量级的方案。
_MOOD_CACHE = {"ts": 0.0, "data": None}
_MOOD_CACHE_TTL = 300


def _get_market_mood() -> dict:
    now = time.time()
    if _MOOD_CACHE["data"] is not None and now - _MOOD_CACHE["ts"] < _MOOD_CACHE_TTL:
        return _MOOD_CACHE["data"]

    db = get_db()
    cursor = db.cursor()
    tier_placeholders = ", ".join(["%s"] * len(market_mood.MOOD_TIERS))
    cursor.execute(
        f"SELECT id, title_zh, importance_score, sentiment_score, market_scope, event_tier "
        f"FROM news_events WHERE time_get_data >= NOW() - INTERVAL %s HOUR "
        f"AND sentiment_score IS NOT NULL AND event_tier IN ({tier_placeholders})",
        (market_mood.MOOD_LOOKBACK_HOURS, *market_mood.MOOD_TIERS),
    )
    events = [
        {"id": r[0], "title_zh": r[1], "importance_score": r[2],
         "sentiment_score": r[3], "market_scope": r[4], "event_tier": r[5]}
        for r in cursor.fetchall()
    ]
    cursor.close()

    result = market_mood.compute_market_mood(events)
    _MOOD_CACHE["ts"], _MOOD_CACHE["data"] = now, result
    return result


@app.route("/api/market-mood", methods=["GET"])
@require_api_key
def get_market_mood():
    return jsonify(_get_market_mood())


# ─── 流水线监控看板（2026-07-29，tab07）──────────────────────────────
#
# Lawrence：「后台盯一下抓进来的事件的排队处理……给我配一个监控看板，抓进来的
# 数据、当前处理速度、已入库的量、有效的量（S+A级），分整体、加密、非加密。」
#
# 加了两个他没点名但当天真出过事故的指标：
#   · 最近几轮的**处理失败率**——个人 OpenAI key 在 01:48 被吊销时，前端一切
#     正常、日志里全是 401，没有任何地方能一眼看出"流水线其实断了"。
#   · 最老未消费条目的**年龄**——优先级队列上线后要盯低优先内容会不会饿死。
@app.route("/api/pipeline-monitor", methods=["GET"])
@require_api_key
def pipeline_monitor():
    db = get_db()
    cur = db.cursor()

    def one(sql, params=()):
        cur.execute(sql, params)
        r = cur.fetchone()
        return r[0] if r else None

    # ── 抓取侧 ──
    staging = {
        "total": one("SELECT COUNT(*) FROM raw_items_staging"),
        "unconsumed": one("SELECT COUNT(*) FROM raw_items_staging WHERE consumed_at IS NULL"),
        "fetched_24h": one("SELECT COUNT(*) FROM raw_items_staging "
                          "WHERE fetched_at >= NOW() - INTERVAL 24 HOUR"),
        "oldest_unconsumed_hours": one(
            "SELECT ROUND(TIMESTAMPDIFF(MINUTE, MIN(fetched_at), NOW())/60, 1) "
            "FROM raw_items_staging WHERE consumed_at IS NULL"),
    }
    cur.execute("SELECT priority, COUNT(*) FROM raw_items_staging "
                "WHERE consumed_at IS NULL GROUP BY priority ORDER BY priority")
    staging["backlog_by_priority"] = [
        {"priority": p, "label": _PRIORITY_LABELS.get(p, f"P{p}"), "count": n}
        for p, n in cur.fetchall()]

    # ── 处理速度（近 6 轮）──
    cur.execute("SELECT run_at, duration_seconds, events_count, status "
                "FROM pipeline_runs ORDER BY run_at DESC LIMIT 6")
    runs = []
    for started, dur, ev, status in cur.fetchall():
        runs.append({
            "started_at": started.isoformat() if hasattr(started, "isoformat") else str(started),
            "duration_s": float(dur or 0),
            "events": int(ev or 0),
            "status": status,
            # 每分钟产出多少事件——比"跑了多久"更能反映真实吞吐
            "events_per_min": round(float(ev or 0) / max(float(dur or 1) / 60, 0.01), 1),
        })
    ok_runs = [r for r in runs if r["status"] == "success"]
    throughput = {
        "recent_runs": runs,
        "avg_events_per_run": round(sum(r["events"] for r in ok_runs) / len(ok_runs), 1) if ok_runs else 0,
        "avg_duration_s": round(sum(r["duration_s"] for r in ok_runs) / len(ok_runs), 1) if ok_runs else 0,
        # 失败率：key 失效/上游故障时这个数会立刻跳起来，是最直接的健康信号
        "failure_rate": round(1 - len(ok_runs) / len(runs), 3) if runs else None,
    }

    # ── 入库侧：整体 / 加密 / 非加密 三档 ──
    def bucket(where_sql, params=()):
        base = f"FROM news_events WHERE {where_sql}"
        total = one(f"SELECT COUNT(*) {base}", params)
        sa = one(f"SELECT COUNT(*) {base} AND event_tier IN ('S','A')", params)
        d7 = one(f"SELECT COUNT(*) {base} AND date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)", params)
        sa7 = one(f"SELECT COUNT(*) {base} AND event_tier IN ('S','A') "
                 f"AND date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)", params)
        return {
            "total": total, "effective_sa": sa,
            "effective_rate": round(sa / total, 4) if total else 0,
            "recent_7d": d7, "recent_7d_sa": sa7,
        }

    stored = {
        "overall":  bucket("1=1"),
        "crypto":   bucket("market_scope = 'crypto'"),
        "non_crypto": bucket("market_scope IS NOT NULL AND market_scope <> 'crypto'"),
    }
    cur.execute("SELECT COALESCE(market_scope,'(未标注)'), COUNT(*), "
                "SUM(event_tier IN ('S','A')) FROM news_events "
                "WHERE date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) "
                "GROUP BY market_scope ORDER BY COUNT(*) DESC")
    stored["by_scope_7d"] = [
        {"scope": s, "count": int(n), "sa": int(sa or 0)} for s, n, sa in cur.fetchall()]

    # ── 新因子覆盖率：改造是否真的生效，看这两个数就够 ──
    total_ev = stored["overall"]["total"] or 1
    coverage = {
        "breadth_tagged": one("SELECT COUNT(*) FROM news_events WHERE breadth_level IS NOT NULL"),
        "punch_scored":   one("SELECT COUNT(*) FROM news_events WHERE score_punch IS NOT NULL"),
        "total": total_ev,
    }
    coverage["breadth_pct"] = round(coverage["breadth_tagged"] / total_ev, 4)
    coverage["punch_pct"] = round(coverage["punch_scored"] / total_ev, 4)

    cur.close()
    return jsonify({"staging": staging, "throughput": throughput,
                    "stored": stored, "factor_coverage": coverage,
                    "generated_at": now_local().isoformat()})


_PRIORITY_LABELS = {0: "P0 权威大盘媒体", 1: "P1 dxFeed大盘/ETF",
                    2: "P2 加密头部+行情", 3: "P3 其他", 4: "P4 dxFeed个股"}


# ─── 主新闻列表 ───────────────────────────────────────────────────────────────
@app.route("/api/news", methods=["GET"])
@require_api_key
def get_news():
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))
    sector = request.args.get("sector")
    source = request.args.get("source")
    news_type = request.args.get("news_type")
    market_scope = request.args.get("market_scope")
    is_rumor = request.args.get("is_rumor")
    # 展示层时效闸（2026-07-29 新增，线上事故后）。默认只出 7 天内的事件——
    # Lawrence：「只出近期（比如1周内）的内容」。这是**展示**约束，不是删数据：
    # 超期的事件仍在库里可查（传 max_age_days=0 关闭本闸，或用 date_from/date_to
    # 显式指定区间），只是不再默认出现在推荐流里。
    # 与 crawler 侧那两道闸的分工：那两道防的是"陈年内容混进库"，这一道防的是
    # "库里正常入库、但随时间自然变旧的内容继续占着推荐位"。
    try:
        # 2026-07-29 从 7 天收紧到 5 天，与 crawler 侧 MAX_EVENT_AGE_DAYS 对齐
        # （Lawrence："发布时间不是近5天的内容做强制去除"）。两侧必须同步改，
        # 否则会出现"库里已按 5 天清过、接口却还按 7 天放行"的口径错位。
        max_age_days = int(request.args.get("max_age_days", 5))
    except ValueError:
        max_age_days = 5
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
    if market_scope:
        where.append("market_scope = %s")
        params.append(market_scope)
    if max_age_days > 0 and not (date_from or date_to or run_at):
        # 显式指定了日期区间/轮次时不叠加本闸——那种查询本身就是"我要看这一段"，
        # 再套一层默认时效窗口只会让结果莫名其妙地少东西。
        where.append("date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)")
        params.append(max_age_days)
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
    db = get_db()
    cursor = db.cursor()

    if sort == "importance":
        # 情绪对齐重排（crawler/market_mood.py）：查一个比页面大的候选池（按
        # importance_score 排好序），在应用层乘上有界加成再重排、切片，而不是
        # 直接在 SQL 里 LIMIT/OFFSET——加成会改变相对顺序，只对当前这一页
        # LIMIT 出来的行做重排会在翻页边界producer出不连续的错误结果（第2页
        # 该出现的条目因为加成被挤到第1页，但 SQL 已经把它排除在候选之外）。
        # 候选池上限 500：翻页翻到几百条之外时，"今天的大盘情绪"对那么靠后的
        # 内容已经没有意义，不值得为了理论上的精确性无限扩大候选池。
        # ── 已部署基线：生产与实验室同一套公式（2026-07-30，"部署到 Agent"）──
        #
        # 有版本被部署到生产（strategy_config.is_prod=1）时，这条主排序路径
        # **不再用存量 importance_score 排序**，改为按部署版本的参数、用与
        # 策略实验室完全相同的函数（compute_factors + rank_pool）查询时实时
        # 计算——"实验室调的就是线上跑的"从此由同一份代码保证，而不是靠两边
        # 手工同步。未部署时走下面的原路径，行为与本改动之前逐字节一致。
        #
        # 候选池仍按存量分预筛（1000 条）：存量分是当前公式固定权重的产出，
        # 作为"哪些事件值得进重排池"的粗筛足够；被它挡在池外、却能被某套
        # 部署参数拉进 Top20 的事件理论上存在，实测在 5 天窗口 ~6000 条里
        # 排名 1000 开外的事件没有任何一套合理参数能翻进前 20。
        prod_cfg = strategy_config.get_prod(db)
        # 取池口径必须与实验室一致（按事件时间取近窗，而不是按存量分预筛）
        # ——首版按存量分取池，实测同参数下生产与实验室 Top10 位置一致 0/10：
        # 池子不同 → 热度基准(P95)不同 → H 因子不同 → 全乱。部署的全部意义
        # 是"实验室调出来什么样、线上就什么样"，输入必须逐项对齐：同池、
        # 同情绪、同参数。1200 上限：足够覆盖 5 天窗口里所有可能进首屏的
        # 事件（新鲜度 48h 半衰期下，两天以外的内容翻不进 Top20），单请求
        # 纯 Python 计算 ~150ms 可接受。
        pool_size = 1200 if prod_cfg else min(500, offset + limit * 5)
        pool_order = ("COALESCE(time_event, date, time_get_data) DESC" if prod_cfg
                      else "importance_score DESC")
        pool_sql = (f"SELECT {EVENT_COLUMNS} FROM news_events WHERE {' AND '.join(where)} "
                   f"ORDER BY {pool_order} LIMIT %s")
        cursor.execute(pool_sql, params + [pool_size])
        pool_rows = cursor.fetchall()
        pool = [row_to_dict(cursor, r) for r in pool_rows]

        mood = _get_market_mood()
        mood_score = mood.get("mood_score") if mood.get("available") else None

        if prod_cfg:
            for e in pool:
                _normalize_pool_row(e)
            # 情绪同实验室：池内 S/A 档现算；配置手动锁定时用锁定值
            mo = (prod_cfg.get("mood") or {}).get("manual_override")
            if mo is not None:
                eff_mood = mo
            else:
                _m = market_mood.compute_market_mood(pool)
                eff_mood = _m.get("mood_score") if _m.get("available") else None
            weights = lab_normalize_weights(
                {k: float(v) for k, v in (prod_cfg.get("base_weights") or {}).items()},
                use_rel=False)
            bonus_coefs = {"k_align": (prod_cfg.get("bonus") or {}).get("k_align", 0.25),
                           "k_reversal": (prod_cfg.get("bonus") or {}).get("k_reversal", 0.20)}
            mkt_weights = market_weight.resolve_weights(prod_cfg.get("market_weights"))
            baseline = scoring.social_baseline(pool)
            now_dt = now_local()
            factors_by_id = {e["id"]: lab_compute_factors(e, baseline, now_dt, None)
                             for e in pool}
            scored = lab_rank_pool(pool, factors_by_id, weights, eff_mood,
                                   bonus_coefs, mkt_weights)
            data = []
            for e, factors, final, base, detail, mkt in scored[offset:offset + limit]:
                e["bonus"] = detail
                e["market"] = mkt
                e["freshness"] = freshness.explain(e)
                e["strategy"] = {"version": prod_cfg.get("_version"),
                                 "base_score": round(base, 4),
                                 "final_score": round(final, 4)}
                data.append(e)
            attach_x_posts(data, cursor)
            cursor.execute(f"SELECT COUNT(*) FROM news_events WHERE {' AND '.join(where)}",
                           params)
            total = cursor.fetchone()[0]
            cursor.close()
            # 响应形状与未部署路径完全一致（data + meta），仅 meta 多一个
            # strategy_version 供前端/调用方识别"这份排序是哪版参数算的"。
            return jsonify({"data": data, "meta": {
                "total": total, "limit": limit, "offset": offset,
                "strategy_version": prod_cfg.get("_version"),
                # 本次排序实际使用的情绪值——平价核验和排查"为什么这条有加成"
                # 都要它；不暴露的话线上排序就有一个看不见的输入。
                "mood_score": eff_mood}})
        # 2026-07-29 修：这里之前调的是 mood_alignment_multiplier——那是拆分
        # 同向/反转两个因子**之前**的旧单一倍率，策略实验室（api/lab_tools.py）
        # 早就换成了 mood_multiplier，但生产这条主排序路径一直没跟着换。后果
        # 是反转加成——PRD-03 明确要的"专门把与大盘反向的重大事件顶上来，防止
        # 回音室"——实际上从没在用户真正看到的主站生效过，只在实验室的推演里
        # 生效。同时也是"用户看不出哪条被反转命中"的根源之一：主站 API 压根
        # 没算过、没吐出过这个信息，前端自然无从展示。
        for e in pool:
            detail = market_mood.mood_multiplier(e, mood_score)
            e["bonus"] = detail
            # 市场重要性倍率（PRD-04，2026-07-29）。与情绪加成同为查询时的外层
            # 倍率，不写回 importance_score——那是"事件本身有多重要"的口径，掺进
            # "我们产品更关心哪个市场"这种运营偏好就污染了，且改权重要全库重算。
            mkt = market_weight.explain(e)
            e["market"] = mkt
            # 新鲜度衰减（crawler/freshness.py，2026-07-30）。同为查询时倍率：
            # "有多新"是"你什么时候看"的函数，写进库里必然过时——存量
            # score_timeliness 正是这么坏掉的（入库时算一次就冻住，3天前的
            # 内容 T=0.973、当天 T=0.980，时效在排序里几乎没区分度，结果旧闻
            # 靠跨轮累积信源堆高 H 反压当天真实事件）。
            fresh = freshness.explain(e)
            e["freshness"] = fresh
            e["_display_score"] = ((e.get("importance_score") or 0.0)
                                   * mkt["multiplier"] * detail["multiplier"]
                                   * fresh["multiplier"])
        pool.sort(key=lambda e: e["_display_score"], reverse=True)
        data = pool[offset:offset + limit]
        for e in data:
            e.pop("_display_score", None)
    else:
        sql = (f"SELECT {EVENT_COLUMNS} FROM news_events WHERE {' AND '.join(where)} "
              f"ORDER BY {order} LIMIT %s OFFSET %s")
        cursor.execute(sql, params + [limit, offset])
        rows = cursor.fetchall()
        data = [row_to_dict(cursor, r) for r in rows]
        # 按时间排序时不重排、不算加成（加成只服务"营造大盘氛围"的排序场景，
        # 按时间看的是"最新发生了什么"，套加成没有意义）。但字段形状必须跟
        # importance 分支一致——前端不该看到"这条有 bonus 字段、那条没有"这种
        # 靠排序方式决定 schema 的不一致，判断"有没有命中反转"时会漏判。
        for e in data:
            e["bonus"] = {"sentiment_align": 0.0, "reversal": 0.0,
                          "total_bonus": 0.0, "multiplier": 1.0}
            # 字段形状与 importance 分支保持一致（按时间排序不重排，但不能让
            # 前端因为排序方式不同就要处理两种 schema）
            e["market"] = market_weight.explain(e)
            e["freshness"] = freshness.explain(e)

    attach_x_posts(data, cursor)

    # 总数
    cursor.execute(f"SELECT COUNT(*) FROM news_events WHERE {' AND '.join(where)}", params)
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
app.register_blueprint(source_catalog_bp)
app.register_blueprint(persona_bp)


if __name__ == "__main__":
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", 8080))
    app.run(host=host, port=port, debug=False)
