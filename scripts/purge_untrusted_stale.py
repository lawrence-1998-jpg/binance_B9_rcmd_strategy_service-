#!/usr/bin/env python3
"""存量清理：删掉"真实发布时间不可知"的事件（2026-07-29 数字税旧闻事故）。

## 起因

一条 6/27 的旧闻以 A 档、日期 2026-07-28 的身份进了库并在前端展示。根因见
`crawler/source_trust.py` 的模块说明：搜索聚合器（Google News/ddgs）给的
`published_at` 是**它重新分发的时间**而不是原文发布时间，而这类条目又没有
正文，导致 LLM 后的事件日期兜底闸拿不到任何材料去纠正——两道防线同时失效。

`crawler/source_trust.py` 已经在 LLM 前把这类条目挡住了（防止再进新的），
本脚本负责清掉**已经在库里的存量**。

## 判定口径（与 source_trust.should_drop_untrusted 保持同一套逻辑）

删除条件：**全部信源都是聚合器（web_search）** 且 **source_count == 1**。

  · "全部都是聚合器"——只要有一个直连发行方的信源，跨轮归并就把可信时间
    带进来了，这条事件的日期就有据可依，不删。
  · "单一信源"——多个聚合器信源互相印证，至少说明这条内容近期确实在被
    多处转载，比孤证可信，不删（保守起见留下）。

实测范围（近 7 天）：4440 条事件里命中 745 条，其中 S 档 5、A 档 44、
B 档 130、C 档 162、D 档 404——D 档占一半以上，说明这批本来也大多是噪音。

## S/A 档单独走人工可核查路径，不是无差别删

49 条 S/A 档会出现在首屏，直接删掉的代价比 D 档大得多。所以脚本默认把它们
**单独列出来**（`--report-sa`）而不是直接删，附上标题和信源，方便用搜索
逐条核实真实发布时间后再决定——这也是 Lawrence 建议的做法（"可以尝试去
搜索，点开信息源链接去看"）。确认要连 S/A 一起删时传 `--include-sa`。

## 用法

    python3 scripts/purge_untrusted_stale.py                # 预演，只统计不删
    python3 scripts/purge_untrusted_stale.py --report-sa    # 列出 S/A 档明细
    python3 scripts/purge_untrusted_stale.py --apply        # 删 B/C/D 档
    python3 scripts/purge_untrusted_stale.py --apply --include-sa   # 连 S/A 一起删

删除前一律先备份进 `purged_stale_20260729` 表，可回滚。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import source_trust, storage  # noqa: E402

BACKUP_TABLE = "purged_stale_20260729"


def load_candidates(conn, days: int):
    """取出「全部信源都是聚合器 且 单一信源」的事件。

    判定放在 Python 里做而不是写进 SQL：sources 是 JSON 数组，用
    source_trust.event_sources_all_aggregated 复用生产同一套判定逻辑，
    避免 SQL 里再手写一遍 JSON_SEARCH 条件、两边口径漂移。
    """
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, title_zh, date, time_event, event_tier, importance_score,
               sources, source_names, source_count
        FROM news_events
        WHERE date >= CURDATE() - INTERVAL %s DAY AND source_count = 1
    """, (days,))
    rows = cur.fetchall()
    cur.close()

    out = []
    for r in rows:
        srcs = r.get("sources")
        if isinstance(srcs, str):
            try:
                srcs = json.loads(srcs)
            except (json.JSONDecodeError, TypeError):
                srcs = []
        if source_trust.event_sources_all_aggregated(srcs or []):
            r["_sources"] = srcs or []
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的执行删除（默认只预演）")
    ap.add_argument("--include-sa", action="store_true",
                    help="连 S/A 档一起删（默认保留，需人工核实后再定）")
    ap.add_argument("--report-sa", action="store_true", help="列出 S/A 档明细供人工核查")
    ap.add_argument("--days", type=int, default=30, help="回溯天数，默认 30")
    args = ap.parse_args()

    conn = storage.get_mysql_conn()
    try:
        cands = load_candidates(conn, args.days)
        by_tier = {}
        for r in cands:
            by_tier.setdefault(r["event_tier"] or "?", []).append(r)

        print(f"命中「聚合器孤证」事件：{len(cands)} 条（回溯 {args.days} 天）")
        for t in ("S", "A", "B", "C", "D"):
            if by_tier.get(t):
                print(f"  {t} 档：{len(by_tier[t])}")

        sa = by_tier.get("S", []) + by_tier.get("A", [])
        if args.report_sa:
            print(f"\n=== S/A 档明细（{len(sa)} 条，建议逐条搜索核实真实发布时间）===")
            for r in sa:
                src = (r["_sources"][0] or {}).get("name", "?") if r["_sources"] else "?"
                url = (r["_sources"][0] or {}).get("url", "") if r["_sources"] else ""
                print(f"  [{r['event_tier']}] {r['date']} {(r['title_zh'] or '')[:38]}")
                print(f"        信源={src}  {url[:100]}")

        targets = cands if args.include_sa else [r for r in cands
                                                 if r["event_tier"] not in ("S", "A")]
        print(f"\n拟删除：{len(targets)} 条"
              f"（{'含' if args.include_sa else '不含'} S/A 档）")

        if not args.apply:
            print("预演模式，未改动数据库。加 --apply 执行。")
            return 0
        if not targets:
            print("没有要删的。")
            return 0

        cur = conn.cursor()
        cur.execute(f"CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} LIKE news_events")
        ids = [r["id"] for r in targets]
        # 分批：id 列表可能上千，一次 IN 太长
        deleted = 0
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            ph = ",".join(["%s"] * len(chunk))
            cur.execute(f"INSERT IGNORE INTO {BACKUP_TABLE} "
                        f"SELECT * FROM news_events WHERE id IN ({ph})", chunk)
            cur.execute(f"DELETE FROM news_events WHERE id IN ({ph})", chunk)
            deleted += cur.rowcount
            conn.commit()
        cur.close()
        print(f"已删除 {deleted} 条，备份在 {BACKUP_TABLE}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
