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

from .dedup import (
    COSINE_THRESHOLD, TIME_WINDOW_HOURS,
    blob_to_embedding, embedding_to_blob, hours_between,
)

logger = logging.getLogger(__name__)

# 跨轮比对的回溯窗口。取 72h 而非 48h，比 DC-3 的时间窗略宽一些留余量：
# 事件时间本身可能有偏差，窗口卡太紧会让边界上的重复漏过去。
LOOKBACK_HOURS = 72


def get_mysql_conn():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER", "root"),
        password=os.environ.get("MYSQL_PASSWORD", "***REMOVED***"),
        database=os.environ.get("MYSQL_DATABASE", "crypto_news"),
        charset="utf8mb4",
    )


def to_mysql_datetime(value: str | None) -> str | None:
    """ISO8601（含 T/Z/毫秒/时区）→ MySQL DATETIME 字符串。

    历史 bug：X API 返回 '2026-07-25T14:02:54.000Z'，MySQL DATETIME 直接拒绝，
    曾导致 77 条 X 事件静默丢失。所有入库时间都必须过这个函数。
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


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
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, event_fingerprint, embedding, source_names, sources,
                  source_count, merged_sources_count, time_event
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
         source_count, merged, time_event) = row
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
    sectors, coins, news_type, event_tier,
    score_market_impact, score_timeliness, score_hotness,
    score_authority, score_quality, importance_score,
    credibility_score, is_rumor, rumor_reason,
    sources, source_names, source_count, is_verified, language_origin,
    cluster_id, merged_sources_count,
    event_subject, event_action, event_fingerprint, embedding, social_interactions
) VALUES (
    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
    %s,%s,%s,%s,%s
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
    importance_score     = VALUES(importance_score),
    updated_at           = CURRENT_TIMESTAMP
"""


def write_events(events: list[dict], conn) -> int:
    """批量写入/更新事件，返回成功条数。"""
    if not events:
        return 0

    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
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
                event.get("event_tier", "C"),
                scores.get("score_market_impact", 0.0),
                scores.get("score_timeliness", 0.0),
                scores.get("score_hotness", 0.0),
                scores.get("score_authority", 0.0),
                scores.get("score_quality", 0.0),
                scores.get("importance_score", 0.0),
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
    UsageTracker.snapshot() 的输出，供 scripts/usage_monitor.py 做成本追踪。"""
    usage = usage or {}
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO pipeline_runs
               (raw_count, deduped_count, enriched_count, events_count,
                rumors_count, duration_seconds, status, error_msg,
                llm_input_tokens, llm_output_tokens, llm_cached_tokens,
                embedding_tokens, estimated_cost_usd)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (stats.get("raw", 0), stats.get("deduped", 0), stats.get("enriched", 0),
             stats.get("events", 0), stats.get("rumors", 0), duration, status, error,
             usage.get("chat_input_tokens", 0), usage.get("chat_output_tokens", 0),
             usage.get("chat_cached_tokens", 0), usage.get("embedding_tokens", 0),
             usage.get("estimated_cost_usd", 0.0)),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"pipeline_runs write failed: {e}")
    finally:
        cursor.close()
