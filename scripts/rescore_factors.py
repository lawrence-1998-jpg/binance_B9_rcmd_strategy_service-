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

from crawler import scoring, storage, verification
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


def rescore(conn, dry_run: bool = False) -> tuple:
    """重算全库。dry_run=True 时只计算不写库，返回值第三项给出按新分排的
    首屏 Top20（供预演打印"会换血几条"）。返回 (总行数, 数值有变行数, top20ids)。"""
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, date, title_zh, title_en, description_short_zh, sources,
               breadth_level, score_market_impact, score_timeliness,
               score_hotness, score_authority, score_quality,
               importance_score AS old_importance,
               is_rumor, verification_status
        FROM news_events
        WHERE score_market_impact IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()
    print(f"[B/C] 待重算：{len(rows)} 条")

    from datetime import date as _date, timedelta as _td
    window_cut = _date.today() - _td(days=5)
    wcur = conn.cursor()
    updated = changed = 0
    window_scores = []          # (new_total, id) —— 预演/收尾都要算 Top20 换血
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
        new_total = round(total, 4)
        if abs((r.get("old_importance") or 0.0) - new_total) > 1e-4:
            changed += 1
        d = r.get("date")
        if d is not None and d >= window_cut:
            window_scores.append((new_total, r["id"]))

        if not dry_run:
            wcur.execute("""
                UPDATE news_events
                   SET score_breadth=%s, score_punch=%s, punch_magnitude_pct=%s,
                       score_authority=%s, importance_score=%s, scoring_version=%s
                 WHERE id=%s
            """, (round(B, 4), round(punch["score"], 4), punch["magnitude_pct"],
                  round(A, 4), new_total, scoring.SCORING_VERSION, r["id"]))
        updated += 1
        if idx % 500 == 0:
            if not dry_run:
                conn.commit()
            print(f"  [B/C] {idx}/{len(rows)}")
    if not dry_run:
        conn.commit()
    wcur.close()
    window_scores.sort(reverse=True)
    return updated, changed, [i for _, i in window_scores[:20]]


# ══════════════════════════════════════════════════════════════════════
# 全库改写三护栏（2026-07-30，Lawrence："不能再犯 把整个页面的库改乱 覆盖掉
# 这种恐怖事件了"）。当天这个脚本被裸跑了 4 次、每次覆盖全库 6800+ 行的
# importance_score——公式对就没事，公式错一次就是全库污染且无路可退。三道闸：
#
#   1) 先快照：写之前把要动的列备份进 rescore_backup（带批次号），
#      `--restore <批次号>` 一条命令整批还原。
#   2) 差异门：默认**预演**（与 purge_untrusted_stale.py 同一约定），打印
#      将改动的行数 + Top20 会换掉几条；看过再 --apply。
#   3) 互斥锁：pipeline 正在写库时拒绝跑——两个写者并发覆盖同一批行，
#      结果取决于毫秒级时序，事后无法解释。
# ══════════════════════════════════════════════════════════════════════

BACKUP_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rescore_backup (
  batch      VARCHAR(20) NOT NULL,
  id         VARCHAR(32) NOT NULL,
  score_breadth        FLOAT NULL,
  score_punch          FLOAT NULL,
  punch_magnitude_pct  FLOAT NULL,
  score_authority      FLOAT NULL,
  importance_score     FLOAT NULL,
  scoring_version      TINYINT UNSIGNED NULL,
  PRIMARY KEY (batch, id),
  KEY idx_batch (batch)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='rescore_factors 的写前快照，--restore <batch> 整批还原'
"""
# ↑ COLLATE 必须与 news_events 一致（utf8mb4_unicode_ci）：restore 的
#   JOIN ON b.id = e.id 在两表 collation 不一致时直接报 Illegal mix of
#   collations——首次往返测试当场撞上，不是理论风险。

_MUTATED_COLS = ("score_breadth", "score_punch", "punch_magnitude_pct",
                 "score_authority", "importance_score", "scoring_version")


def _pipeline_lock_held() -> bool:
    from pathlib import Path
    lock_path = Path(__file__).resolve().parent.parent / "logs" / "pipeline.lock"
    if not lock_path.exists():
        return False
    import fcntl
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        f.close()


def snapshot(conn, batch: str) -> int:
    cur = conn.cursor()
    cur.execute(BACKUP_TABLE_SQL)
    cols = ", ".join(_MUTATED_COLS)
    cur.execute(
        f"INSERT INTO rescore_backup (batch, id, {cols}) "
        f"SELECT %s, id, {cols} FROM news_events WHERE score_market_impact IS NOT NULL",
        (batch,))
    n = cur.rowcount
    conn.commit()
    cur.close()
    return n


def restore(conn, batch: str) -> int:
    cur = conn.cursor()
    sets = ", ".join(f"e.{c} = b.{c}" for c in _MUTATED_COLS)
    cur.execute(
        f"UPDATE news_events e JOIN rescore_backup b ON b.id = e.id AND b.batch = %s "
        f"SET {sets}", (batch,))
    n = cur.rowcount
    conn.commit()
    cur.close()
    return n


def top20_ids(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT id FROM news_events WHERE date >= CURDATE() - INTERVAL 5 DAY "
                "ORDER BY importance_score DESC LIMIT 20")
    ids = [r[0] for r in cur.fetchall()]
    cur.close()
    return ids


def main():
    import argparse
    parser = argparse.ArgumentParser(description="全库因子/总分重算（默认预演）")
    parser.add_argument("--apply", action="store_true",
                        help="真正写库（默认只预演：打印将改动的规模与 Top20 换血数）")
    parser.add_argument("--restore", metavar="BATCH",
                        help="按批次号从 rescore_backup 整批还原，然后退出")
    parser.add_argument("--skip-llm", action="store_true",
                        help="跳过 A 阶段的 LLM 回填（兼容旧用法，仅 B/C 离线重算）")
    parser.add_argument("--yes-i-know-pipeline-is-running", action="store_true",
                        help="无视 pipeline 互斥锁强行执行（仅限确知安全时）")
    args = parser.parse_args()

    conn = storage.get_mysql_conn()
    try:
        if args.restore:
            n = restore(conn, args.restore)
            print(f"[restore] 批次 {args.restore} 还原 {n} 行")
            return 0

        if _pipeline_lock_held() and not args.yes_i_know_pipeline_is_running:
            print("拒绝执行：pipeline 正在运行（logs/pipeline.lock 被持有）。"
                  "两个写者并发覆盖同一批行的结果不可解释。等它跑完，或确知安全时加 "
                  "--yes-i-know-pipeline-is-running。")
            return 2

        if not args.apply:
            # 预演：算但不写，报告规模与首屏影响
            before = top20_ids(conn)
            n, changed, new_top20 = rescore(conn, dry_run=True)
            swapped = len(set(before) - set(new_top20))
            print(f"[预演] 覆盖 {n} 行，其中数值有变化 {changed} 行；"
                  f"首屏 Top20 将换掉 {swapped}/20 条。")
            print("确认无误后加 --apply 执行（执行时自动快照，可 --restore 回滚）。")
            return 0

        batch = now_local().strftime("%Y%m%d%H%M%S")
        before = top20_ids(conn)
        snap_n = snapshot(conn, batch)
        print(f"[快照] 批次 {batch} 备份 {snap_n} 行 → rescore_backup")

        if not args.skip_llm:
            filled = backfill_breadth(conn)
            print(f"[A] 完成，回填 {filled} 条")
        n, changed, _ = rescore(conn, dry_run=False)
        after = top20_ids(conn)
        swapped = len(set(before) - set(after))
        print(f"[B/C] 完成，重算 {n} 条（数值变化 {changed}）· Top20 换血 {swapped}/20 "
              f"· 回滚：--restore {batch} · {now_local().isoformat()}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
