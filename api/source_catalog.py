"""信源目录 —— 把散在三处的信源信息合成一张可查询的表。

2026-07-27 Lawrence："加一个信源统计小 tab，可以查询所有信息源。分类、分级、
事件数量、网址之类的。可简单筛选。"

三处来源，缺一不可：
  1. crawler/sources.py       —— 接入方式、语言、人工权威分(1–5)、URL / KOL 账号
  2. crawler/verification.py  —— 校验用的机构分层（official / top_media / …）与权重
  3. news_events.source_names —— 这个信源到底真的产出了多少事件

只读注册表 + 一次聚合查询，不额外调用任何外部服务，成本为零。
注册表里配了但一条都没产出的信源也会列出来（事件数 0）——那恰恰是需要看见的：
配了没用上的源，要么是抓取坏了，要么是该下掉。
"""
import logging
import os
import sys
from functools import wraps

from flask import Blueprint, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector

from crawler import sources as S
from crawler import verification as V

logger = logging.getLogger(__name__)
source_catalog_bp = Blueprint("source_catalog", __name__)

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


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "") or request.args.get("token", "")
        if key not in VALID_API_KEYS:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def _conn():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "crypto_news"),
        charset="utf8mb4",
    )


# 接入方式：这是 tab01 流程图左栏「数据源与接入方式」的同一套口径，
# 前端筛选器直接用它做分类，两处不能各说各话。
CHANNEL_RSS_DIRECT = "RSS 直连"
CHANNEL_RSSHUB     = "自建 RSSHub"
CHANNEL_HTML       = "HTML 解析"
CHANNEL_X_KOL      = "X KOL 时间线"
CHANNEL_X_SEARCH   = "X 全网搜索"
CHANNEL_SEARCH     = "搜索引擎"


def _registry() -> list[dict]:
    """把 sources.py 里各张表摊平成统一结构。"""
    rows: list[dict] = []

    def add_feeds(table, channel):
        for url, name, lang, authority in getattr(S, table, []):
            rows.append({"name": name, "channel": channel, "lang": lang,
                         "authority": authority, "url": url})

    for t in ("RSS_SOURCES_P0", "RSS_SOURCES_P1", "RSS_SOURCES_P2", "RSS_SOURCES_MACRO"):
        add_feeds(t, CHANNEL_RSS_DIRECT)
    add_feeds("RSS_SOURCES_RSSHUB", CHANNEL_RSSHUB)

    for h in getattr(S, "HTML_SOURCES", []):
        rows.append({"name": h["name"], "channel": CHANNEL_HTML, "lang": h.get("lang", ""),
                     "authority": h.get("authority", 3), "url": h.get("url", "")})

    for kol in getattr(S, "CRYPTO_KOLS", []):
        # (username, authority, kind)
        username, authority = kol[0], (kol[1] if len(kol) > 1 else 3)
        kind = kol[2] if len(kol) > 2 else ""
        rows.append({"name": "@" + username, "channel": CHANNEL_X_KOL, "lang": "",
                     "authority": authority, "url": "https://x.com/" + username,
                     "note": kind})

    n_sq = len(getattr(S, "BINANCE_SQUARE_QUERIES", []))
    if n_sq:
        rows.append({"name": "币安广场检索", "channel": CHANNEL_SEARCH, "lang": "en",
                     "authority": 2, "url": "https://www.binance.com/en/square",
                     "note": f"{n_sq} 条 query"})
    n_xs = len(getattr(S, "X_SEARCH_QUERIES", []))
    if n_xs:
        rows.append({"name": "X 全网搜索", "channel": CHANNEL_X_SEARCH, "lang": "",
                     "authority": 2, "url": "https://x.com/search",
                     "note": f"{n_xs} 条 query"})
    return rows


def _tier_of(name: str, url: str = "", stype: str = "rss") -> tuple[str, str, float]:
    """机构 id / 分层 / 权重。

    直接复用 verification.resolve_source —— 它就是真实性校验实际用的那套口径。
    这里另起一套判断只会和线上打分对不上，那正是最容易骗到人的一类不一致。
    """
    try:
        return V.resolve_source({"source_name": name, "source": name, "url": url, "type": stype})
    except Exception as e:
        logger.debug("resolve_source(%s) 失败: %s", name, e)
        tier = getattr(V, "TIER_UNKNOWN", "unknown")
        return "unknown", tier, getattr(V, "TIER_WEIGHT", {}).get(tier, 0.0)


@source_catalog_bp.route("/api/source-catalog", methods=["GET"])
@require_api_key
def source_catalog():
    counts: dict[str, int] = {}
    try:
        conn = _conn()
        cur = conn.cursor()
        # source_names 是 JSON 数组列，这里按行展开统计。数据量千级，全表扫无压力。
        cur.execute("SELECT source_names FROM news_events WHERE source_names IS NOT NULL")
        import json as _json
        for (raw,) in cur.fetchall():
            try:
                for nm in (_json.loads(raw) if isinstance(raw, str) else (raw or [])):
                    counts[str(nm)] = counts.get(str(nm), 0) + 1
            except Exception:
                continue
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("source-catalog 统计事件数失败（目录仍可返回）: %s", e)

    rows = []
    for r in _registry():
        stype = "x" if r["channel"].startswith("X ") else "rss"
        inst, tier, weight = _tier_of(r["name"], r.get("url", ""), stype)
        rows.append({**r,
                     "institution": inst,
                     "tier": tier,
                     "tier_weight": round(weight, 2),
                     "event_count": counts.get(r["name"], 0)})

    # 库里出现过、但注册表里没有的名字（web_search / x_search 捞回来的长尾）
    known = {r["name"] for r in rows}
    for nm, c in counts.items():
        if nm in known:
            continue
        inst, tier, weight = _tier_of(nm, "", "web_search")
        rows.append({"name": nm, "channel": CHANNEL_SEARCH, "lang": "", "authority": None,
                     "url": "", "institution": inst, "tier": tier,
                     "tier_weight": round(weight, 2),
                     "event_count": c, "note": "搜索召回长尾"})

    rows.sort(key=lambda x: (-x["event_count"], x["name"]))
    return jsonify({
        "data": rows,
        "meta": {
            "total": len(rows),
            "registered": len(known),
            "channels": [CHANNEL_RSS_DIRECT, CHANNEL_RSSHUB, CHANNEL_HTML,
                         CHANNEL_X_KOL, CHANNEL_X_SEARCH, CHANNEL_SEARCH],
            "tiers": list(getattr(V, "TIER_WEIGHT", {}).keys()),
        },
    })
