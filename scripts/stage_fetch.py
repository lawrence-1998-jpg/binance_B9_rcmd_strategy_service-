#!/usr/bin/env python3
"""
高频抓取入口 —— 只抓取 + 存档，不进 LLM，成本接近 0。

由独立的、比主 pipeline 更频繁的 cron 调用（建议每 1-2 小时）。解决的问题见
`crawler/staging.py` 顶部说明：高频源的 RSS 服务端窗口固定，12 小时一次的
主 pipeline 抓取会让发布密集的源把内容挤出窗口、永久错过。

不抓 X（KOL 时间线 + 全网搜索）——按用户明确要求，"除了 X 这种要 API 额度的
接口，其它都可以更高频拉取"，X 维持主 pipeline 原有节奏，不接入这条高频路径。

用法（crontab 示例，每 2 小时整点跑，与主 pipeline 的 0/12 点错开）：
    0 2,4,6,8,10,14,16,18,20,22 * * * cd ~/crypto-news-crawler && \\
        /usr/bin/python3 scripts/stage_fetch.py >> logs/stage_fetch.log 2>&1
"""
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

env_file = ROOT / "config" / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()  # 强制覆盖，避免 cron 残留旧值

log_dir = ROOT / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "stage_fetch.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("stage_fetch")

from crawler import staging, storage  # noqa: E402
from crawler.main import fetch_cheap_sources  # noqa: E402


def main() -> int:
    start = time.time()
    conn = storage.get_mysql_conn()
    try:
        items = fetch_cheap_sources()
        result = staging.stage_items(items, conn)
        stats = staging.staging_stats(conn)
        duration = round(time.time() - start, 1)
        logger.info(
            f"stage_fetch done in {duration}s: fetched={len(items)} "
            f"new={result['new']} duplicate={result['duplicate']} | "
            f"staging table: total={stats['total']} unconsumed={stats['unconsumed']}"
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
