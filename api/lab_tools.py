"""
策略实验室（Strategy Lab）— Tab 5 后端。独立 Flask Blueprint，只读数据库。

╔══════════════════════════════════════════════════════════════════════════╗
║ 接入方法 —— 需要在 api/server.py 里加两行（不要改动本文件之外的任何东西）：  ║
║                                                                            ║
║   1) 在文件顶部 import 区加：                                             ║
║        from api.lab_tools import lab_bp                                  ║
║                                                                            ║
║   2) 在所有路由定义之后、`if __name__ == "__main__":` 之前加：            ║
║        app.register_blueprint(lab_bp)                                    ║
║                                                                            ║
║ 加上这两行后，以下路由会自动生效：                                        ║
║   GET  /lab                     —— 策略实验室前端页面（web/lab.html）      ║
║   POST /api/tools/reweight      —— 单版本权重调节 + 实时重排              ║
║   POST /api/tools/compare       —— 两版本权重对比（换手率/升降 case/summary）║
╚══════════════════════════════════════════════════════════════════════════╝

设计原则：
  - 打分逻辑 100% 复用 crawler/scoring.py 里的 compute_impact / compute_timeliness /
    compute_hotness / compute_authority / compute_quality，不重新实现任何因子算法，
    只是把权重从写死的常量变成请求参数。
  - 相关性（Rel）因子：2026-07-26 起为**连续分**（此前是 sectors 命中与否的
    二元判断）。优先读入库时 LLM 按 skill 口径打的 sector_relevance 明细
    （0-1 连续、锚点强制、含低于发布阈值的候选），明细缺失的旧行按
    sectors 命中 0.60 / 成分币白名单 0.55 / 标题关键词 0.40 分层退化。
    查询时零 LLM 调用——实验室是拖滑块即时重算几百条的交互工具，跑不起
    每次请求调 LLM 的完整版；完整版（硬门+Rel^1.5+体裁门+传导链+去重+
    宁缺毋滥）在 /api/recommend/sector。
  - 全程只 SELECT，不写 news_events 或任何表。
  - 不依赖 api/server.py 的任何内部函数（get_db/require_api_key 等），完全自
    包含，避免和同时在改 server.py 的另一个 agent产生耦合冲突。
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, request, jsonify, redirect, send_from_directory

from crawler import freshness, market_mood, market_weight, scoring, storage
from crawler.sector_relevance import SECTOR_ANCHORS
from crawler.timeutil import now_local

# api/ 不是 package（没有 __init__.py），server.py 是以 `from lab_tools import lab_bp`
# 这种平铺方式引入同目录模块的——所以这里必须用 `import strategy_config` 而不是
# `from . import strategy_config`，后者在启动时直接 ImportError。
import strategy_config

# ─────────────────────────────────────────────────────────────────────────────
# 鉴权：与 api/server.py 里的 require_api_key 逻辑保持一致（同一个静态 token），
# 但独立实现，不 import server.py。
# ─────────────────────────────────────────────────────────────────────────────
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "***REMOVED***")

# 2026-07-26：跟 api/server.py 的 VALID_API_KEYS 保持同步——5 个可分发给不同人的
# token，同样的原因（独立实现，不 import server.py，见上面的模块说明）。
API_TOKENS = {
    "lawrence":  os.environ.get("API_TOKEN_LAWRENCE",  "***REMOVED***"),
    "team-a":    os.environ.get("API_TOKEN_TEAM_A",    "***REMOVED***"),
    "team-b":    os.environ.get("API_TOKEN_TEAM_B",    "***REMOVED***"),
    "partner-1": os.environ.get("API_TOKEN_PARTNER1",  "***REMOVED***"),
    "partner-2": os.environ.get("API_TOKEN_PARTNER2",  "***REMOVED***"),
    "web":       os.environ.get("API_TOKEN_WEB",       "***REMOVED***"),
}
VALID_API_KEYS = {API_SECRET_KEY, *API_TOKENS.values()}


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


WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

lab_bp = Blueprint("lab_tools", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# 前端页面（静态吐出，无需鉴权，与 index.html 的 /dashboard 同一模式）
# ─────────────────────────────────────────────────────────────────────────────
@lab_bp.route("/lab", methods=["GET"])
def lab_page():
    """旧的独立页面入口，2026-07-26 设计改版后 301 到主站 tab05。

    策略实验室已整页并入 index.html 的 panel-5（顶部导航 05），lab.html 不再作为
    独立页面提供——留着会变成一个没人维护、样式和数据口径都会慢慢漂移的孤儿页。
    保留这个路由是因为旧链接（文档、聊天记录、书签）还在指过来，直接 404 太粗暴。
    用 301 而不是 302：这是永久性的信息架构变更，让浏览器和爬虫更新记录。
    """
    return redirect("/#tab5", code=301)


# ─────────────────────────────────────────────────────────────────────────────
# 数据拉取
# ─────────────────────────────────────────────────────────────────────────────
POOL_COLUMNS = """
    id, title_en, title_zh, date, time_event, time_get_data,
    description_short_zh, description_long_zh,
    sectors, sector_relevance, coins, news_type, market_scope, breadth_level, event_tier,
    score_market_impact, score_breadth, score_punch, punch_magnitude_pct,
    score_timeliness, score_hotness, score_authority, score_quality,
    importance_score, is_rumor, sources, source_names, source_count, social_interactions,
    sentiment, sentiment_score, verification_status
"""

# 2026-07-30 500→1200：生产"部署到 Agent"路径固定用 1200 池（api/server.py），
# 实验室上限低于它的话，同参数请求会被静默夹到 500——池子不同 → 热度基准
# P95 不同 → H 因子不同 → 平价核验永远对不齐。上限必须 ≥ 生产池。
MAX_POOL_LIMIT = 1200


def fetch_pool(conn, days: int, limit: int) -> list[dict]:
    """拉取近 N 天**发生**的事件，转成 scoring.py 各 compute_* 函数能直接吃的 dict。

    ## 2026-07-30 修：口径从「入库时间」改成「事件时间」

    原来是 `WHERE time_get_data >= since ORDER BY time_get_data DESC LIMIT N`，
    即"最近入库的 N 条"。这在增量抓取下没问题——入库顺序约等于发生顺序。
    但一次**批量回填**就会把它彻底击穿：当天回填 3454 条 Benzinga 历史新闻
    （按 published 升序拉，所以先入库的是最老的），pipeline 消费掉 800 条后，
    "最近入库的 300 条"变成了 **300/300 全是 Benzinga、且全是 7/27-7/28 的旧闻**
    ——实验室首屏于是只剩一个信源的旧新闻，29/30 号的内容一条都进不了池子。

    这不是回填的锅，是这个查询把「我们什么时候把它写进库」当成了「它什么时候
    发生」。两者在稳态下相关、在回填时完全脱钩。生产 /api/news 一直是按
    `date`（事件日期）过滤的，实验室却按入库时间——**同一个产品的两个界面用
    不同的时间轴取数**，本身就是不一致的根源。改成与生产同一根轴。

    COALESCE(time_event, date)：time_event 是 LLM 从正文读出的真实发生时间，
    缺失时退化到 date（日期粒度），两者都没有才用 time_get_data 兜底——
    不兜底会让老数据整批消失。
    """
    since = (now_local() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT {POOL_COLUMNS} FROM news_events "
        f"WHERE COALESCE(time_event, date, time_get_data) >= %s "
        f"ORDER BY COALESCE(time_event, date, time_get_data) DESC LIMIT %s",
        (since, limit),
    )
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    cursor.close()

    events = []
    for row in rows:
        d = dict(zip(cols, row))
        for f in ("sectors", "sector_relevance", "coins", "source_names", "sources"):
            v = d.get(f)
            if isinstance(v, str):
                try:
                    d[f] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    d[f] = []
            elif v is None:
                d[f] = []
        # scoring.compute_timeliness 要读 published_at；库里是 time_event（真实新闻时间），
        # 缺失时退化用 time_get_data（入库时间），比给 0.5 中性分更贴近真实新鲜度。
        published = d.get("time_event") or d.get("time_get_data")
        d["published_at"] = published.isoformat() if hasattr(published, "isoformat") else published
        for k in ("date", "time_event", "time_get_data"):
            v = d.get(k)
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        events.append(d)
    return events


# ─────────────────────────────────────────────────────────────────────────────
# 权重归一化 + 因子计算（复用 scoring.py，不重新发明）
# ─────────────────────────────────────────────────────────────────────────────
# 2026-07-29（PRD-03 R6）：五因子 → 七因子，并把「加分项」与「基础因子」分开。
#
# 基础因子：权重归一化到 1.0，加权求和得 BaseScore。
# 加分项：不参与归一化，作为外层倍率 (1 + Σbonus) 应用在 BaseScore 上。
# 分开的理由见 ADR-001 D1——加分项依赖每天都在变的 mood_score，做成加权项会让
# 跨天分数不可比；做成外层倍率则 BaseScore 保持可比，且系数调 0 即可退回原排序。
FACTOR_KEYS = ["M", "B", "T", "I", "H", "A", "Q", "Rel"]
FACTOR_NAME = {"M": "影响面", "B": "广度", "T": "时效性", "I": "冲击力",
               "H": "热度", "A": "权威性", "Q": "质量", "Rel": "相关性"}
DEFAULT_RAW_WEIGHTS = {"M": 0.26, "B": 0.16, "T": 0.16, "I": 0.14,
                       "H": 0.10, "A": 0.10, "Q": 0.08, "Rel": 0.0}

# 加分项（与基础因子分开展示、分开调节）
BONUS_KEYS = ["k_align", "k_reversal"]
BONUS_NAME = {"k_align": "情绪同向加成", "k_reversal": "反转信号加成"}
DEFAULT_BONUS = {"k_align": market_mood.MOOD_ALIGN_BOOST,
                 "k_reversal": market_mood.MOOD_REVERSAL_BOOST}
BONUS_NOTE = (
    "加分项不参与权重归一化，作为外层倍率 (1 + 同向 + 反转) 应用在基础分上，合计封顶 +"
    f"{int(market_mood.BONUS_TOTAL_CAP * 100)}%。"
    "同向加成让首屏跟着大盘氛围走；反转加成专门把「与大盘反向的重大事件」顶上来，"
    "防止大盘单边时首屏变成回音室——它只对 S/A 档生效，低档位的反向噪音不会被扶上来。"
    "两个系数都调 0 即退回纯基础排序（也是验证它们真实贡献的 A/B 对照方式）。"
)

# 市场重要性权重（PRD-04，2026-07-29）。与基础因子、加分项并列的第三组可调参数，
# 三者量纲不同：基础因子是归一化到 100% 的权重份额，加分项是百分比上限，
# 市场重要性是**直接相乘的倍率**。
MARKET_KEYS = ["us_stock", "crypto", "macro_policy", "social_signal",
               "general", "hk_stock", "jp_stock", "kr_stock"]
MARKET_NAME = {"us_stock": "美股", "crypto": "加密", "macro_policy": "经济政策",
               "social_signal": "社会信号", "general": "综合",
               "hk_stock": "港股", "jp_stock": "日股", "kr_stock": "韩股"}
MARKET_NOTE = (
    "市场重要性是作用在基础分上的**直接倍率**，不参与因子归一化。"
    "起因：tier 是 LLM 相对『事件自己所在的市场』判定的，但排序是全局的——"
    "实测韩股 S 档率 13.6%、美股只有 0.15%（差 90 倍），而韩股供给量只有美股的 1/15，"
    "结果小市场的本地大新闻长期压过大市场的全球相关新闻。"
    "**cross_market 豁免**：广度为『跨市场』的事件不打折（权重下限提到 1.0）——"
    "这直接对应『日韩在剧烈波动且影响到美国市场时才值得看』，"
    "比如「油价飙升拖累韩国KOSPI跌7%」是跨市场、照常出，"
    "而「韩财长就单一个股杠杆ETF致歉」是单一大盘、按 0.55 折价沉下去。"
    "全部调回 1.0 即退回改造前的排序（A/B 对照方式）。"
)

REL_NOTE = (
    "相关性为连续分（2026-07-26 起）：优先取入库时 LLM 按 skill 口径打的连续相关度"
    "（0-1，锚点强制，覆盖 86% 库存），旧行按 sectors 命中 0.60 / 成分币白名单 0.55 / "
    "标题关键词 0.40 分层退化，查询时零 LLM 成本。注意实验室里 Rel 是可调权重因子（探索用），"
    "生产 Sector Insight 用的是「硬门 Rel≥0.5 + Rel^1.5 外层乘子」——要看生产口径结果，"
    "请调用 /api/recommend/sector。"
)


def normalize_weights(raw: dict, use_rel: bool) -> dict:
    """把用户输入的任意权重归一化成合计 1.0。用户不需要自己凑够 1.0。

    全 0 或非法输入时退化为参与因子间的等权，而不是报错——这是个探索工具，
    不该因为用户把滑块全拖到 0 就崩掉。
    """
    raw = raw or {}
    w = {}
    for k in FACTOR_KEYS:
        try:
            v = float(raw.get(k, DEFAULT_RAW_WEIGHTS[k]))
        except (TypeError, ValueError):
            v = DEFAULT_RAW_WEIGHTS[k]
        w[k] = max(0.0, v)
    if not use_rel:
        w["Rel"] = 0.0

    total = sum(w.values())
    if total <= 0:
        active = ["M", "T", "H", "A", "Q"] + (["Rel"] if use_rel else [])
        eq = 1.0 / len(active)
        return {k: (eq if k in active else 0.0) for k in FACTOR_KEYS}
    return {k: v / total for k, v in w.items()}


def compute_relevance(event: dict, sector: str) -> float:
    """连续相关性——skill v5.1 口径的查询时便宜近似（零 LLM 调用）。

    分层取值（高优先级在前）：
      1. 入库时 LLM 打的连续分：sector_relevance 明细里找目标板块。这就是
         「真相关才打」量化的产物（0-1 连续、anchor 强制、低于 0.55 发布阈值的
         候选也保留在明细里），86% 的库存事件有这层数据。
      2. 明细缺失的旧行（内容标签上线前入库）但 sectors 命中 → 0.60：它通过过
         当时的发布门，给保守中档，不冒充精确。
      3. coins ∩ 板块成分币白名单（SECTOR_ANCHORS.tickers）→ 0.55：skill 里
         "1 跳、成分资产涉入"档位的下缘。
      4. 标题命中板块关键词 → 0.40：有语义迹象但按 skill 不足以过 0.5 硬门。
      5. 其余 → 0.0。

    注意本工具里 Rel 是**可调权重的内层因子**（探索用），与生产 Sector Insight
    的"硬门 + Rel^1.5 外层乘子"用法刻意不同——实验室的意义就是让用户自由调配
    权重看排序变化，硬门会让滑块失去意义。要看生产口径的结果，用
    /api/recommend/sector 或评测工具的 AB 对比。
    """
    for tag in event.get("sector_relevance") or []:
        if isinstance(tag, dict) and tag.get("sector") == sector:
            try:
                return max(0.0, min(1.0, float(tag.get("relevance", 0.0))))
            except (TypeError, ValueError):
                break
    if sector in (event.get("sectors") or []):
        return 0.60
    anchors = SECTOR_ANCHORS.get(sector) or {}
    coins = set(event.get("coins") or [])
    if coins & set(anchors.get("tickers") or ()):
        return 0.55
    title = f"{event.get('title_en') or ''} {event.get('title_zh') or ''}".lower()
    if any(kw in title for kw in (anchors.get("keywords") or [])):
        return 0.40
    return 0.0


def compute_factors(event: dict, baseline: float, now: datetime, sector: str | None) -> dict:
    """七因子 + 可选 Rel，逐字段调用 scoring.py 的既有函数。"""
    factors = {
        "M": scoring.compute_impact(event),
        "B": scoring.compute_breadth(event),
        "T": scoring.compute_timeliness(event, now),
        # 冲击力优先用入库时算好的值；存量老行没有该字段则现算一次
        # （纯正则+信源统计，零 LLM 成本，不怕在查询路径上跑）。
        "I": (float(event["score_punch"]) if event.get("score_punch") is not None
              else scoring.compute_punch(event)["score"]),
        "H": scoring.compute_hotness(event, baseline),
        # A 不能再调 compute_authority：库里的 score_authority 存的已经是
        # 折扣后的终值（rumor ×0.7 + verification 降权都在入库打分时应用过，
        # 见 scoring.compute_macro_score → storage.write_events 的写入链）。
        # 再调一遍会对 rumor/未验证事件二次折扣（2026-07-26 review 确认）。
        # 直接用存量值，夹紧到 [0,1] 即可。
        "A": min(1.0, max(0.0, float(event.get("score_authority") or 0.0))),
        "Q": scoring.compute_quality(event),
    }
    if sector:
        factors["Rel"] = compute_relevance(event, sector)
    else:
        factors["Rel"] = 0.0
    return factors


def weighted_score(factors: dict, weights: dict) -> float:
    return sum(weights[k] * factors[k] for k in FACTOR_KEYS)


def source_class(source_names) -> str:
    """粗粒度信源分类，仅供 summary 里做规则统计用，不进打分。

    命名约定本身就带类型信息：X/ 前缀 = KOL 推文原声，"快讯" = 快讯类聚合信源，
    "公告" = 官方公告；三者都不是就归到"主流媒体/研究机构"一档。
    """
    names = source_names or []
    if any(str(n).startswith("X/") for n in names):
        return "social"
    if any("快讯" in str(n) for n in names):
        return "flash"
    if any("公告" in str(n) for n in names):
        return "official"
    return "media"


CLASS_LABEL = {
    "social": "社交媒体/KOL 来源",
    "flash": "快讯类信源",
    "official": "官方公告类信源",
    "media": "主流媒体/研究机构来源",
}


def event_card(e: dict, factors: dict | None = None, score: float | None = None,
                rank: int | None = None, prod_rank: int | None = None,
                weights: dict | None = None, bonus: dict | None = None,
                base_score: float | None = None, market: dict | None = None) -> dict:
    card = {
        "id": e["id"],
        "title_zh": e.get("title_zh"),
        "title_en": e.get("title_en"),
        # 2026-07-29：补正文。此前卡片只有标题，用户点开看不到内容，
        # 没法判断"这条为什么排这么高"——Lawrence 原话「现在不够好用」。
        "description_short_zh": e.get("description_short_zh"),
        "description_long_zh": e.get("description_long_zh"),
        "event_tier": e.get("event_tier"),
        "news_type": e.get("news_type"),
        "market_scope": e.get("market_scope"),
        "breadth_level": e.get("breadth_level"),
        "punch_magnitude_pct": e.get("punch_magnitude_pct"),
        "sentiment": e.get("sentiment"),
        "sentiment_score": e.get("sentiment_score"),
        "sectors": e.get("sectors"),
        "coins": e.get("coins"),
        "source_names": e.get("source_names"),
        # 2026-07-29：补原文信源链接。此前卡片只有 source_names（纯名字，没有
        # url），点开展开区没法直接跳到原文核实——Lawrence 明确要"点开要有
        # 信息源链接"。sources 明细本身在 crawler/storage.py 写库时就有
        # {name, url, authority} 结构，只是策略实验室这条查询路径之前没选它。
        "sources": e.get("sources"),
        "source_count": e.get("source_count"),
        "is_rumor": bool(e.get("is_rumor")),
        "verification_status": e.get("verification_status"),
        "importance_score": e.get("importance_score"),
        "time_event": e.get("time_event"),
    }
    if factors is not None:
        card["factors"] = {k: round(v, 4) for k, v in factors.items()}
        # 每个因子的**加权贡献值**——只给原始分用户还得自己乘权重心算，
        # 直接给出贡献值才看得出"这条排高是被哪个因子推上去的"。
        if weights:
            card["contributions"] = {
                k: round(weights.get(k, 0.0) * v, 4) for k, v in factors.items()}
    if bonus is not None:
        card["bonus"] = bonus
    if market is not None:
        # 市场重要性明细（含是否命中 cross_market 豁免），供实验室展示
        # "为什么这条被折价 / 为什么它没被折价"
        card["market"] = market
    if base_score is not None:
        card["base_score"] = round(base_score, 4)
    if score is not None:
        card["score"] = round(score, 4)
    if rank is not None:
        card["rank"] = rank
    if prod_rank is not None:
        card["production_rank"] = prod_rank
    return card


def _lab_mood_score(conn_events: list[dict]):
    """用当前池子里的 S/A 档事件现算大盘情绪。

    刻意不复用 server.py 的 /api/market-mood 缓存：实验室是**探索工具**，
    用户可能把 days 调成 30 天来看长周期，那时的"大盘情绪"应当是这个池子的
    情绪，而不是生产环境固定 48 小时窗口的那个值。口径跟着用户选的池子走，
    结果才可解释。
    """
    res = market_mood.compute_market_mood(conn_events)
    return res.get("mood_score") if res.get("available") else None


def resolve_mood(events: list[dict], raw):
    """决定这次重排用哪个大盘情绪值。

    2026-07-30 新增「大盘情绪方向」控件（Lawrence："增加一个大盘情绪的因子，
    让我可以直接调控情绪方向"）。语义：

      · raw 为 None / 缺失 / "auto"  → 用池子现算的实时情绪（原行为）
      · raw 是 -1..1 的数字          → **人工指定**，覆盖实时值

    人工指定的价值在于**反事实推演**：实时情绪是什么样，取决于最近恰好发生了
    什么，不可控；而"如果此刻大盘极度悲观，我这套权重会把什么顶上首屏"是产品
    决策真正要回答的问题。没有这个控件就只能干等到市场真的崩一次才能验证。

    返回 (mood_score, is_manual)——is_manual 要透传到前端，否则用户看到一个
    情绪值却分不清是实时算的还是自己刚拖出来的。
    """
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in ("", "auto")):
        return _lab_mood_score(conn_events=events), False
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return _lab_mood_score(conn_events=events), False
    return max(-1.0, min(1.0, v)), True


def resolve_bonus_coefs(raw: dict) -> dict:
    """解析加分项系数。非法/缺失回落默认值，负数夹到 0（加分项不做惩罚）。"""
    raw = raw or {}
    out = {}
    for k in BONUS_KEYS:
        try:
            v = float(raw.get(k, DEFAULT_BONUS[k]))
        except (TypeError, ValueError):
            v = DEFAULT_BONUS[k]
        out[k] = max(0.0, min(1.0, v))
    return out


def rank_pool(events: list[dict], factors_by_id: dict, weights: dict,
              mood_score=None, bonus_coefs: dict | None = None,
              market_weights: dict | None = None):
    """四段式打分排序：BaseScore(加权) × 市场重要性 × 新鲜度 × (1 + 加分项)。

    返回 [(event, factors, final_score, base_score, bonus_detail, market_detail), ...]
    降序。mood_score 为 None（大盘情绪不可用）时加分项全为 0，退化成纯基础排序。

    市场重要性倍率是 2026-07-29 加的（PRD-04）：tier 是相对"自己所在市场"判定的，
    但排序是全局的，导致韩股 S 档率是美股的 90 倍、供给只有 1/15 却占了 2 倍的
    首屏位置。详见 crawler/market_weight.py。

    新鲜度衰减是 2026-07-30 补进来的（crawler/freshness.py）。当天先加进了生产
    排序（api/server.py），实验室这边漏了——结果是**同一套权重在两个界面算出
    不同的排名**：生产首屏是 7/29-7/30 的内容，实验室却把 7/27-7/28 的旧闻排在
    前面。实验室的全部意义在于"我在这里调的就是线上跑的那套"，两边公式不一致
    的话，调参结论直接失效。补齐后两边是同一个公式。
    """
    bonus_coefs = bonus_coefs or DEFAULT_BONUS
    scored = []
    for e in events:
        f = factors_by_id[e["id"]]
        base = weighted_score(f, weights)
        # v3 公式的 CNBC 编辑背书 +0.05（scoring.CNBC_COVER_BONUS）。实验室
        # 必须与生产同公式——今天刚为"实验室漏了新鲜度衰减"付过一次学费。
        if scoring.cnbc_covered(e):
            base = min(1.0, base + scoring.CNBC_COVER_BONUS)
        detail = market_mood.mood_multiplier(
            e, mood_score,
            k_align=bonus_coefs.get("k_align"),
            k_reversal=bonus_coefs.get("k_reversal"))
        mkt = market_weight.explain(e, market_weights)
        fresh = freshness.decay_multiplier(e)
        final = base * mkt["multiplier"] * fresh * detail["multiplier"]
        scored.append((e, f, final, base, detail, mkt))
    scored.sort(key=lambda x: -x[2])
    return scored


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/tools/reweight —— 单版本权重调节 + 实时重排
# ─────────────────────────────────────────────────────────────────────────────
@lab_bp.route("/api/tools/reweight", methods=["POST"])
@require_api_key
def reweight():
    body = request.get_json(force=True, silent=True) or {}
    days = max(1, int(body.get("days", 7)))
    pool_limit = min(int(body.get("pool_limit", 300)), MAX_POOL_LIMIT)
    sector = (body.get("sector") or None) or None
    weights_raw = body.get("weights", {})

    conn = storage.get_mysql_conn()
    try:
        events = fetch_pool(conn, days, pool_limit)
    finally:
        conn.close()

    top_n = min(int(body.get("top_n", 30)), max(1, len(events)))
    now = now_local()
    baseline = scoring.social_baseline(events)
    use_rel = bool(sector)
    weights = normalize_weights(weights_raw, use_rel)

    bonus_coefs = resolve_bonus_coefs(body.get("bonus", {}))
    mkt_weights = market_weight.resolve_weights(body.get("market_weights"))
    mood, mood_manual = resolve_mood(events, body.get("mood_override"))

    factors_by_id = {e["id"]: compute_factors(e, baseline, now, sector) for e in events}
    scored = rank_pool(events, factors_by_id, weights, mood, bonus_coefs, mkt_weights)

    prod_order = sorted(events, key=lambda e: -(e.get("importance_score") or 0))
    prod_rank = {e["id"]: i + 1 for i, e in enumerate(prod_order)}

    results = []
    for rank, (e, factors, s, base, detail, mkt) in enumerate(scored[:top_n], start=1):
        card = event_card(e, factors, s, rank, prod_rank.get(e["id"]),
                          weights=weights, bonus=detail, base_score=base,
                          market=mkt)
        p_rank = prod_rank.get(e["id"])
        card["rank_delta"] = (p_rank - rank) if p_rank is not None else None
        results.append(card)

    return jsonify({
        "meta": {
            "pool_size": len(events),
            "days": days,
            "sector": sector,
            "rel_enabled": use_rel,
            "rel_note": REL_NOTE if use_rel else None,
            "weights_normalized": {k: round(v, 4) for k, v in weights.items()},
            "factor_names": FACTOR_NAME,
            "bonus_coefs": bonus_coefs,
            "bonus_names": BONUS_NAME,
            "bonus_note": BONUS_NOTE,
            "market_weights": mkt_weights,
            "market_names": MARKET_NAME,
            "market_note": MARKET_NOTE,
            "mood_score": mood,
            # 前端要能区分"这个情绪值是实时算的"还是"我自己拖出来的"，
            # 否则拖完滑杆看到一个数字，分不清生效没有。
            "mood_manual": mood_manual,
            "social_baseline": round(baseline, 1),
            "generated_at": now.isoformat(),
        },
        "results": results,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/tools/compare —— 两版本对比：换手率 / 上升下降 case / 自动 summary
# ─────────────────────────────────────────────────────────────────────────────
@lab_bp.route("/api/tools/compare", methods=["POST"])
@require_api_key
def compare():
    body = request.get_json(force=True, silent=True) or {}
    days = max(1, int(body.get("days", 7)))
    pool_limit = min(int(body.get("pool_limit", 300)), MAX_POOL_LIMIT)
    sector = (body.get("sector") or None) or None
    weights_a_raw = body.get("weights_a", {})
    weights_b_raw = body.get("weights_b", {})
    label_a = str(body.get("label_a") or "版本 A")[:40]
    label_b = str(body.get("label_b") or "版本 B")[:40]

    conn = storage.get_mysql_conn()
    try:
        events = fetch_pool(conn, days, pool_limit)
    finally:
        conn.close()

    if not events:
        # 这里以前配的是 HTTP 200：带 error 字段却是成功状态码，和全服务的错误语义
        # 相反（其它地方任何 {"error": ...} 都配非 2xx），任何按状态码判断成败的
        # 调用方都会把这次"没数据"当成一次正常返回。请求本身是合法的，只是这个
        # 时间窗里没有任何事件可对比，语义上最接近"资源不存在"，用 404
        # （与 history_tools.py 里"查不到记录"用 404 保持一致）。
        # 前端 lab.html 的 api() 对非 2xx 会抛 Error(j.error)，runCompare 有 .catch
        # 兜底渲染同一句提示，这个改动不会让页面卡在 loading。
        return jsonify({"error": "指定时间范围内没有事件数据"}), 404

    top_n = min(int(body.get("top_n", 20)), len(events))
    case_limit = min(int(body.get("case_limit", 8)), 30)

    now = now_local()
    baseline = scoring.social_baseline(events)
    use_rel = bool(sector)
    weights_a = normalize_weights(weights_a_raw, use_rel)
    weights_b = normalize_weights(weights_b_raw, use_rel)

    # 因子只需算一次：M/T/H/A/Q/Rel 不依赖权重，权重只影响加权求和。
    factors_by_id = {e["id"]: compute_factors(e, baseline, now, sector) for e in events}
    event_by_id = {e["id"]: e for e in events}

    # 两版可以各带各的加分项系数——这正是验证"加分项到底有没有用"的方式：
    # A 版把系数调 0、B 版开着，对比换手率与升降 case 即为 A/B 对照。
    bonus_a = resolve_bonus_coefs((body.get("version_a") or {}).get("bonus", {}))
    bonus_b = resolve_bonus_coefs((body.get("version_b") or {}).get("bonus", {}))
    # 两版共用同一个情绪值（含人工指定）：对比的是**权重差异**，情绪必须是
    # 受控变量，两边各算各的就分不清排序变化来自权重还是来自情绪。
    mood, _mood_manual = resolve_mood(events, body.get("mood_override"))

    mkt_weights = market_weight.resolve_weights(body.get("market_weights"))
    scored_a = rank_pool(events, factors_by_id, weights_a, mood, bonus_a, mkt_weights)
    scored_b = rank_pool(events, factors_by_id, weights_b, mood, bonus_b, mkt_weights)

    rank_a = {e["id"]: i + 1 for i, (e, *_rest) in enumerate(scored_a)}
    rank_b = {e["id"]: i + 1 for i, (e, *_rest) in enumerate(scored_b)}
    score_a = {t[0]["id"]: t[2] for t in scored_a}
    score_b = {t[0]["id"]: t[2] for t in scored_b}

    top_a_ids = [t[0]["id"] for t in scored_a[:top_n]]
    top_b_ids = [t[0]["id"] for t in scored_b[:top_n]]
    set_a, set_b = set(top_a_ids), set(top_b_ids)
    overlap = set_a & set_b
    turnover_rate = 1.0 - (len(overlap) / top_n if top_n else 0.0)

    only_in_a = [event_card(event_by_id[i], factors_by_id[i], score_a[i], rank_a[i], None)
                 for i in top_a_ids if i not in set_b]
    only_in_b = [event_card(event_by_id[i], factors_by_id[i], score_b[i], rank_b[i], None)
                 for i in top_b_ids if i not in set_a]

    # 排名变化 case：限定在"至少在其中一个版本里排得比较靠前"的范围内看，
    # 避免把两个都在第 280 名徘徊的无关紧要事件也算作显著变化。
    zone = max(top_n * 3, 60)
    deltas = []
    for eid in rank_a:
        ra, rb = rank_a[eid], rank_b[eid]
        if min(ra, rb) <= zone:
            deltas.append((eid, rb - ra))  # 正数 = 相对 B，在 A 里排名上升

    def _case(eid, delta):
        e = event_by_id[eid]
        c = event_card(e, factors_by_id[eid])
        c["rank_a"] = rank_a[eid]
        c["rank_b"] = rank_b[eid]
        c["score_a"] = round(score_a[eid], 4)
        c["score_b"] = round(score_b[eid], 4)
        c["delta"] = delta
        return c

    rising = sorted([d for d in deltas if d[1] > 0], key=lambda x: -x[1])[:case_limit]
    falling = sorted([d for d in deltas if d[1] < 0], key=lambda x: x[1])[:case_limit]
    rising_cases = [_case(eid, d) for eid, d in rising]
    falling_cases = [_case(eid, d) for eid, d in falling]

    summary = build_summary(
        events=event_by_id, rank_a=rank_a, rank_b=rank_b,
        weights_a=weights_a, weights_b=weights_b,
        turnover_rate=turnover_rate, top_n=top_n,
        label_a=label_a, label_b=label_b, sector=sector,
        rising_cases=rising_cases, falling_cases=falling_cases,
    )

    top_a_list = [event_card(event_by_id[i], factors_by_id[i], score_a[i], r + 1)
                  for r, i in enumerate(top_a_ids)]
    top_b_list = [event_card(event_by_id[i], factors_by_id[i], score_b[i], r + 1)
                  for r, i in enumerate(top_b_ids)]

    return jsonify({
        "meta": {
            "pool_size": len(events),
            "days": days,
            "sector": sector,
            "rel_enabled": use_rel,
            "rel_note": REL_NOTE if use_rel else None,
            "weights_a_normalized": {k: round(v, 4) for k, v in weights_a.items()},
            "weights_b_normalized": {k: round(v, 4) for k, v in weights_b.items()},
            "label_a": label_a, "label_b": label_b,
            "social_baseline": round(baseline, 1),
            "generated_at": now.isoformat(),
        },
        "top_a": top_a_list,
        "top_b": top_b_list,
        "turnover": {
            "top_n": top_n,
            "overlap_count": len(overlap),
            "turnover_rate": round(turnover_rate, 4),
            "only_in_a": only_in_a,
            "only_in_b": only_in_b,
        },
        "rising_cases": rising_cases,
        "falling_cases": falling_cases,
        "summary": summary,
    })


def build_summary(events, rank_a, rank_b, weights_a, weights_b, turnover_rate, top_n,
                   label_a, label_b, sector, rising_cases, falling_cases) -> str:
    """纯规则生成的对比总结，不调用任何 LLM。"""
    lines = []

    # 1) 权重差异最大的因子
    diffs = {k: weights_a.get(k, 0) - weights_b.get(k, 0) for k in FACTOR_KEYS}
    top_factor = max(diffs, key=lambda k: abs(diffs[k]))
    diff_val = diffs[top_factor]
    if abs(diff_val) >= 0.005:
        direction = "提高" if diff_val > 0 else "降低"
        lines.append(
            f"{label_a} 相较 {label_b}，「{FACTOR_NAME[top_factor]}」权重{direction}了 "
            f"{abs(diff_val) * 100:.0f} 个百分点"
            f"（{weights_b.get(top_factor, 0) * 100:.0f}% → {weights_a.get(top_factor, 0) * 100:.0f}%），"
            f"是本次对比里变化最大的因子。"
        )

    # 2) 换手率
    changed = round(turnover_rate * top_n)
    lines.append(f"Top{top_n} 换手率 {turnover_rate * 100:.0f}%：两版本 Top{top_n} 里约有 {changed} 条新闻不重合。")

    # 3) 按信源类型分组的平均排名变化（规则统计，不猜测语义）
    group_deltas = defaultdict(list)
    for eid in rank_a:
        cls = source_class(events[eid].get("source_names"))
        group_deltas[cls].append(rank_b[eid] - rank_a[eid])  # 正数：在 A 里排名相对上升
    group_avg = {c: sum(v) / len(v) for c, v in group_deltas.items() if v}
    ordered = sorted(group_avg.items(), key=lambda x: -x[1])
    if len(ordered) >= 2 and (ordered[0][1] - ordered[-1][1]) >= 1.0:
        best_c, best_v = ordered[0]
        worst_c, worst_v = ordered[-1]
        lines.append(
            f"{CLASS_LABEL.get(best_c, best_c)}平均排名"
            f"{'上升' if best_v >= 0 else '下降'} {abs(best_v):.1f} 位，"
            f"{CLASS_LABEL.get(worst_c, worst_c)}平均"
            f"{'上升' if worst_v >= 0 else '下降'} {abs(worst_v):.1f} 位。"
        )

    # 4) 相关性因子说明（如果启用了）
    if sector and (weights_a.get("Rel", 0) > 0 or weights_b.get("Rel", 0) > 0):
        lines.append(
            f"已启用「{sector}」板块相关性因子（简化版：命中记 1.0，否则 0.0）；"
            f"完整版 Sector Insight 相关性算法尚未上线。"
        )

    # 5) 举例佐证（最多各举 1 条，具体列表见 rising_cases/falling_cases）
    if rising_cases:
        c = rising_cases[0]
        title = c.get("title_zh") or c.get("title_en") or c["id"]
        lines.append(f"上升幅度最大：《{title}》从第 {c['rank_b']} 名升至第 {c['rank_a']} 名。")
    if falling_cases:
        c = falling_cases[0]
        title = c.get("title_zh") or c.get("title_en") or c["id"]
        lines.append(f"下降幅度最大：《{title}》从第 {c['rank_b']} 名降至第 {c['rank_a']} 名。")

    return " ".join(lines) if lines else "两版本权重差异极小，排序基本没有变化。"


# ─────────────────────────────────────────────────────────────────────────────
# 排序策略基线配置 —— GET/POST /api/strategy-config，POST /api/strategy-config/rollback
#
# 2026-07-30 新增（Lawrence："增加一个存为基线的按钮，点击后弹窗提示是否确认
# 替换基线...那么就需要你把排序公式的参数做成真的配置化的，而不是写死的"）。
#
# 本轮的生效范围是**策略实验室的默认配置（04/05）**：打开实验室时滑杆从这里
# 初始化，而不是从代码常量。01/02/03 的生产排序**暂不接入**——那要把生产从
# 「读入库时算好的 importance_score」改成「查询时按配置重算」，是排序主路径的
# 改动，按 Lawrence 的决定放到展示之后再做（见 docs/WORKLOG.md 需求 #84）。
#
# 表结构与"为什么是整份快照而不是 key-value"见 config/migrations/016_strategy_config.sql，
# 校验与兜底策略见 api/strategy_config.py 的模块说明。
# ─────────────────────────────────────────────────────────────────────────────
@lab_bp.route("/api/strategy-config", methods=["GET"])
@require_api_key
def strategy_config_get():
    conn = storage.get_mysql_conn()
    try:
        cfg = strategy_config.get_active(conn)
        versions = strategy_config.list_versions(conn)
    finally:
        conn.close()
    return jsonify({"config": cfg, "versions": versions,
                    "defaults": strategy_config.DEFAULTS})


@lab_bp.route("/api/strategy-config", methods=["POST"])
@require_api_key
def strategy_config_save():
    body = request.get_json(force=True, silent=True) or {}
    payload = body.get("config")
    if payload is None:
        return jsonify({"error": "缺少 config 字段"}), 400

    conn = storage.get_mysql_conn()
    try:
        cfg = strategy_config.save_baseline(
            conn, payload,
            note=(body.get("note") or None),
            created_by=(body.get("created_by") or "lab"))
    except strategy_config.ConfigError as e:
        # 校验失败必须把**具体哪一项不合法**告诉前端——弹窗里只显示"保存失败"
        # 用户无从下手，而这类错误恰恰都是可以自己改对的。
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()
    return jsonify({"ok": True, "config": cfg, "version": cfg["_version"]})


@lab_bp.route("/api/strategy-config/deploy", methods=["POST"])
@require_api_key
def strategy_config_deploy():
    """部署到生产（"部署到 Agent"）。与 rollback 分开：rollback 挪的是实验室
    默认指针，deploy 挪的是生产指针——生产从此按该版本参数查询时实时计算
    排序（api/server.py 的 importance 分支）。"""
    body = request.get_json(force=True, silent=True) or {}
    try:
        version = int(body.get("version"))
    except (TypeError, ValueError):
        return jsonify({"error": "version 必须是整数"}), 400
    conn = storage.get_mysql_conn()
    try:
        cfg = strategy_config.deploy_to_prod(conn, version)
    except strategy_config.ConfigError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()
    return jsonify({"ok": True, "version": cfg["_version"], "config": cfg})


@lab_bp.route("/api/strategy-config/rollback", methods=["POST"])
@require_api_key
def strategy_config_rollback():
    body = request.get_json(force=True, silent=True) or {}
    try:
        version = int(body.get("version"))
    except (TypeError, ValueError):
        return jsonify({"error": "version 必须是整数"}), 400

    conn = storage.get_mysql_conn()
    try:
        cfg = strategy_config.rollback(conn, version)
    except strategy_config.ConfigError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()
    return jsonify({"ok": True, "config": cfg, "version": cfg["_version"]})
