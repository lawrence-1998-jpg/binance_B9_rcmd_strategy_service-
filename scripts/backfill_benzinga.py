#!/usr/bin/env python3
"""一次性回填 Benzinga 历史新闻 —— scripts/backfill_benzinga.py（2026-07-30）

背景：接入当天生产路径只按 90 分钟回溯窗跑，存量历史是空的。Lawrence 下午
要给老板演示"美股调权 + 新闻捕获效果"，需要产品里现在就能看到有分量的
Benzinga 内容，等 30 分钟一次的常规节奏慢慢攒不现实。这个脚本只做一次性的
翻页回填，接完之后不需要再跑——往后的增量由 stage_fetch_priority.py 常规
覆盖。

只回填到 `--days` 天前（默认 4 天）：超过 `crawler/source_trust.py` 的
MAX_AGE_DAYS（5 天展示窗口）的内容就算拉回来也不会出现在默认 `/api/news`
结果里，回填更久远的历史对这次演示没有意义，只会白花 LLM 结构化的钱。
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

env_file = ROOT / "config" / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

log_dir = ROOT / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "backfill_benzinga.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("backfill_benzinga")

from crawler import staging, storage  # noqa: E402
from crawler.benzinga_news import backfill_benzinga_news  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=4.0,
                        help="回填最近多少天（默认 4，留在 5 天展示窗口内）")
    args = parser.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info(f"回填起点：{since_str}")

    items = backfill_benzinga_news(since_str)
    if not items:
        logger.warning("没拉到任何数据，检查 MASSIVE_API_KEY 或网络")
        return 1

    conn = storage.get_mysql_conn()
    try:
        result = staging.stage_items(items, conn)

        # ── 回填自动降级（2026-07-30 事故的机制化）────────────────────
        # 回填条目会继承信源的高优先级（Benzinga=P0），与当天新闻同级 FIFO
        # 排队且 fetched_at 更早——1859 条历史存量把当天新闻堵了 4-5 小时，
        # 靠人工 UPDATE 才解开。现在**非当天**的回填条目入库后立即降到 P4，
        # 当天的保留原优先级（回填窗口通常含今天，今天那部分就是实时新闻）。
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        old_hashes = [staging.url_hash(it["url"]) for it in items
                      if (it.get("published_at") or "")[:10] < today and it.get("url")]
        demoted = 0
        if old_hashes:
            cur = conn.cursor()
            for i in range(0, len(old_hashes), 500):
                chunk = old_hashes[i:i + 500]
                ph = ",".join(["%s"] * len(chunk))
                cur.execute(
                    f"UPDATE raw_items_staging SET priority = 4 "
                    f"WHERE consumed_at IS NULL AND priority < 4 AND url_hash IN ({ph})",
                    tuple(chunk))
                demoted += cur.rowcount
            conn.commit()
            cur.close()

        stats = staging.staging_stats(conn)
        logger.info(
            f"回填完成：fetched={len(items)} new={result['new']} "
            f"duplicate={result['duplicate']} demoted_to_P4={demoted} | "
            f"staging: total={stats['total']} unconsumed={stats['unconsumed']}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
