"""
dxFeed News —— 美股/宏观新闻实时源（2026-07-28 新增）

背景：Lawrence 转发了公司通过 Binance 账号采购的 dxFeed 试用凭据（同事 Drew Zhu
在跟 dxFeed 对接 Fundamental + News 两个服务），用户原话"这是公司给的账号...
有的话就用"。实测确认可用：`https://news.dxfeed.com` 用 HTTP Basic Auth
（用户名 binance），聚合的是 MT Newswires 的机构级实时美股新闻——比 Google
News 搜索抓回来的内容权威得多、也更及时（分钟级），正好补上美股/宏观这块
"不能只靠搜索引擎兜底"的缺口。

## 为什么限定一份精选 symbol 清单，而不是拉全量

裸查询（不带 symbol 参数）是机构新闻的完整消防水管：绝大多数是单只小盘股的
SEC Form 4 内部人交易披露、常规财报细节这类 C/D 档噪音——真实抓了一把回来，
几十条里只有大盘 ETF/宏观那一条真正重要。全量拉回来意味着为这些注定被系统
打成低分的内容付一遍 LLM 结构化的钱。这份精选清单只覆盖：主要指数/波动率、
跟踪大盘的头部 ETF、市值最大的科技股（真正能带动大盘的那几家）、以及和
B9 用户高度相关的加密概念股——覆盖"这条新闻大概率会影响大盘或情绪"的那个子集，
不追求覆盖每一条个股新闻。

## 关于 url 字段

dxFeed 不提供可公开跳转的文章链接（这是订阅制机构数据商的通行做法，内容本身
就是产品）。用 `?id=<id>` 拼一个可回查的引用链接——同样需要 Basic Auth 才能
打开，类似"彭博终端 ID"这种引用方式，比塞一个假 URL 更诚实。
"""
import logging

import requests

logger = logging.getLogger(__name__)

DXFEED_NEWS_BASE = "https://news.dxfeed.com/"

# 主要指数/波动率 + 跟踪大盘的头部 ETF + 市值最大的科技股 + 加密概念股。
# 见模块头部说明——精选而非全量，是成本控制的第一道闸。
DXFEED_SYMBOLS = [
    "SPX", "DJI", "IXIC", "RUT", "VIX",           # 大盘指数 + 波动率
    "SPY", "QQQ", "DIA", "IWM",                    # 头部 ETF
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",  # 市值最大的科技股
    "COIN", "MSTR", "GLXY", "MARA", "RIOT",        # 加密概念股
]

# 大盘/ETF 级 symbol —— 命中这些的条目走高优先级（PRD-03 R1）。
# Lawrence 明确要保留个股大底池，所以这里做的是**优先级区分**而不是过滤：
# 个股新闻照抓照存，只是排在大盘后面处理。
DXFEED_INDEX_SYMBOLS = {"SPX", "DJI", "IXIC", "RUT", "VIX", "SPY", "QQQ", "DIA", "IWM"}

MAX_ITEMS_PER_QUERY = 50
REQUEST_TIMEOUT = 20

# 实测发现的硬限：symbol 参数一次最多传 10 个，超过直接 400（"Invalid parameters"，
# 不是限流也不是无效 ticker——逐个测过 DXFEED_SYMBOLS 里每一个都能单独查通，
# 问题就是数量）。21 个精选 symbol 分批查，每批 ≤10。
_SYMBOL_BATCH_SIZE = 10


def _batches(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def fetch_dxfeed_news() -> list[dict]:
    """返回 news_events 兼容的 item 列表。凭据缺失或单批请求失败时该批跳过，
    不抛异常——这是一路免费信源之外新加的付费/试用源，不该因为它抖动就搞垮整轮抓取。
    """
    import os
    user = os.environ.get("DXFEED_NEWS_USER")
    password = os.environ.get("DXFEED_NEWS_PASS")
    if not user or not password:
        logger.info("dxFeed News: 未配置 DXFEED_NEWS_USER/DXFEED_NEWS_PASS，跳过")
        return []

    seen_ids = set()
    items = []
    for batch in _batches(DXFEED_SYMBOLS, _SYMBOL_BATCH_SIZE):
        try:
            resp = requests.get(
                DXFEED_NEWS_BASE,
                params={"symbol": ",".join(batch), "limit": MAX_ITEMS_PER_QUERY, "body": "true"},
                auth=(user, password),
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.warning(f"dxFeed News 批次 {batch} 拉取失败，跳过该批：{e}")
            continue

        for n in payload.get("news", []):
            nid = n.get("id")
            if nid in seen_ids:   # 多个 symbol 可能命中同一条新闻（如大盘 ETF 连带指数）
                continue
            title = (n.get("title") or "").strip()
            if not title:
                continue
            seen_ids.add(nid)
            # 记录这条新闻挂了哪些我们关注的 symbol —— 优先级判定要靠它区分
            # 大盘与个股（见 crawler/staging.py 的 SOURCE_PRIORITY）。用交集而不是
            # 原样存 n["symbols"]：一条新闻可能挂几十个无关 ticker（实测有 48 个的），
            # 只留我们订阅的那些，字段短且判定语义清晰。
            hit = [s for s in (n.get("symbols") or []) if s in set(DXFEED_SYMBOLS)]
            items.append({
                "source": f"dxFeed-{n.get('source') or 'MTNewswires'}",
                "title": title,
                "url": f"{DXFEED_NEWS_BASE}?id={nid}",
                "summary": (n.get("body") or "").strip(),
                "published_at": n.get("time", ""),
                "matched_symbols": ",".join(hit[:12]),
                "lang": "en",
                # 机构级实时新闻源，authority 对齐 crawler/web_search.py 的 _TIER_5
                # （CNBC/Reuters/Bloomberg 那一档）——MT Newswires 是同一量级的
                # 机构新闻通讯社，不是二线聚合站。
                "authority": 5,
                "type": "dxfeed",
            })

    logger.info(f"dxFeed News: {len(items)} items ({len(DXFEED_SYMBOLS)} symbols, "
               f"{(len(DXFEED_SYMBOLS) + _SYMBOL_BATCH_SIZE - 1)//_SYMBOL_BATCH_SIZE} 批)")
    return items
