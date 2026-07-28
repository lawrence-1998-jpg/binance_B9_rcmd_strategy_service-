#!/usr/bin/env python3
"""高优媒体高频抓取入口 —— 只抓 CNBC/Bloomberg/Forbes/WSJ/FT 等头部财经媒体，
不碰长尾源，跑得比 scripts/stage_fetch.py 更勤。

起因（2026-07-29）：Lawrence 明确要求头部财经媒体"实时性要更强一点，半小时
跑一轮"。但 stage_fetch.py 抓的是**全部**免费源，里面一大半是长尾加密自媒体，
把它整体提到 30 分钟一次没有必要——那些源本来就不要求这么高的时效，白白
增加 staging 表体积和后续处理压力。所以单独拆一个只覆盖头部媒体的脚本，
和 stage_fetch.py 各自独立跑，互不影响：
    stage_fetch.py           —— 全量源，每小时（cron: 30 * * * *）
    stage_fetch_priority.py  —— 头部媒体，每 30 分钟（cron: 15,45 * * * *）
两边都只抓取+存档，不进 LLM，成本仍然接近 0；LLM 处理节奏不变，仍由主
pipeline（run_pipeline.py，每小时）按处理优先级消费存档。
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
            os.environ[key.strip()] = value.strip()

log_dir = ROOT / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "stage_fetch_priority.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("stage_fetch_priority")

from crawler import staging, storage  # noqa: E402
from crawler.main import fetch_global_markets_sources  # noqa: E402


def main() -> int:
    start = time.time()
    conn = storage.get_mysql_conn()
    try:
        items = fetch_global_markets_sources()
        result = staging.stage_items(items, conn)
        stats = staging.staging_stats(conn)
        duration = round(time.time() - start, 1)
        logger.info(
            f"stage_fetch_priority done in {duration}s: fetched={len(items)} "
            f"new={result['new']} duplicate={result['duplicate']} | "
            f"staging table: total={stats['total']} unconsumed={stats['unconsumed']}"
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
