#!/usr/bin/env python3
"""
存量数据回填与历史去重（一次性运维脚本）。

去重重构上线前入库的行没有 embedding / event_fingerprint，导致两个问题：
  1. 跨轮归并（DC-4）看不见它们，新事件会和历史行重复
  2. 上线前积累的重复行（实测 841 条里有 149 条）不会自动消失

本脚本分两个阶段，默认只做只读的第一阶段 + 干跑报告，加 --apply 才真正合并：

  阶段一  为缺 embedding 的行补算向量（非破坏性，可反复执行）
  阶段二  按向量聚类找出历史重复，合并信源后删除冗余行（破坏性，需 --apply）

用法：
    python3 scripts/backfill_dedup.py              # 回填向量 + 干跑去重报告
    python3 scripts/backfill_dedup.py --apply      # 真正执行合并与删除
    python3 scripts/backfill_dedup.py --report-only  # 只看报告，不回填
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 加载 .env（与 run_pipeline.py 一致，强制覆盖以免 cron/systemd 残留旧值）
env_file = ROOT / "config" / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

import numpy as np  # noqa: E402

from crawler import storage  # noqa: E402
from crawler.dedup import (  # noqa: E402
    COSINE_THRESHOLD, TIME_WINDOW_HOURS, EMBED_DIM,
    blob_to_embedding, embed_texts, embedding_to_blob,
)
from crawler.pipeline import get_openai_client  # noqa: E402
from crawler.scoring import (  # noqa: E402
    W_AUTH, W_HOT, W_IMPACT, W_QUAL, W_TIME, compute_hotness, social_baseline,
)

BATCH = 256


# ── 阶段一：回填 embedding ───────────────────────────────────────────

def backfill_embeddings(conn) -> int:
    """给所有缺向量的行补算 embedding。可反复执行，只处理 embedding IS NULL 的行。"""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, title_en, description_short_en
           FROM news_events WHERE embedding IS NULL"""
    )
    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        print("阶段一：所有行都已有 embedding，跳过")
        return 0

    print(f"阶段一：为 {len(rows)} 行补算 embedding …")
    client = get_openai_client()
    updated = 0

    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        texts = [f"{title}. {desc or ''}"[:1000] for _, title, desc in chunk]
        vectors = embed_texts(texts, client)

        cursor = conn.cursor()
        for (event_id, _, _), vector in zip(chunk, vectors):
            blob = embedding_to_blob(vector)
            if blob is None:
                continue
            cursor.execute(
                "UPDATE news_events SET embedding = %s WHERE id = %s", (blob, event_id)
            )
            updated += 1
        conn.commit()
        cursor.close()
        print(f"  {min(start + BATCH, len(rows))}/{len(rows)}")

    print(f"阶段一完成：回填 {updated} 行\n")
    return updated


# ── 阶段二：历史重复聚类 ─────────────────────────────────────────────

def load_all(conn) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, title_zh, title_en, date, time_event, embedding,
                  source_names, source_count, merged_sources_count,
                  score_authority, importance_score, event_tier,
                  LENGTH(description_short_zh),
                  score_market_impact, score_timeliness, score_quality,
                  social_interactions
           FROM news_events WHERE embedding IS NOT NULL
           ORDER BY date DESC"""
    )
    rows = cursor.fetchall()
    cursor.close()

    events = []
    for r in rows:
        try:
            names = json.loads(r[6]) if r[6] else []
        except (json.JSONDecodeError, TypeError):
            names = []
        events.append({
            "id": r[0], "title_zh": r[1], "title_en": r[2], "date": r[3],
            "time_event": r[4], "embedding": blob_to_embedding(r[5]),
            "source_names": names, "source_count": r[7] or 1,
            "merged_sources_count": r[8] or 1, "score_authority": r[9] or 0.0,
            "importance_score": r[10] or 0.0, "event_tier": r[11] or "C",
            "desc_len": r[12] or 0,
            "score_market_impact": r[13] or 0.0, "score_timeliness": r[14] or 0.0,
            "score_quality": r[15] or 0.0, "social_interactions": r[16] or 0,
        })
    return events


def find_duplicate_clusters(events: list[dict]) -> list[list[dict]]:
    """按日期分桶后做向量聚类，返回大小 >1 的簇。

    先按日期分桶是为了避开 O(n²)：同一事件的报道必然集中在相邻一两天，
    跨月的两条不可能是同一事件。桶内再两两比向量。
    """
    by_date = defaultdict(list)
    for event in events:
        if event["embedding"] is None:
            continue
        by_date[str(event["date"])].append(event)

    # 相邻日期合并进同一个比较窗（事件可能跨零点报道）
    dates = sorted(by_date)
    clusters = []
    for i, date in enumerate(dates):
        window = list(by_date[date])
        if i + 1 < len(dates):
            window += by_date[dates[i + 1]]
        if len(window) < 2:
            continue

        matrix = np.stack([e["embedding"] for e in window])
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.maximum(norms, 1e-9)
        sim = matrix @ matrix.T

        # 只处理"代表条属于当前日期"的簇，避免相邻日期窗口重复产出同一簇
        seen_in_window = set()
        for a in range(len(window)):
            if window[a]["date"] != by_date[date][0]["date"]:
                continue
            if window[a]["id"] in seen_in_window:
                continue
            group = [window[a]]
            seen_in_window.add(window[a]["id"])
            for b in range(len(window)):
                if a == b or window[b]["id"] in seen_in_window:
                    continue
                if sim[a][b] >= COSINE_THRESHOLD:
                    group.append(window[b])
                    seen_in_window.add(window[b]["id"])
            if len(group) > 1:
                clusters.append(group)

    # 一条只能属于一个簇：按簇大小降序贪心分配
    assigned, final = set(), []
    for group in sorted(clusters, key=len, reverse=True):
        fresh = [e for e in group if e["id"] not in assigned]
        if len(fresh) > 1:
            final.append(fresh)
            assigned.update(e["id"] for e in fresh)
    return final


def pick_representative(group: list[dict]) -> dict:
    """簇内保留规则（文档三章）：权威最高 → 已聚合信源最多 → 信息最完整。

    把 source_count 排在 desc_len 之前：一条已经代表 3 家报道的行，比一条只有单源
    但摘要写得长的行更适合当代表——多源交叉本身就是可信度证据。
    """
    return max(group, key=lambda e: (e["score_authority"], e["source_count"],
                                     e["desc_len"], e["importance_score"]))


def merge_clusters(conn, clusters: list[list[dict]], apply: bool,
                   baseline: float) -> tuple[int, int]:
    """把每个簇合并到代表条，删除其余行。apply=False 时只统计不落库。"""
    merged_rows = deleted_rows = 0

    for group in clusters:
        keeper = pick_representative(group)
        others = [e for e in group if e["id"] != keeper["id"]]
        if not others:
            continue

        all_names = sorted(set(keeper["source_names"]).union(
            *[set(e["source_names"]) for e in others]
        ))
        source_count = max(len({n.split("/")[0] for n in all_names}),
                           keeper["source_count"])
        merged_count = sum(e["merged_sources_count"] for e in group)
        social = max(e["social_interactions"] for e in group)

        # 信源数和社交互动都变了，H 因子必须跟着重算，否则合并后的行仍带着
        # "单源"时算出的低热度分。M/T/A/Q 不受合并影响，沿用库中已有值。
        hotness = compute_hotness(
            {"social_interactions": social, "source_count": source_count}, baseline
        )
        importance = round(
            W_IMPACT * keeper["score_market_impact"] +
            W_TIME * keeper["score_timeliness"] +
            W_HOT * hotness +
            W_AUTH * keeper["score_authority"] +
            W_QUAL * keeper["score_quality"], 4
        )

        if apply:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE news_events
                   SET source_names = %s, source_count = %s,
                       merged_sources_count = %s, is_verified = %s,
                       social_interactions = %s, score_hotness = %s,
                       importance_score = %s
                   WHERE id = %s""",
                (json.dumps(all_names, ensure_ascii=False), source_count,
                 merged_count, source_count >= 2, social,
                 round(hotness, 4), importance, keeper["id"]),
            )
            placeholders = ",".join(["%s"] * len(others))
            cursor.execute(
                f"DELETE FROM news_events WHERE id IN ({placeholders})",
                tuple(e["id"] for e in others),
            )
            conn.commit()
            cursor.close()

        merged_rows += 1
        deleted_rows += len(others)

    return merged_rows, deleted_rows


def print_report(clusters: list[list[dict]], total: int) -> None:
    redundant = sum(len(g) - 1 for g in clusters)
    print("=" * 72)
    print(f"历史重复报告：{total} 行中发现 {len(clusters)} 个重复簇，"
          f"冗余 {redundant} 行（{redundant / total * 100:.1f}%）")
    print("=" * 72)
    for group in sorted(clusters, key=len, reverse=True)[:10]:
        keeper = pick_representative(group)
        print(f"\n簇大小 {len(group)}（保留权威 {keeper['score_authority']:.2f} 那条）：")
        for event in sorted(group, key=lambda e: -e["score_authority"]):
            mark = "保留" if event["id"] == keeper["id"] else "删除"
            print(f"  [{mark}] {event['importance_score']:.4f} "
                  f"{str(event['title_zh'])[:38]:<40} {event['source_names']}")
    if len(clusters) > 10:
        print(f"\n… 另有 {len(clusters) - 10} 个簇未展示")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="真正执行合并与删除（默认只干跑）")
    parser.add_argument("--report-only", action="store_true",
                        help="跳过 embedding 回填，只出重复报告")
    args = parser.parse_args()

    conn = storage.get_mysql_conn()
    try:
        if not args.report_only:
            backfill_embeddings(conn)

        events = load_all(conn)
        print(f"阶段二：对 {len(events)} 行做重复检测（cosine ≥ {COSINE_THRESHOLD}，"
              f"时间窗 {TIME_WINDOW_HOURS}h，向量 {EMBED_DIM} 维）\n")
        clusters = find_duplicate_clusters(events)
        print_report(clusters, len(events))

        if not clusters:
            print("没有发现重复，无需处理")
            return 0

        merged, deleted = merge_clusters(conn, clusters, args.apply,
                                         social_baseline(events))
        if args.apply:
            print(f"已执行：合并 {merged} 簇，删除 {deleted} 行")
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM news_events")
            print(f"表当前行数：{cursor.fetchone()[0]}")
            cursor.close()
        else:
            print(f"干跑：将合并 {merged} 簇、删除 {deleted} 行。"
                  f"确认无误后加 --apply 执行。")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
