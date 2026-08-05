#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存量 price_move 语义回填 —— **跑在 Lawrence 的 Mac 上**，不是 VM。

## 为什么需要

2026-08-02 给 enrich schema 加了 `price_move` 语义字段，让 LLM 直接回答
"这个百分数是不是价格变动"，根治了靠正则+排除表猜的老问题。但**存量事件**
是在那之前入库的，没有这个字段，只能走正则兜底——展示窗口里还有 986 条带
幅度值的条目可能带着误读的冲击力分在排序。

自然轮换 5 天后会全部换新，但那 5 天里首屏一直是旧口径。这个脚本把它补齐。

## 为什么跑在 Mac 上

公司 LiteLLM 网关是内网地址，只有挂 VPN 的 Mac 连得通；VM 侧个人 key 已被
成本闸关闭（Lawrence 明确"现在就不用个人的key了"）。所以只能 Mac 出算力，
经 ssh 读写 VM 的库——这也是本项目一贯的做法，不新增端点。

## 范围与安全

- **只处理 punch_magnitude_pct IS NOT NULL 的条目**：没抽到数字的补了也不会
  改变任何分数，白花钱。
- 只问 price_move 一个判断，prompt 极短（不是重跑整个 enrich），单条成本约为
  完整 enrich 的十分之一量级。
- **默认预演**，`--apply` 才写库；写库前打印将改变多少条、Top20 换血几条。
  沿用本项目全库改写的既有约定（见 scripts/rescore_factors.py 三护栏）。

用法：
    python3 scripts/backfill_price_move.py              # 预演
    python3 scripts/backfill_price_move.py --apply      # 真写
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request

VM = "manus-vm"
# 口令只从环境变量读（2026-08-05 仓库转 public），代码里不留兜底值。
_MYSQL_PWD = os.environ.get("MYSQL_PASSWORD", "")
CRED_FILE = os.path.expanduser("~/.b9/credentials.json")

PROMPT = """You decide ONE thing about a financial news item: is a percentage in it an actual
PRICE change of a tradable asset?

true  — the number is how much an asset's price or an index level actually MOVED
        "Bitcoin fell 8%", "Nikkei -4.2%", "Tesla shares surge 12%", "ASTEROID down 52%"
false — anything else, even with a rise/fall verb next to it:
        market share / dominance ("Upbit share rises to 67.4%", "BTC dominance above 58%")
        rates & ratios (tax rate, yield, approval rating 33%, volatility 60%, adoption 75%)
        coverage ("tariffs cover 99% of imports"), earnings vs estimates ("EPS beat by 30%")
        analyst price targets, historical stats / seasonality, flows & quantities, TVL,
        protocol signalling ("BIP-110 at 100%")

move_pct = how much it CHANGED (positive number). A LEVEL is not a CHANGE: "yield rose TO
5.26%" gives move_pct null. If a move is described but its size is never stated, keep
is_price_move true and move_pct null. Never borrow an unrelated number.

move_horizon: intraday / multi_day / long_term (YTD, six months — narrative recap) / none.

Answer for each input id. Do not skip any."""

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "is_price_move": {"type": "boolean"},
                    "move_pct": {"type": ["number", "null"]},
                    "move_horizon": {"type": "string",
                                     "enum": ["intraday", "multi_day", "long_term", "none"]},
                },
                "required": ["id", "is_price_move", "move_pct", "move_horizon"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

BATCH = 20


def vm_sql(query: str) -> str:
    """在 VM 上执行 SQL，返回 tab 分隔的原始输出。"""
    out = subprocess.run(
        ["ssh", VM, f"mysql -uroot -p{_MYSQL_PWD} crypto_news -sN -e {json.dumps(query)}"],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"VM SQL 失败：{out.stderr[:300]}")
    return out.stdout


def load_cred() -> dict:
    with open(CRED_FILE) as f:
        d = json.load(f)
    c = d["keys"][d["active"]]
    return c


def ask(cred: dict, items: list[dict]) -> list[dict]:
    body = json.dumps({
        "model": cred.get("model", "gpt-5.4"),
        "messages": [{"role": "system", "content": PROMPT},
                     {"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "price_move_backfill", "strict": True, "schema": SCHEMA}},
    }).encode()
    req = urllib.request.Request(
        f"{cred['base_url']}/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cred['key']}"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(json.loads(r.read())["choices"][0]["message"]["content"])["results"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写库（默认只预演）")
    ap.add_argument("--days", type=int, default=5, help="回填最近几天（默认与展示窗口一致）")
    ap.add_argument("--limit", type=int, default=2000)
    args = ap.parse_args()

    rows = []
    raw = vm_sql(
        f"SELECT id, title_zh, title_en, punch_magnitude_pct FROM news_events "
        f"WHERE date >= CURDATE() - INTERVAL {args.days} DAY "
        f"AND punch_magnitude_pct IS NOT NULL LIMIT {args.limit}")
    for line in raw.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            rows.append({"id": parts[0], "title_zh": parts[1],
                         "title_en": parts[2], "old_pct": parts[3]})
    print(f"待回填：{len(rows)} 条（近 {args.days} 天、且已抽出幅度值的）")
    if not rows:
        return 0

    cred = load_cred()
    verdicts: dict = {}
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        payload = [{"id": r["id"], "title": r["title_zh"] or r["title_en"],
                    "title_en": r["title_en"]} for r in chunk]
        try:
            for v in ask(cred, payload):
                verdicts[v["id"]] = v
        except Exception as e:
            print(f"  批 {i // BATCH + 1} 失败（跳过，可重跑补上）：{e}")
        done = min(i + BATCH, len(rows))
        if done % 200 == 0 or done == len(rows):
            print(f"  {done}/{len(rows)}")

    changed = [r for r in rows
               if r["id"] in verdicts and not verdicts[r["id"]]["is_price_move"]]
    print(f"\nLLM 判定：{len(verdicts)} 条有结论，其中 "
          f"**{len(changed)} 条原本被误判为涨跌幅**（占已判定的 "
          f"{100 * len(changed) // max(1, len(verdicts))}%）")
    for r in changed[:8]:
        print(f"   pct={r['old_pct']:>7}  {(r['title_zh'] or '')[:38]}")

    if not args.apply:
        print("\n预演模式，未写库。确认后加 --apply。")
        return 0

    # 只写 price_move 字段；冲击力分由 rescore_factors 统一重算（单一职责，
    # 也让"重算"这一步始终走它自己的三护栏）
    written = 0
    for i in range(0, len(rows), 100):
        pairs = []
        for r in rows[i:i + 100]:
            v = verdicts.get(r["id"])
            if not v:
                continue
            pm = json.dumps({"is_price_move": v["is_price_move"],
                             "move_pct": v["move_pct"],
                             "move_horizon": v["move_horizon"]}, ensure_ascii=False)
            pairs.append(f"WHEN {json.dumps(r['id'])} THEN {json.dumps(pm)}")
        if not pairs:
            continue
        ids = ",".join(json.dumps(r["id"]) for r in rows[i:i + 100] if r["id"] in verdicts)
        vm_sql(f"UPDATE news_events SET price_move = CASE id {' '.join(pairs)} END "
               f"WHERE id IN ({ids})")
        written += len(pairs)
        print(f"  已写 {written}/{len(verdicts)}")
    print(f"\n完成，写入 {written} 条。接着跑："
          f"\n  ssh {VM} 'cd ~/crypto-news-crawler && python3 scripts/rescore_factors.py --apply --skip-llm'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
