#!/usr/bin/env python3
"""
存量数据回填：把历史事件的 x_tweet_id 关联写回 x_raw_posts.news_event_id
（一次性运维脚本，可反复执行）。

`crawler.storage.persist_x_post_links` 上线前，write_events 从不回写这一列，
导致 /api/news/<id>/x-sources 永远查不到数据——关联信息其实一直都在
news_events.sources 里的 x_tweet_id 字段，只是没写回 x_raw_posts。本脚本读出
全部历史事件，复用 persist_x_post_links 补上这一列；之后新入库的事件由
pipeline 自己维护，不再需要跑这个脚本。

用法：
    python3 scripts/backfill_x_links.py
"""
import json
import os
import sys
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

from crawler import storage  # noqa: E402


def load_events(conn) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute("SELECT id, sources FROM news_events")
    rows = cursor.fetchall()
    cursor.close()

    events = []
    for event_id, sources_raw in rows:
        try:
            sources = json.loads(sources_raw) if sources_raw else []
        except (json.JSONDecodeError, TypeError):
            sources = []
        events.append({"id": event_id, "sources": sources})
    return events


def main() -> int:
    conn = storage.get_mysql_conn()
    try:
        events = load_events(conn)
        print(f"读到 {len(events)} 个历史事件，开始回填 x_raw_posts.news_event_id ...")
        written = storage.persist_x_post_links(events, conn)
        print(f"完成：{written} 条 x_raw_posts 行已关联到事件 id")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
