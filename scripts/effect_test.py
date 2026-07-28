#!/usr/bin/env python3
"""业务效果测试 —— 本期排序改造前后对比（2026-07-29）。

功能测试（scripts/qa_suite.py）回答的是"有没有 bug"。这个脚本回答的是另一个
问题："改完之后，用户看到的东西真的变好了吗"——Lawrence 明确要了这一项。

## 对照怎么来的

改造前的排序快照存在 `ranking_before_20260729`（重算 importance_score 之前
CREATE TABLE AS SELECT 出来的一份 3174 行拷贝）。它是真实的旧口径分数，不是
事后模拟——模拟会带上"我以为旧公式长什么样"的假设，而库里那 87% 的旧分恰恰
是好几个历史版本混在一起的，模拟不出来。

## 五项指标，每一项对应一条业务诉求

1. **非加密内容在首屏的占比** —— 老板要求"美股/港股/日韩/世界经济也要放出来，
   而且重点新闻要排在前面"。这是最直接的验收口径。
2. **首屏 S/A 档占比** —— "排序结果尤其是首几刷要有冲击力"。首屏被 C/D 档
   噪音占据是这次改造要解决的问题之一。
3. **新闻类型覆盖数** —— 筛选器要有东西可筛。首屏只有 crypto 一种类型，
   等于类型 chip 是个摆设。
4. **广度/冲击力两个新因子的区分度** —— 如果新因子在首屏和大盘上分布一样，
   说明它们没起作用，只是增加了计算量。用首屏均值 vs 全库均值的差值衡量。
5. **换手率** —— 改造前后 Top20 的重合度。太高说明改了等于没改，太低说明
   排序被推翻得不合理，两头都要看到数才能判断。

指标 1/2/3 有明确的方向性预期（应该上升），4/5 是描述性的——只报数不判分，
因为它们没有"越高越好"的天然方向。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import storage

TOP_N = 20
WINDOW_DAYS = 7
SNAPSHOT = "ranking_before_20260729"

CRYPTO_SCOPES = ("crypto",)


def q(conn, sql, params=None):
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close()
    return rows


def top_before(conn):
    return q(conn, f"""
        SELECT s.id, s.importance_score, s.event_tier, s.market_scope, s.title_zh
        FROM {SNAPSHOT} s
        JOIN news_events e ON e.id = s.id          -- 只比仍在库的行，被清掉的不参与
        WHERE s.date >= CURDATE() - INTERVAL %s DAY
        ORDER BY s.importance_score DESC
        LIMIT %s
    """, (WINDOW_DAYS, TOP_N))


def top_after(conn):
    return q(conn, """
        SELECT id, importance_score, event_tier, market_scope, title_zh
        FROM news_events
        WHERE date >= CURDATE() - INTERVAL %s DAY
        ORDER BY importance_score DESC
        LIMIT %s
    """, (WINDOW_DAYS, TOP_N))


def profile(rows):
    n = len(rows) or 1
    non_crypto = sum(1 for r in rows if r["market_scope"] not in CRYPTO_SCOPES)
    sa = sum(1 for r in rows if r["event_tier"] in ("S", "A"))
    scopes = {}
    for r in rows:
        scopes[r["market_scope"] or "未标注"] = scopes.get(r["market_scope"] or "未标注", 0) + 1
    return {
        "n": len(rows),
        "non_crypto_pct": round(non_crypto / n * 100, 1),
        "sa_pct": round(sa / n * 100, 1),
        "scope_kinds": len(scopes),
        "scopes": scopes,
    }


def factor_discrimination(conn):
    """新因子在首屏 vs 全库的均值差。差值≈0 说明因子没有区分力。"""
    rows = q(conn, """
        SELECT
          AVG(CASE WHEN rk <= %s THEN score_breadth END) AS top_b,
          AVG(score_breadth)                            AS all_b,
          AVG(CASE WHEN rk <= %s THEN score_punch END)  AS top_i,
          AVG(score_punch)                              AS all_i
        FROM (
          SELECT score_breadth, score_punch,
                 ROW_NUMBER() OVER (ORDER BY importance_score DESC) AS rk
          FROM news_events
          WHERE date >= CURDATE() - INTERVAL %s DAY
        ) t
    """, (TOP_N, TOP_N, WINDOW_DAYS))
    r = rows[0]
    def f(x): return round(float(x), 4) if x is not None else None
    return {
        "breadth_top": f(r["top_b"]), "breadth_all": f(r["all_b"]),
        "punch_top": f(r["top_i"]),   "punch_all": f(r["all_i"]),
    }


def main():
    conn = storage.get_mysql_conn()
    try:
        before, after = top_before(conn), top_after(conn)
        pb, pa = profile(before), profile(after)
        ids_b = {r["id"] for r in before}
        ids_a = {r["id"] for r in after}
        overlap = len(ids_b & ids_a)
        disc = factor_discrimination(conn)

        report = {
            "window_days": WINDOW_DAYS, "top_n": TOP_N,
            "before": pb, "after": pa,
            "delta": {
                "non_crypto_pct": round(pa["non_crypto_pct"] - pb["non_crypto_pct"], 1),
                "sa_pct": round(pa["sa_pct"] - pb["sa_pct"], 1),
                "scope_kinds": pa["scope_kinds"] - pb["scope_kinds"],
            },
            "turnover": {
                "overlap": overlap,
                "turnover_pct": round((1 - overlap / (len(ids_a) or 1)) * 100, 1),
            },
            "factor_discrimination": disc,
            "top_after_titles": [
                {"tier": r["event_tier"], "scope": r["market_scope"],
                 "score": round(float(r["importance_score"]), 4),
                 "title": r["title_zh"]}
                for r in after[:10]
            ],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))

        print("\n" + "=" * 68)
        print("业务效果结论")
        print("=" * 68)
        for label, key, unit in [("非加密内容首屏占比", "non_crypto_pct", "%"),
                                 ("首屏 S/A 档占比", "sa_pct", "%"),
                                 ("首屏新闻类型数", "scope_kinds", " 种")]:
            b, a = pb[key], pa[key]
            arrow = "↑" if a > b else ("↓" if a < b else "—")
            print(f"  {label:<20} {b}{unit} → {a}{unit}  {arrow}")
        print(f"  {'Top20 换手率':<20} {report['turnover']['turnover_pct']}%"
              f"（{overlap}/{TOP_N} 条留在首屏）")
        print(f"  {'广度因子区分度':<20} 首屏 {disc['breadth_top']} vs 全库 {disc['breadth_all']}")
        print(f"  {'冲击力因子区分度':<20} 首屏 {disc['punch_top']} vs 全库 {disc['punch_all']}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
