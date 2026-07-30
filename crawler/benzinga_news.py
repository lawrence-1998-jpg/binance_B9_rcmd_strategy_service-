"""
Benzinga 实时新闻（经 Massive 平台）—— crawler/benzinga_news.py（2026-07-30 新增）

背景：Lawrence 转发了公司新采购的 Massive 平台 key（合作方 Ben.Y），文档见
https://massive.com/docs/rest/partners/benzinga/news —— `GET
https://api.massive.com/benzinga/v2/news`，`apiKey` 查询参数鉴权，直连
Benzinga 自己的编辑新闻流（不是搜索聚合），带完整正文、真实 tickers、
可信的 published/last_updated 时间戳。实测（2026-07-30）响应质量确认：
HTML 正文、ticker 列表、真实发布时间戳，`published.gt` 增量过滤参数验证有效。

## 为什么用「回溯窗口」而不是持久化水位线（watermark）

这条源接的是 `stage_fetch_priority.py`（30 分钟一次的高频抓取，只做抓取+
存档，不进 LLM）。跟 RSS 源的处理方式保持一致：每次都拉一个比抓取间隔更宽
的时间窗（这里是 90 分钟，3 倍于 30 分钟节奏，留出 cron 抖动/单次失败的
安全余量），重复内容靠 `crawler/staging.py` 的 url_hash 去重挡掉——不需要
额外维护一张水位线状态表，和 CNBC/MarketWatch 等 RSS 源"抓一个比节奏更宽
的窗口 + 去重"是同一套简单方案，没有为这条源单独发明新机制。

## authority 定 5 分（2026-07-30 两次上调：先 3→4，后 Lawrence 看了 24h
## 覆盖率核实结果——美股硬新闻命中率高、Fed决议实测比CNBC快2分钟——说
## "本来我们就是要美股为主"，定 5，对齐 CNBC/Reuters/Bloomberg 档）

初版按 `crawler/web_search.py` 域名分级表（`_TIER_3`）给了 3 分，理由是
"直连 API 换来的是时间戳可信+正文完整，不是编辑质量的跃升"。用真实 24
小时数据核实覆盖率后（见 docs/WORKLOG.md 同名章节），美股相关硬新闻头条
命中率高且实测更快，这个判断被证据推翻——不是"编辑质量没变、只是管道
升级"，是"这条源在我们最看重的美股维度上表现确实够格"。5 分与
`crawler/dxfeed_news.py` 的机构级档位并列，两者现在是同一档、不同信源
的关系，不是谁对齐谁。

## 为什么在 staging.py 优先级里给它 P0（权威大盘媒体档）

authority 不变不代表处理优先级不变——Lawrence 明确要"这几类财经数据源，
实时性要更强一点"，而这条源恰好是**发布即结构化**的原生 API（无需等
RSS 抓取窗口），最适合承接这个诉求。优先级（多快处理）和权威度（打几分）
在这个项目里是两条独立轴线，dxFeed 大盘 symbol 同样是"P0/P1 优先级 + 不
对齐 5 分权威度"的先例。
"""
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

MASSIVE_API_BASE = "https://api.massive.com/benzinga/v2/news"
REQUEST_TIMEOUT = 20

# 回溯窗口：配合 30 分钟一次的 stage_fetch_priority cron，留 3 倍安全余量。
LOOKBACK_MINUTES = int(os.environ.get("B9_BENZINGA_LOOKBACK_MIN", "90"))
# 实测过去 90 分钟（美股非交易时段）仅个位数条目，交易时段量级会明显更高；
# 300 给出充足余量，命中即说明窗口内被截断，需要调小窗口或调大上限。
MAX_ITEMS_PER_CALL = int(os.environ.get("B9_BENZINGA_LIMIT", "300"))

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _map_result(n: dict) -> dict | None:
    """把 Massive 原始响应行映射成 news_events 兼容的 item。标题为空则丢弃。"""
    title = (n.get("title") or "").strip()
    if not title:
        return None
    body = (n.get("body") or n.get("teaser") or "").strip()
    body = _HTML_TAG_RE.sub(" ", body).strip()  # 正文是带标签的富文本，去标签留纯文本供 LLM 判读
    tickers = n.get("tickers") or []
    return {
        "source": "Benzinga",
        "title": title,
        "url": n.get("url", ""),
        "summary": body,
        "published_at": n.get("published", ""),
        "matched_symbols": ",".join(tickers[:12]),
        "lang": "en",
        "authority": 4,
        "type": "benzinga",
    }


def fetch_benzinga_news() -> list[dict]:
    """返回 news_events 兼容的 item 列表。凭据缺失或请求失败时直接跳过、不抛异常
    —— 与 dxFeed 一致：新源自身抖动不该搞垮整轮抓取。"""
    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        logger.info("Benzinga News: 未配置 MASSIVE_API_KEY，跳过")
        return []

    since = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        resp = requests.get(
            MASSIVE_API_BASE,
            params={
                "published.gt": since_str,
                "limit": MAX_ITEMS_PER_CALL,
                "sort": "published.desc",
                "apiKey": api_key,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.warning(f"Benzinga News 拉取失败，跳过本轮：{e}")
        return []

    results = payload.get("results", [])
    if len(results) >= MAX_ITEMS_PER_CALL:
        logger.warning(
            f"Benzinga News: 命中单次上限 {MAX_ITEMS_PER_CALL}，"
            f"回溯窗口 {LOOKBACK_MINUTES} 分钟内可能有截断，考虑调小窗口或调大上限")

    items = [it for n in results if (it := _map_result(n))]
    logger.info(f"Benzinga News: {len(items)} items (回溯 {LOOKBACK_MINUTES} 分钟)")
    return items


def backfill_benzinga_news(since_iso: str, page_limit: int = 500, max_pages: int = 50) -> list[dict]:
    """一次性历史回填：从 `since_iso`（含）到现在，翻页拉全部结果。

    只用于 scripts/backfill_benzinga.py 这类一次性操作，不进生产 30 分钟
    循环——生产路径固定用短回溯窗 + 去重（见模块顶部说明），翻页机制只在
    需要补历史存量时才用得上。`next_url` 已经带好下一页的 cursor，直接接
    apiKey 参数即可继续翻页。
    """
    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        logger.info("Benzinga backfill: 未配置 MASSIVE_API_KEY，跳过")
        return []

    items: list[dict] = []
    url = (f"{MASSIVE_API_BASE}?published.gt={since_iso}&limit={page_limit}"
           f"&sort=published.asc&apiKey={api_key}")
    for page in range(max_pages):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.warning(f"Benzinga backfill 第 {page+1} 页拉取失败，停止翻页：{e}")
            break

        results = payload.get("results", [])
        items.extend(it for n in results if (it := _map_result(n)))
        next_url = payload.get("next_url")
        if not next_url or not results:
            break
        url = f"{next_url}&apiKey={api_key}"

    logger.info(f"Benzinga backfill: {len(items)} items since {since_iso}")
    return items
