#!/usr/bin/env python3
"""存量重算：把全库 importance_score 统一到当前七因子公式（2026-07-29）。

## 起因（实测数据，不是预防性重构）

给全库按当前公式反算一遍并和 `importance_score` 比对，结果是：

    新七因子公式吻合   402 行
    旧五因子公式吻合  1865 行
    两者都不吻合       907 行（中间版本的权重）
    合计              3174 行

也就是说 **87% 的库存事件的排序分是用已经废弃的公式算出来的**。广度（B）和
冲击力（I）这两个本期新增、合计占 30% 权重的因子，对这批行完全没有生效。
前端按 importance_score 排序，于是新旧公式的分被放在同一个列表里比大小——
这本身就是不可比的，本期"排序效果变好了吗"的业务测试如果不先修这个，测出来
的差异有很大一部分只是"哪些行碰巧被新公式重算过"。

## 三个阶段

A. **LLM 回填 breadth_level**（唯一花钱的一步）
   广度是"这件事波及多大范围"的语义判断，没有可靠规则能从标题反推。用关键词
   猜会造出比 NULL 更糟的东西——一个看起来有值、实际是瞎猜的分。所以宁可花钱。
   只标这一个枚举，不要摘要不要分级，prompt 极短。

B. **离线重算 score_punch**（不花钱）
   冲击力是纯计算：幅度从标题/短摘要正则提取，权威共振数 sources 里 authority≥4
   的家数。库里这两样都有，直接调 scoring.compute_punch。

C. **重算 importance_score**
   用 A/B 补齐后的因子列 + 当前权重。

**刻意不重算 T（时效）和 H（热度）**：这两个因子依赖"现在几点"和当时的社交
基准，离线重算会把所有历史事件的时效分刷成"很旧"，制造出一个本期改动之外的
新变化，让业务对比失去干净的对照。这里只修"公式版本不一致"这一件事。

## 幂等 / 可中断

A 阶段只处理 breadth_level IS NULL 的行，C 阶段是纯覆盖写。任何时候 Ctrl-C
或失败重跑都安全，已提交的批次不会重复计费。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import scoring, storage
from crawler.pipeline import get_openai_client
from crawler.timeutil import now_local

MODEL = os.environ.get("B9_BACKFILL_MODEL", "gpt-5.4")
BATCH = 25

BREADTH_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "breadth_level": {
                        "type": "string",
                        "enum": ["cross_market", "market_index", "sector",
                                 "multi_asset", "single_asset"],
                    },
                },
                "required": ["id", "breadth_level"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

BREADTH_PROMPT = """你在给财经新闻标注"影响广度"这一个字段，不做任何其他判断。

从下面五档里选一档，标准与生产 pipeline 完全一致：
- cross_market：跨市场级。同时波及股市与加密市场，或波及多个国家/地区的大盘
  （美联储决议、全球性关税、跨市场系统性风险）
- market_index：单一市场大盘级。影响一个国家/地区的整体指数
  （日经暴跌、纳指创新高、韩国交易所政策）
- sector：板块级。影响一个行业或赛道，不是整个大盘
  （AI 芯片股集体下跌、DeFi 协议监管、银行业新规）
- multi_asset：多资产级。明确波及若干个标的，但不构成一个板块
- single_asset：单一标的级。只关乎一家公司/一个币种

判断的是**事件本身的波及范围**，不是它有多重要、多轰动。一家公司的重大丑闻
再轰动也仍然是 single_asset。

对每条输入按 id 返回一个 breadth_level，不要遗漏任何一条。"""


# ── A：LLM 回填 breadth_level ────────────────────────────────────────

def backfill_breadth(conn) -> int:
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, title_zh, title_en, description_short_zh, news_type, market_scope
        FROM news_events
        WHERE breadth_level IS NULL
        ORDER BY FIELD(event_tier,'S','A','B','C','D'), date DESC
    """)
    rows = cur.fetchall()
    cur.close()
    print(f"[A] 待回填 breadth_level：{len(rows)} 条")
    if not rows:
        return 0

    client = get_openai_client()
    wcur = conn.cursor()
    done = 0
    total_batches = (len(rows) + BATCH - 1) // BATCH

    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        payload = [{
            "id": r["id"],
            "title": r.get("title_zh") or r.get("title_en") or "",
            "summary": (r.get("description_short_zh") or "")[:180],
            "news_type": r.get("news_type"),
            "market_scope": r.get("market_scope"),
        } for r in chunk]
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": BREADTH_PROMPT},
                          {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "breadth_backfill", "strict": True, "schema": BREADTH_SCHEMA}},
            )
            results = json.loads(resp.choices[0].message.content)["results"]
        except Exception as e:
            # 单批失败不影响其他批：脚本幂等，剩下的重跑补上。
            print(f"  [A] 批 {i//BATCH + 1}/{total_batches} 失败，跳过：{e}")
            continue

        for item in results:
            level = item.get("breadth_level")
            if level not in scoring.BREADTH_VALUES:
                continue
            wcur.execute(
                "UPDATE news_events SET breadth_level=%s, score_breadth=%s "
                "WHERE id=%s AND breadth_level IS NULL",
                (level, scoring.BREADTH_VALUES[level], item["id"]))
            done += wcur.rowcount
        conn.commit()
        print(f"  [A] 批 {i//BATCH + 1}/{total_batches} 已提交，累计 {done}")

    wcur.close()
    return done


# ── B + C：离线重算 punch 与总分 ─────────────────────────────────────

def _json_col(value, default):
    if not value:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def rescore(conn) -> int:
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, title_zh, title_en, description_short_zh, sources,
               breadth_level, score_market_impact, score_timeliness,
               score_hotness, score_authority, score_quality
        FROM news_events
        WHERE score_market_impact IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()
    print(f"[B/C] 待重算：{len(rows)} 条")

    wcur = conn.cursor()
    updated = 0
    for idx, r in enumerate(rows, 1):
        event = {
            "title_zh": r.get("title_zh"),
            "title_en": r.get("title_en"),
            "description_short_zh": r.get("description_short_zh"),
            "sources": _json_col(r.get("sources"), []),
            "breadth_level": r.get("breadth_level"),
        }
        punch = scoring.compute_punch(event)
        B = scoring.compute_breadth(event)

        M = r["score_market_impact"] or 0.0
        T = r["score_timeliness"] or 0.0
        H = r["score_hotness"] or 0.0
        A = r["score_authority"] or 0.0
        Q = r["score_quality"] or 0.0
        total = (scoring.W_IMPACT * M + scoring.W_BREADTH * B
                 + scoring.W_TIME * T + scoring.W_PUNCH * punch["score"]
                 + scoring.W_HOT * H + scoring.W_AUTH * A + scoring.W_QUAL * Q)

        wcur.execute("""
            UPDATE news_events
               SET score_breadth=%s, score_punch=%s, punch_magnitude_pct=%s,
                   importance_score=%s, scoring_version=%s
             WHERE id=%s
        """, (round(B, 4), round(punch["score"], 4), punch["magnitude_pct"],
              round(total, 4), scoring.SCORING_VERSION, r["id"]))
        updated += 1
        if idx % 500 == 0:
            conn.commit()
            print(f"  [B/C] {idx}/{len(rows)}")
    conn.commit()
    wcur.close()
    return updated


def main():
    conn = storage.get_mysql_conn()
    try:
        filled = backfill_breadth(conn)
        print(f"[A] 完成，回填 {filled} 条")
        n = rescore(conn)
        print(f"[B/C] 完成，重算 {n} 条 · {now_local().isoformat()}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
