"""
MySQL 读写层。

除了常规的写库，这里还实现去重管线的最后一层：

    DC-4  跨轮归并 —— 写库前把本轮事件与库中近期事件比对，命中则并入既有行

这一层是修复 149 条冗余的关键。cron 每 4 小时跑一轮，而各信源的抓取窗口远大于
4 小时（RSS 普遍返回最近 30 条），所以相邻两轮必然重复抓到同一批新闻。旧实现的
aggregate_events 只在**单轮内**去重，跨轮完全不设防，同一事件每轮都以新 id 插入
一行。轮内去重做得再好也堵不住这个口子。
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import mysql.connector
import numpy as np

from . import scoring

from .dedup import (
    COSINE_THRESHOLD, TIME_WINDOW_HOURS,
    blob_to_embedding, embedding_to_blob, hours_between,
)
from .timeutil import now_local, to_mysql_datetime as _to_mysql_datetime

logger = logging.getLogger(__name__)

# 跨轮比对的回溯窗口。取 72h 而非 48h，比 DC-3 的时间窗略宽一些留余量：
# 事件时间本身可能有偏差，窗口卡太紧会让边界上的重复漏过去。
LOOKBACK_HOURS = 72


def get_mysql_conn():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "crypto_news"),
        charset="utf8mb4",
    )


# 实现搬到 crawler/timeutil.py（那里统一做 UTC+8 换算），这里保留同名再导出：
# 项目里十几处 `from crawler.storage import to_mysql_datetime` 不用改。
to_mysql_datetime = _to_mysql_datetime


# ── 社交互动信号（供 H 因子）────────────────────────────────────────

def attach_social_metrics(events: list[dict], conn) -> None:
    """给每个事件挂上关联 X 推文的互动总量（赞 + 转 + 评 + 引）。

    关联路径是事件 sources[].x_tweet_id → x_raw_posts.tweet_id。同一事件可能由多条
    KOL 推文共同支撑，互动量累加。非 X 来源的事件互动量为 0，这是真实情况——
    它们确实没有社交信号，H 因子里由信源数那 0.4 权重体现热度。
    """
    tweet_ids = {
        src.get("x_tweet_id")
        for event in events
        for src in event.get("sources", [])
        if src.get("x_tweet_id")
    }
    if not tweet_ids:
        for event in events:
            event["social_interactions"] = 0
        return

    placeholders = ",".join(["%s"] * len(tweet_ids))
    cursor = conn.cursor()
    cursor.execute(
        f"""SELECT tweet_id,
                   like_count + retweet_count + reply_count + quote_count
            FROM x_raw_posts WHERE tweet_id IN ({placeholders})""",
        tuple(tweet_ids),
    )
    metrics = dict(cursor.fetchall())
    cursor.close()

    for event in events:
        event["social_interactions"] = sum(
            int(metrics.get(src.get("x_tweet_id"), 0) or 0)
            for src in event.get("sources", [])
            if src.get("x_tweet_id")
        )

    hit = sum(1 for e in events if e.get("social_interactions", 0) > 0)
    logger.info(f"Social metrics: {hit}/{len(events)} events carry X interactions")


# ── DC-4 跨轮归并 ────────────────────────────────────────────────────

def load_recent_events(conn, hours: int = LOOKBACK_HOURS) -> list[dict]:
    """拉取近 N 小时入库的事件，作为跨轮归并的比对基准。"""
    since = (now_local() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        # title_zh/title_en/description_short_zh 是 2026-07-29 补读的：跨轮归并
        # 命中既有行时，写库**刻意不更新正文**（防前端卡片文案抖动），但打分是
        # 用**新一轮的正文**算的——于是 punch 的"数值幅度"子项来自一份最终不会
        # 入库的文本，和行里真正存着的正文对不上。实测 638 条有幅度值的事件里
        # 63 条错位，且 100% 都是归并过的行，症状很刺眼：「KOSPI跌超8%触发熔断」
        # 显示"幅度 80%"、「日经225跌4% 铠侠跌18%」显示"幅度 2%"。
        # 把既有正文一并读出来，在 merge_with_existing 里回填给事件，让打分
        # 和入库看到的是同一份文本。
        """SELECT id, event_fingerprint, embedding, source_names, sources,
                  source_count, merged_sources_count, time_event,
                  title_zh, title_en, description_short_zh
           FROM news_events WHERE time_get_data >= %s""",
        (since,),
    )
    rows = cursor.fetchall()
    cursor.close()

    def _load_json(raw, fallback):
        try:
            return json.loads(raw) if raw else fallback
        except (json.JSONDecodeError, TypeError):
            return fallback

    recent = []
    for row in rows:
        (event_id, fingerprint, blob, source_names, sources,
         source_count, merged, time_event,
         title_zh, title_en, desc_short_zh) = row
        recent.append({
            "id": event_id,
            "fingerprint": fingerprint or "",
            "embedding": blob_to_embedding(blob),
            "source_names": _load_json(source_names, []),
            # sources 是带 url/authority 的完整明细。必须一并读出来，否则跨轮归并
            # 时新一轮只会写入自己这批 sources，把历史轮次的明细覆盖掉——而
            # source_names 走的是并集，两者会长期不同步（实测 508 行里有 59 行
            # 长度对不上，下游若只读 sources 会把多源事件误判成孤证）。
            "sources": _load_json(sources, []),
            "source_count": source_count or 1,
            "merged_sources_count": merged or 1,
            "published_at": time_event.isoformat() if time_event else None,
            # 既有正文，供 merge_with_existing 回填（见上面 SELECT 的说明）
            "title_zh": title_zh,
            "title_en": title_en,
            "description_short_zh": desc_short_zh,
        })
    logger.info(f"Cross-run merge: loaded {len(recent)} events from last {hours}h")
    return recent


def _match_by_embedding(events: list[dict], recent: list[dict]) -> dict[int, dict]:
    """对所有事件一次性算出语义最近的库中既有行，返回 {事件下标: 既有行}。

    向量化成一次矩阵乘法：逐条循环比对是 O(新事件数 × 近期事件数) 次 Python 层
    调用，实测量级下（约 500 × 850）会明显拖慢每轮 pipeline。
    """
    candidates = [r for r in recent if r["embedding"] is not None]
    indexed = [(i, e) for i, e in enumerate(events) if e.get("embedding") is not None]
    if not candidates or not indexed:
        return {}

    def _normalize(matrix):
        return matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-9)

    new_matrix = _normalize(np.stack([e["embedding"] for _, e in indexed]))
    old_matrix = _normalize(np.stack([c["embedding"] for c in candidates]))
    sim = new_matrix @ old_matrix.T

    matches = {}
    best_cols = sim.argmax(axis=1)
    for row, (event_index, event) in enumerate(indexed):
        col = int(best_cols[row])
        if float(sim[row][col]) < COSINE_THRESHOLD:
            continue
        # 相似度达标还要过时间窗，避免"同主体不同时间的两件事"被并到一起
        if hours_between(event.get("published_at"),
                         candidates[col]["published_at"]) > TIME_WINDOW_HOURS:
            continue
        matches[event_index] = candidates[col]
    return matches


def merge_with_existing(events: list[dict], recent: list[dict]) -> tuple[list[dict], int]:
    """把本轮事件与库中近期事件对齐，返回 (待写入事件列表, 命中条数)。

    命中既有行的事件会复用该行的 id，写库时自然走 ON DUPLICATE KEY UPDATE 分支，
    变成一次更新而非插入重复行——这是堵住跨轮重复的关键。

    若本轮有多个事件命中**同一**既有行，它们会被折叠成一条再写。否则两次写入会
    以同一个 id 先后覆盖，后写的把先写的信源名单冲掉。
    """
    by_fingerprint = {r["fingerprint"]: r for r in recent if r["fingerprint"]}
    embedding_matches = _match_by_embedding(events, recent)

    # 既有行 id → 已折叠到该行的事件，保证一个既有 id 只产出一次写入
    claimed: dict[str, dict] = {}
    output, merged_count = [], 0

    for index, event in enumerate(events):
        fingerprint = event.get("event_fingerprint", "")
        existing = by_fingerprint.get(fingerprint) or embedding_matches.get(index)

        if existing is None:
            output.append(event)
            continue

        merged_count += 1
        target = claimed.get(existing["id"])
        if target is None:
            # 首个命中者：继承既有行的 id 与信源
            event["id"] = existing["id"]
            # 同时继承既有行的**正文**。写库那条 UPSERT 刻意不更新标题/正文
            # （防前端卡片文案抖动），所以入库后留下的是既有行这一份；如果这里
            # 不回填，下游 score_events 会用本轮新正文去算 punch 的"数值幅度"
            # 子项，算出来的幅度对应一份最终不会入库的文本。实测这正是
            # 「KOSPI跌超8%触发熔断」显示"幅度 80%"、「日经225跌4% 铠侠跌18%」
            # 显示"幅度 2%"的原因（638 条里错 63 条，100% 都是归并过的行）。
            # 回填之后，打分看到的正文和最终入库的正文是同一份。
            for _text_field in ("title_zh", "title_en", "description_short_zh"):
                if existing.get(_text_field):
                    event[_text_field] = existing[_text_field]
            event["source_names"] = sorted(set(event.get("source_names", [])) |
                                           set(existing["source_names"]))
            event["merged_sources_count"] = (existing["merged_sources_count"] +
                                             event.get("merged_sources_count", 1))
            # sources 明细同样取并集，和 source_names 保持同步
            event["sources"] = _merge_sources(event.get("sources", []),
                                              existing.get("sources", []))
            _refresh_source_count(event, existing["source_count"])
            claimed[existing["id"]] = event
            output.append(event)
        else:
            # 后续命中者：并入首个，不再单独写一行
            target["source_names"] = sorted(set(target["source_names"]) |
                                            set(event.get("source_names", [])))
            target["sources"] = _merge_sources(target.get("sources", []),
                                               event.get("sources", []))
            target["merged_sources_count"] += event.get("merged_sources_count", 1)
            _refresh_source_count(target, existing["source_count"])

    folded = len(events) - len(output)
    logger.info(
        f"Cross-run merge: {merged_count}/{len(events)} events matched existing rows"
        + (f", {folded} folded into siblings" if folded else "")
    )
    return output, merged_count


def _merge_sources(*source_lists) -> list[dict]:
    """按 url 去重合并多份 sources 明细，保持稳定顺序。

    跨轮归并时新旧两轮各有一份 sources，必须并集而非覆盖——否则 sources 只留
    最后一轮的明细，而 source_names 是并集，两个字段会长期不一致，下游读 sources
    判断信源数就会把多源事件误判成孤证。
    """
    merged, seen = [], set()
    for sources in source_lists:
        for src in sources or []:
            url = (src or {}).get("url", "")
            key = url or json.dumps(src, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            merged.append(src)
    return merged


def _refresh_source_count(event: dict, existing_count: int) -> None:
    """信源名单变动后同步 source_count / is_verified。

    注意这里对 existing_count 取 max 是为了不让已确认的多源事件因某轮抓取
    不全而掉档；代价是若历史值本身偏高（早期 bug 留下的），会一直保留。
    verification.py 另算了一个 independent_source_count（按机构去重），
    需要精确机构数时以那个为准。
    """
    event["source_count"] = max(
        len({name.split("/")[0] for name in event["source_names"]}), existing_count
    )
    event["is_verified"] = event["source_count"] >= 2


# ── 写库 ─────────────────────────────────────────────────────────────

_INSERT_EVENT_SQL = """
INSERT INTO news_events (
    id, title_en, title_zh, date, time_event, time_get_data,
    description_short_en, description_short_zh,
    description_long_en, description_long_zh,
    sectors, coins, news_type, market_scope, breadth_level, price_move, event_tier,
    score_market_impact, score_breadth, score_punch, punch_magnitude_pct,
    score_timeliness, score_hotness,
    score_authority, score_quality, importance_score, scoring_version,
    credibility_score, is_rumor, rumor_reason,
    sources, source_names, source_count, is_verified, language_origin,
    cluster_id, merged_sources_count,
    event_subject, event_action, event_fingerprint, embedding, social_interactions
) VALUES (
    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,%s,%s,%s,%s
)
ON DUPLICATE KEY UPDATE
    -- 标题与正文刻意不更新：同一事件跨轮重复抓到时，LLM 每次改写措辞略有不同，
    -- 覆盖会让前端已展示的卡片文案无故抖动。首次入库的版本已是簇内权威最高者。
    sources              = VALUES(sources),
    source_names         = VALUES(source_names),
    source_count         = VALUES(source_count),
    merged_sources_count = VALUES(merged_sources_count),
    is_verified          = VALUES(is_verified),
    social_interactions  = GREATEST(social_interactions, VALUES(social_interactions)),
    -- 随时间/热度变化的分数需要刷新
    score_timeliness     = VALUES(score_timeliness),
    score_hotness        = VALUES(score_hotness),
    -- 冲击力要刷新：跨轮归并会合并 sources，权威共振子项随之变化
    score_punch          = VALUES(score_punch),
    -- 广度必须**每次都刷新**（VALUES，不是 COALESCE）。这里改过一次又改回来，
    -- 记录下两次都踩的坑，防止以后再犯同一对错误里的任何一个：
    --
    -- 第一版（migration 014 刚上线时）：这三列压根不在 UPDATE 子句里，MySQL
    -- 对没提到的列什么都不做。于是 014 之前入库、breadth 天生 NULL 的 145 行
    -- 被跨轮归并碰过之后也永远补不上——一个 0.16 权重的因子被 compute_breadth
    -- 的兜底 BREADTH_DEFAULT=0.15（五档最低）静默顶替，足够把跨市场级事件
    -- 挤出首屏。当时的修法是加上这三列，但改成了 COALESCE（只填空不覆盖）。
    --
    -- 第二版（几小时后，同一天）：COALESCE 引入了一个更隐蔽的不一致——
    -- importance_score 依然是每次都刷新（VALUES），用的是**这一轮** LLM
    -- 重新分类出来的新 B；但 score_breadth 本身却被 COALESCE 成**老值**。
    -- 于是 importance_score 用一个被丢弃的输入算出来，跟它自己同一行里的
    -- score_breadth 对不上——这正是 scripts/qa_suite.py 新增的"打分口径一致性"
    -- 断言要抓的那类问题，而这个断言部署后的第一个生产轮次自己就撞上了
    -- （121 行）。COALESCE 的动机是"不覆盖已展示内容"，但那个约定只对标题/
    -- 正文这类主观措辞成立——数值型因子如果真的换了分类（LLM 判断广度变了），
    -- 分数就应该跟着变，跟 score_punch/score_timeliness/score_hotness 一个道理。
    -- 一次性回填已经把老的 145 行缺口填平（scoring_version=2 覆盖全表），
    -- COALESCE 存在的理由不再成立，所以退回 VALUES。
    breadth_level        = VALUES(breadth_level),
    price_move           = VALUES(price_move),
    score_breadth        = VALUES(score_breadth),
    punch_magnitude_pct  = VALUES(punch_magnitude_pct),
    -- score_market_impact 和 score_quality 直到刚才都**没在这个 UPDATE 子句里
    -- 出现过**——同一天第三次撞上同一类问题：QA 的打分口径一致性断言部署后，
    -- 手动触发的下一轮生产 pipeline 一跑完就抓到 19 行不吻合。跨轮归并命中的
    -- 事件会带着新一轮算出的 M/A/Q 传给 importance_score（VALUES 立刻刷新），
    -- 但 score_market_impact/score_quality 这两列因为压根不在子句里，MySQL
    -- 对没提到的列什么都不做，于是停留在**首次入库**那一刻的旧值，跟同一行
    -- 里刚刷新的 importance_score 对不上。
    --
    -- 结论：这类 bug 靠"每次出现改一列"堵不完——必须是一条结构性规则：
    -- **任何进 compute_macro_score 公式的列，都必须在这里用 VALUES 刷新，
    -- 没有例外、不做个案判断**。下面把 M/A/Q 补全，凑齐全部七个基础因子列
    -- （B/T/I/H 已经在上面），以后新增因子列时对照这条规则检查，别再漏。
    score_market_impact  = VALUES(score_market_impact),
    score_authority      = VALUES(score_authority),
    score_quality        = VALUES(score_quality),
    importance_score     = VALUES(importance_score),
    -- 2026-07-29 新增（见 migration 015）。这行必须跟 importance_score 一起刷，
    -- 否则会重演同一个 bug 的变体：分刷新了，版本号没刷新，"这行是哪个版本算的"
    -- 又变回一次反算猜测，而不是一次 WHERE 查询。
    scoring_version      = VALUES(scoring_version),
    updated_at           = CURRENT_TIMESTAMP
"""


def write_events(events: list[dict], conn) -> int:
    """批量写入/更新事件，返回成功条数。"""
    if not events:
        return 0

    cursor = conn.cursor()
    now_str = now_local().strftime("%Y-%m-%d %H:%M:%S")
    written = 0

    for event in events:
        scores = event.get("scores", {})
        date_str = (event.get("published_at") or "")[:10] or now_str[:10]
        try:
            cursor.execute(_INSERT_EVENT_SQL, (
                event["id"],
                event.get("title_en", ""),
                event.get("title_zh", ""),
                date_str,
                to_mysql_datetime(event.get("published_at")),
                now_str,
                event.get("description_short_en", ""),
                event.get("description_short_zh", ""),
                event.get("description_long_en", ""),
                event.get("description_long_zh", ""),
                json.dumps(event.get("sectors", []), ensure_ascii=False),
                json.dumps(event.get("coins", []), ensure_ascii=False),
                event.get("news_type", "other"),
                event.get("market_scope", "crypto"),
                event.get("breadth_level"),
                # 语义判断整体存 JSON（见 migration 021 的说明：三个字段同生共死）
                json.dumps(event["price_move"], ensure_ascii=False)
                if isinstance(event.get("price_move"), dict) else None,
                event.get("event_tier", "C"),
                scores.get("score_market_impact", 0.0),
                scores.get("score_breadth", 0.0),
                scores.get("score_punch", 0.0),
                scores.get("punch_magnitude_pct"),
                scores.get("score_timeliness", 0.0),
                scores.get("score_hotness", 0.0),
                scores.get("score_authority", 0.0),
                scores.get("score_quality", 0.0),
                scores.get("importance_score", 0.0),
                scores.get("scoring_version", scoring.SCORING_VERSION),
                event.get("credibility_score", 0.5),
                bool(event.get("is_rumor", False)),
                event.get("rumor_reason", ""),
                json.dumps(event.get("sources", []), ensure_ascii=False),
                json.dumps(event.get("source_names", []), ensure_ascii=False),
                event.get("source_count", 1),
                bool(event.get("is_verified", False)),
                event.get("lang", "en"),
                event.get("cluster_id", "") or event["id"],
                event.get("merged_sources_count", 1),
                event.get("event_subject", "")[:128],
                event.get("event_action", "")[:128],
                event.get("event_fingerprint", ""),
                embedding_to_blob(event.get("embedding")),
                int(event.get("social_interactions", 0) or 0),
            ))
            written += 1
        except Exception as e:
            logger.warning(f"Write failed [{event.get('title_en', '')[:60]}]: {e}")

    conn.commit()
    cursor.close()
    logger.info(f"MySQL: wrote/updated {written}/{len(events)} events")
    return written


_UPDATE_X_POST_LINK_SQL = "UPDATE x_raw_posts SET news_event_id = %s WHERE tweet_id = %s"


def persist_x_post_links(events: list[dict], conn) -> int:
    """把事件最终 id 写回它引用的 x_raw_posts 行，建立 news_event_id 关联。

    必须在 write_events 之后调用（此时跨轮归并已把事件 id 定型为既有行 id 或新
    id）。此前 write_x_posts 只落推文本身，从不写这一列，导致 /api/news/<id>/
    x-sources 永远查不到数据——关联信息其实一直都在 event['sources'] 的
    x_tweet_id 里，只是没回写。按 tweet_id 做 UPDATE 天然幂等，重复调用安全。
    """
    if not events:
        return 0
    cursor = conn.cursor()
    written = 0
    for event in events:
        tweet_ids = {
            src.get("x_tweet_id")
            for src in event.get("sources", [])
            if src.get("x_tweet_id")
        }
        for tweet_id in tweet_ids:
            try:
                cursor.execute(_UPDATE_X_POST_LINK_SQL, (event["id"], tweet_id))
                written += cursor.rowcount
            except Exception as e:
                logger.warning(f"x_raw_posts link write failed [{tweet_id}]: {e}")
    conn.commit()
    cursor.close()
    logger.info(f"MySQL: news_event_id linked for {written} x_raw_posts rows")
    return written


_INSERT_X_POST_SQL = """
INSERT INTO x_raw_posts (
    tweet_id, kol_username, kol_display_name, kol_followers_count,
    kol_verified, kol_profile_url, tweet_title, tweet_body, tweet_url,
    tweet_lang, like_count, retweet_count, reply_count, quote_count,
    impression_count, published_at
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON DUPLICATE KEY UPDATE
    like_count=VALUES(like_count), retweet_count=VALUES(retweet_count),
    reply_count=VALUES(reply_count), quote_count=VALUES(quote_count),
    impression_count=VALUES(impression_count), fetched_at=CURRENT_TIMESTAMP
"""


def write_x_posts(posts: list[dict], conn) -> int:
    """X 原始推文落表。互动量会被后续 attach_social_metrics 读回来喂给 H 因子，
    所以这一步必须在事件写库之前完成。"""
    if not posts:
        return 0

    cursor = conn.cursor()
    written = 0
    for post in posts:
        try:
            cursor.execute(_INSERT_X_POST_SQL, (
                post["tweet_id"], post["kol_username"],
                post.get("kol_display_name", ""), post.get("kol_followers_count", 0),
                bool(post.get("kol_verified", False)), post.get("kol_profile_url", ""),
                post.get("tweet_title", ""), post.get("tweet_body", ""),
                post.get("tweet_url", ""), post.get("tweet_lang", "en"),
                post.get("like_count", 0), post.get("retweet_count", 0),
                post.get("reply_count", 0), post.get("quote_count", 0),
                post.get("impression_count", 0),
                to_mysql_datetime(post.get("published_at")),
            ))
            written += 1
        except Exception as e:
            logger.warning(f"x_raw_posts write failed [{post.get('tweet_id')}]: {e}")

    conn.commit()
    cursor.close()
    logger.info(f"MySQL: wrote {written} x_raw_posts")
    return written


def record_run(conn, stats: dict, duration: float,
               status: str = "success", error: str | None = None,
               usage: dict | None = None) -> None:
    """记录本轮 pipeline 水位，供「零丢失铁律」核查；`usage` 是
    UsageTracker.snapshot() 的输出，供 scripts/usage_monitor.py 做成本追踪。

    `stats["stage_timings"]`（若有）是 pipeline.run_pipeline() 用 lap() 记的
    各阶段耗时（秒），存成 JSON——2026-07-26 加的，此前"pipeline 为什么这么久"
    只能翻日志按时间戳手动倒推，现在一条 SQL 就能看分解。
    """
    usage = usage or {}
    stage_timings = json.dumps(stats.get("stage_timings") or {}, ensure_ascii=False)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO pipeline_runs
               (raw_count, deduped_count, enriched_count, events_count,
                rumors_count, duration_seconds, status, error_msg,
                llm_input_tokens, llm_output_tokens, llm_cached_tokens,
                embedding_tokens, estimated_cost_usd, stage_timings)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (stats.get("raw", 0), stats.get("deduped", 0), stats.get("enriched", 0),
             stats.get("events", 0), stats.get("rumors", 0), duration, status, error,
             usage.get("chat_input_tokens", 0), usage.get("chat_output_tokens", 0),
             usage.get("chat_cached_tokens", 0), usage.get("embedding_tokens", 0),
             usage.get("estimated_cost_usd", 0.0), stage_timings),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"pipeline_runs write failed: {e}")
    finally:
        cursor.close()


# ── 本地 Claude 预处理缓存（enrich bridge）───────────────────────────
#
# 背景（2026-07-26）：Lawrence 的 Claude Max 订阅有大量闲置额度，而 VM 上的
# OpenAI credit 在真金白银地烧。于是把最贵的 LLM 结构化环节做成"可预计算"：
# 他的 Mac 上有个 worker（scripts/local_enrich_worker.py）闲时拉取 staging
# 里还没处理的条目，用本地 claude CLI 按同一份 prompt 结构化，结果回传到
# llm_enrich_cache 表；本模块提供 pipeline 侧的读取。
#
# 稳定性设计（Mac 是工作机，不保证在线，这是硬前提）：
#   1. 缓存未命中 → enrich_one 走 OpenAI 原路径，行为与没有这套机制时完全一致
#   2. 读缓存本身任何异常 → 返回空 dict，等价于全部未命中
#   3. prompt_hash 不匹配的缓存行直接不选 —— prompt 一旦迭代，旧缓存自动全部失效，
#      不会出现"一半条目用旧口径、一半用新口径"的精神分裂数据

# 缓存是否要求 prompt_hash 完全一致才复用。
#
# 2026-07-28 改为默认**不要求**（Lawrence："改prompt和换模型后的数据结果混用就
# 混用了，没所谓"，冷启阶段以铺满数据为先）。改之前的行为是严格匹配，代价在当天
# 就实测到了：我调了一次 SYSTEM_PROMPT，hash 从 13c1dac7 变成 d9d04ce7，于是
# Mac 侧刚用公司额度算好的 696 条缓存**一条都用不上**，同一批内容被 VM 用个人
# OpenAI 账号又付费重算了一遍（那一轮 llm_cache_hits=0）。
#
# 放开的代价是如实的：库里会同时存在不同 prompt 版本、不同模型产出的结构化结果，
# 字段口径可能有细微差异（比如新 prompt 才有的 market_scope，旧缓存里没有——
# 这种缺字段的行会被 _valid_cached_enrichment 判为不合法而自动落回重算，
# 所以不会产生"字段缺失的脏事件"，只会少省一点钱）。
# 需要严格口径时（比如做正式评测要保证同一把尺子），把这个环境变量设成 false。
CACHE_REQUIRE_PROMPT_MATCH = (
    os.environ.get("B9_CACHE_REQUIRE_PROMPT_MATCH", "false").strip().lower() == "true")


def load_enrich_cache(conn, url_hashes: list[str], prompt_hash: str) -> dict:
    """按 url_hash 批量取预处理结果，返回 {url_hash: enriched_dict}。

    2026-08-02（ADR-002 A4）：结果里会带一个 `_embedding` 键（256 维 float32
    blob 解出的向量），是 Mac 经公司网关随 enrich 一起算好的。没带就是 None，
    下游照旧现算或退化——这个字段以下划线开头，write_events 按列写库时会
    自然忽略，不会污染事件表。

    是否要求 prompt_hash 一致由 CACHE_REQUIRE_PROMPT_MATCH 控制，默认不要求，
    理由见该常量的注释。任何异常都吞掉返回 {}——缓存是纯加速层，绝不允许它的
    故障影响主流程。
    """
    if not url_hashes:
        return {}
    out = {}
    try:
        cursor = conn.cursor()
        # IN 子句分块，避免单条 SQL 过长（一轮 800+ 条目 × 64 字符 hash）
        for i in range(0, len(url_hashes), 500):
            chunk = url_hashes[i:i + 500]
            placeholders = ",".join(["%s"] * len(chunk))
            if CACHE_REQUIRE_PROMPT_MATCH:
                cursor.execute(
                    f"""SELECT url_hash, enriched, embedding FROM llm_enrich_cache
                        WHERE prompt_hash = %s AND url_hash IN ({placeholders})""",
                    (prompt_hash, *chunk),
                )
            else:
                # 同一 url 可能有多版缓存，取最新的一条
                cursor.execute(
                    f"""SELECT url_hash, enriched, embedding FROM llm_enrich_cache
                        WHERE url_hash IN ({placeholders})
                        ORDER BY created_at ASC""",
                    tuple(chunk),
                )
            for url_hash, enriched, embedding in cursor.fetchall():
                try:
                    item = json.loads(enriched)
                except (TypeError, ValueError):
                    continue  # 单行坏数据只影响它自己，落回 OpenAI
                # 向量坏了不该连累结构化结果——blob_to_embedding 长度不符会
                # 返回 None，那条就只是没有向量，enrich 结果照常可用。
                try:
                    from .dedup import blob_to_embedding
                    item["_embedding"] = blob_to_embedding(embedding)
                except Exception:
                    item["_embedding"] = None
                out[url_hash] = item
        cursor.close()
    except Exception as e:
        logger.warning(f"enrich cache load failed (falling back to OpenAI for all): {e}")
        return {}
    if out:
        logger.info(f"Enrich cache: {len(out)}/{len(url_hashes)} pre-enriched locally")
    return out


def mark_enrich_cache_consumed(conn, url_hashes: list[str]) -> None:
    """标记已被本轮 pipeline 用掉的缓存行（观测用，不影响正确性）。"""
    if not url_hashes:
        return
    try:
        cursor = conn.cursor()
        for i in range(0, len(url_hashes), 500):
            chunk = url_hashes[i:i + 500]
            placeholders = ",".join(["%s"] * len(chunk))
            cursor.execute(
                f"UPDATE llm_enrich_cache SET consumed_at = NOW() "
                f"WHERE url_hash IN ({placeholders})",
                tuple(chunk),
            )
        conn.commit()
        cursor.close()
    except Exception as e:
        logger.warning(f"enrich cache consume-mark failed (harmless): {e}")


def save_enrich_cache(conn, entries: list[tuple], prompt_hash: str) -> None:
    """把 OpenAI 的原始结构化输出回写缓存，供下一轮同 URL 免费复用。

    `entries` 是 [(url_hash, raw_llm_output_dict, model_str), ...]。
    与 enrich bridge 的 submit 端点写同一张表、同一套 ON DUPLICATE 语义——
    谁后算谁生效，prompt_hash 闸门保证口径一致。纯优化，调用方需自行 try/except。
    """
    if not entries:
        return
    cursor = conn.cursor()
    for url_hash, raw, model in entries:
        if not url_hash:
            continue
        cursor.execute(
            """INSERT INTO llm_enrich_cache (url_hash, prompt_hash, enriched, model)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 prompt_hash = VALUES(prompt_hash),
                 enriched    = VALUES(enriched),
                 model       = VALUES(model),
                 created_at  = CURRENT_TIMESTAMP,
                 consumed_at = NULL""",
            (url_hash, prompt_hash, json.dumps(raw, ensure_ascii=False), model[:64]),
        )
    conn.commit()
    cursor.close()
