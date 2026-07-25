#!/usr/bin/env python3
"""Pipeline 运行入口 - 由 cron 每4小时调用"""
import os, sys, logging
from pathlib import Path

# 加载环境变量
env_file = Path(__file__).parent / "config" / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()  # 强制覆盖，避免 cron/systemd 残留旧值

# 日志配置
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "pipeline.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

sys.path.insert(0, str(Path(__file__).parent))

from crawler.pipeline import run_pipeline

if __name__ == "__main__":
    logging.info("=== Starting Pipeline Run ===")
    stats = run_pipeline()
    logging.info(f"=== Pipeline Complete: {stats} ===")
