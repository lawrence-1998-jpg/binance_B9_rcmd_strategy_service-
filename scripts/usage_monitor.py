#!/usr/bin/env python3
"""
OpenAI 用量与成本监控（一次性/定期人工查看的小工具）。

背景：OpenAI 官方的 usage/costs API（`/v1/organization/usage/*`、
`/v1/organization/costs`）用现有 key 调用返回 403（缺 `api.usage.read` scope，
这个 scope 要在 OpenAI 后台单独为 key 授权，需要账号所有者操作，不是代码能
绕过的）；`/v1/dashboard/billing/usage` 需要 session key 而非 API key。

所以成本数据来自应用层自己的统计（crawler/usage_tracker.py 在每次调用后读
`resp.usage` 累加），落在 `pipeline_runs` 表里，本脚本只是把它汇总展示。
这个数字是**估算**，依据 crawler/usage_tracker.py 里维护的价格表——如果
OpenAI 调价而没有同步更新那张表，这里会跟实际账单出现偏差。

用法：
    python3 scripts/usage_monitor.py                # 最近 30 天概览
    python3 scripts/usage_monitor.py --days 7        # 最近 7 天
    python3 scripts/usage_monitor.py --runs 5         # 只看最近 5 轮明细
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
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


def fetch_runs(conn, since: datetime):
    cursor = conn.cursor()
    cursor.execute(
        """SELECT run_at, status, llm_input_tokens, llm_output_tokens,
                  llm_cached_tokens, embedding_tokens, estimated_cost_usd,
                  enriched_count, events_count
           FROM pipeline_runs WHERE run_at >= %s ORDER BY run_at ASC""",
        (since.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    rows = cursor.fetchall()
    cursor.close()
    return rows


def fmt_usd(v) -> str:
    return f"${float(v or 0):.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=30, help="统计最近 N 天（默认 30）")
    parser.add_argument("--runs", type=int, default=10, help="明细展示最近 N 轮（默认 10）")
    args = parser.parse_args()

    conn = storage.get_mysql_conn()
    since = datetime.utcnow() - timedelta(days=args.days)
    rows = fetch_runs(conn, since)
    conn.close()

    if not rows:
        print(f"最近 {args.days} 天没有 pipeline 运行记录。")
        print("提示：如果这是 002_usage_tracking.sql 迁移前的历史数据，"
              "旧记录的用量字段会是 0，属正常——只有迁移后的新一轮才有数据。")
        return 0

    print("=" * 78)
    print(f"OpenAI 用量与成本监控 — 最近 {args.days} 天（{len(rows)} 轮）")
    print("=" * 78)

    total_in = sum(r[2] or 0 for r in rows)
    total_out = sum(r[3] or 0 for r in rows)
    total_cached = sum(r[4] or 0 for r in rows)
    total_emb = sum(r[5] or 0 for r in rows)
    total_cost = sum(float(r[6] or 0) for r in rows)
    ok_runs = sum(1 for r in rows if r[1] == "success")

    print(f"\n成功运行：{ok_runs}/{len(rows)} 轮")
    print(f"LLM token：输入 {total_in:,}（含缓存 {total_cached:,}） / 输出 {total_out:,}")
    print(f"Embedding token：{total_emb:,}")
    print(f"累计估算成本：{fmt_usd(total_cost)}")

    if len(rows) >= 2:
        span_days = max((rows[-1][0] - rows[0][0]).total_seconds() / 86400, 0.1)
        per_day = total_cost / span_days
        print(f"\n日均成本：{fmt_usd(per_day)}")
        print(f"预估月成本（× 30）：{fmt_usd(per_day * 30)}")

        # 当前 cadence 下的理论月成本：按最近一轮的单轮成本 × 已知的每日运行次数。
        # 2026-07-26 cron 已从每 4 小时（6 次/天）改为每 12 小时（2 次/天）。
        last_cost = float(rows[-1][6] or 0)
        for label, runs_per_day in (("每天 2 次（当前 cron）", 2), ("每天 6 次（旧 cron）", 6)):
            print(f"  按最近一轮单价 {fmt_usd(last_cost)} 折算，{label}："
                  f"{fmt_usd(last_cost * runs_per_day)}/天，"
                  f"{fmt_usd(last_cost * runs_per_day * 30)}/月")

    print()
    print("-" * 78)
    print(f"最近 {min(args.runs, len(rows))} 轮明细")
    print("-" * 78)
    print(f"{'时间(UTC)':<20}{'状态':<9}{'输入tok':<10}{'输出tok':<9}"
          f"{'缓存tok':<9}{'embtok':<8}{'成本':<10}{'事件数'}")
    for r in rows[-args.runs:]:
        run_at, status, tin, tout, tcached, temb, cost, enriched, events = r
        print(f"{str(run_at):<20}{status:<9}{tin or 0:<10,}{tout or 0:<9,}"
              f"{tcached or 0:<9,}{temb or 0:<8,}{fmt_usd(cost):<10}{events or 0}")

    print()
    print("=" * 78)
    print("价格表来源与口径说明见 crawler/usage_tracker.py 顶部注释；")
    print("如与实际账单持续偏差较大，去 OpenAI 后台核对最新单价并更新那张表。")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
