#!/usr/bin/env python3
"""Pipeline 运行入口 —— 由 cron 每小时调用（2026-07-28 起，此前是每 2 天 1 轮）。"""
import fcntl, os, sys, logging
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
    # 单实例锁（2026-07-28 加，配合 cron 从每 2 天 1 轮改为每小时 1 轮）。
    # 两天一次的时候一轮跑 20 分钟也不可能撞上下一次；改成每小时之后，只要某一轮
    # 因为积压/限流/上游变慢跑超 60 分钟，下一个整点就会叠跑——两个进程同时读同一批
    # 未消费 staging 条目（consumed_at 要到写库成功后才标记，见 staging.py 的说明），
    # 结果是同一批内容被结构化两次，钱花两遍。用 flock 挡住：拿不到锁说明上一轮还在
    # 跑，直接退出，等下一个整点即可，不排队不重试。
    lock_path = Path(__file__).parent / "logs" / "pipeline.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.warning("=== 上一轮 pipeline 仍在运行，本轮跳过（单实例锁）===")
        sys.exit(0)

    try:
        logging.info("=== Starting Pipeline Run ===")
        stats = run_pipeline()
        logging.info(f"=== Pipeline Complete: {stats} ===")
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
