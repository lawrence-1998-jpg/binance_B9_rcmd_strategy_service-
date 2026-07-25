"""
原始条目存档层 —— 解耦"抓取频率"与"LLM 处理频率"。

背景（2026-07-26）：cron 从每 4 小时改成每 12 小时降本后，排查漏召案例
（Triple-A 支付平台被盗事件）发现：吴说等高频源的 RSS 是服务端固定窗口
（约 30-50 条），12 小时间隔会让发布密集的源把窗口内的旧内容挤出去——
不是我们的新鲜度过滤或去重误杀（两者实测误杀率均为 0），是内容在我们
抓取之前就已经从源头消失了。

抓取 RSS/HTML/搜索引擎本身不花钱，真正的成本大头是下游 LLM 结构化
（`crawler/pipeline.py:enrich_one`，约 $0.0076/条）。所以把两件事分开：

    高频（如每 1-2 小时，由 scripts/stage_fetch.py 独立 cron 调用）
        跑 crawler.main.fetch_cheap_sources()，只做「抓取 + 存档」，
        不进 LLM，成本接近 0

    低频（现有 12 小时 pipeline 节奏不变）
        pipeline.run_pipeline() 从存档表里捞出所有未消费的条目，
        叠加当轮实时抓取的 X（KOL + 搜索，按用户要求维持原节奏不提速），
        走原有的 粗去重 → LLM → 聚合 → 打分 → 入库

这样高频源不再受 12 小时窗口限制而滚屏丢失，但 LLM 调用次数和频率完全不变。

X 不走存档：按用户明确要求，"除了 X 这种要 API 额度的接口，其它都可以更高频
拉取"——X 维持现有节奏，不加入这条高频路径。
"""
import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _url_hash(url: str) -> str:
    return hashlib.sha256((url or "").strip().rstrip("/").encode()).hexdigest()


def stage_items(items: list[dict], conn) -> dict:
    """把抓到的条目写入存档表，按 url 去重（重复 url 只更新 fetched_at）。

    返回 {"new": 新增条数, "duplicate": 已存在条数}——duplicate 高不代表抓取
    有问题，相邻两次高频抓取本来就该有大量重叠，这正是"提高抓取频率、
    降低滚屏丢失概率"这个设计要生效的地方。
    """
    if not items:
        return {"new": 0, "duplicate": 0}

    cursor = conn.cursor()
    new_count = duplicate_count = 0

    for item in items:
        url = item.get("url", "")
        if not url:
            continue
        url_hash = _url_hash(url)
        try:
            cursor.execute(
                """INSERT INTO raw_items_staging
                   (source, title, url, url_hash, summary, published_at,
                    lang, authority, type)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE fetched_at = CURRENT_TIMESTAMP""",
                (item.get("source", ""), item.get("title", ""), url, url_hash,
                 item.get("summary", ""), item.get("published_at", ""),
                 item.get("lang", "en"), item.get("authority", 3),
                 item.get("type", "rss")),
            )
            if cursor.rowcount == 1:  # INSERT 走的是 1，UPDATE 分支走的是 2
                new_count += 1
            else:
                duplicate_count += 1
        except Exception as e:
            logger.warning(f"Stage failed for {url[:80]}: {e}")

    conn.commit()
    cursor.close()
    logger.info(f"Staging: {new_count} new, {duplicate_count} duplicate "
               f"(of {len(items)} fetched)")
    return {"new": new_count, "duplicate": duplicate_count}


def consume_staged_items(conn, max_age_days: int = 7) -> list[dict]:
    """取出全部未消费的存档条目，标记为已消费，返回可直接送入 pipeline 的
    item 列表（字段与 crawler/main.py 里其它 fetch_* 函数一致）。

    `max_age_days` 兜底：正常情况下 fetch_cheap_sources 内部的新鲜度过滤已经
    挡掉陈旧内容，这里是防万一存档表堆积（比如主 pipeline 挂了几天没跑）时，
    不要把过老的内容也当"新鲜存货"送进 LLM。
    """
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT id, source, title, url, summary, published_at, lang, authority, type
           FROM raw_items_staging
           WHERE consumed_at IS NULL
             AND fetched_at >= NOW() - INTERVAL %s DAY
           ORDER BY fetched_at ASC""",
        (max_age_days,),
    )
    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        logger.info("Staging: no unconsumed items")
        return []

    ids = [r["id"] for r in rows]
    cursor = conn.cursor()
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"UPDATE raw_items_staging SET consumed_at = %s WHERE id IN ({placeholders})",
        (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), *ids),
    )
    conn.commit()
    cursor.close()

    items = [{
        "source": r["source"], "title": r["title"], "url": r["url"],
        "summary": r["summary"] or "", "published_at": r["published_at"] or "",
        "lang": r["lang"] or "en", "authority": r["authority"] or 3,
        "type": r["type"] or "rss",
    } for r in rows]
    logger.info(f"Staging: consumed {len(items)} items")
    return items


def staging_stats(conn) -> dict:
    """存档表水位，供运维/监控使用。"""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT COUNT(*), SUM(consumed_at IS NULL), MIN(fetched_at), MAX(fetched_at)
           FROM raw_items_staging"""
    )
    total, unconsumed, oldest, newest = cursor.fetchone()
    cursor.close()
    return {
        "total": total or 0,
        "unconsumed": unconsumed or 0,
        "oldest_fetched_at": oldest.isoformat() if oldest else None,
        "newest_fetched_at": newest.isoformat() if newest else None,
    }
