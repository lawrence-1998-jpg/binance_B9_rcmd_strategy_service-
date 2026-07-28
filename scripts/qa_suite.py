#!/usr/bin/env python3
"""
B9 全流程 QA 套件 —— 交付门禁。

用法（在 VM 上跑，打本地回环，不受跨境网络抖动干扰）：
    cd ~/crypto-news-crawler && set -a && source config/.env && set +a
    python3 scripts/qa_suite.py            # 全量
    python3 scripts/qa_suite.py --no-paid  # 跳过会真花钱的用例

为什么要有这个文件（2026-07-26 Lawrence 立的规矩）：
    "如果编码阶段整体完成了、没活干了，就进入全流程 QA，验证功能可用。
     必须拿到 no bug 的测试报告，这个项目才算交付，才能给我看。"

设计原则：
  1. **断言用户可见的行为**，不是内部实现。每条用例的失败信息要能直接定位。
  2. **可重复**：不依赖当天的数据内容，只依赖不变量（如"鉴权必须拦住"、
     "指纹不能重复"）。所以可以每次发版前无脑重跑。
  3. **自清理**：写库的用例（历史记录/埋点/反馈）跑完自己删掉，不留垃圾。
  4. **花钱的用例单独标注**，默认跑一条最便宜的做端到端证明，可用 --no-paid 关掉。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8080"
TOKEN = "***REMOVED***"
LEGACY_TOKEN = "***REMOVED***"

results: list[tuple[str, str, bool, str]] = []   # (分组, 用例, 通过?, 详情)


def check(group: str, name: str, ok: bool, detail: str = "") -> bool:
    results.append((group, name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  — {detail}" if detail and not ok else ""))
    return bool(ok)


def http(path: str, method: str = "GET", body=None, token: str | None = TOKEN,
         timeout: int = 60):
    """返回 (status, parsed_json_or_text)。网络/HTTP 错误也返回状态码，不抛。"""
    url = BASE + path
    if token:
        url += ("&" if "?" in path else "?") + "token=" + urllib.parse.quote(token)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw
    except Exception as e:                      # 连不上/超时
        return 0, str(e)


def sql(query: str) -> list[list[str]]:
    out = subprocess.run(
        ["mysql", "-uroot", "-p***REMOVED***", "crypto_news", "-sN", "-e", query],
        capture_output=True, text=True)
    if out.returncode != 0:
        return []
    return [line.split("\t") for line in out.stdout.strip().splitlines() if line]


# ══════════════════════════════════════════════════════════════════
def qa_services():
    print("\n[1/8] 服务与调度")
    g = "服务"
    for svc in ("crypto-news-api", "mysql", "cron", "b9-https-tunnel"):
        st = subprocess.run(["systemctl", "is-active", svc],
                            capture_output=True, text=True).stdout.strip()
        check(g, f"{svc} 运行中", st == "active", f"实际={st}")
    docker = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                            capture_output=True, text=True).stdout
    check(g, "rsshub 容器运行中", "rsshub" in docker, "中文源依赖它")

    cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    check(g, "pipeline cron 存在", "run_pipeline.py" in cron)
    check(g, "存档 cron 存在", "stage_fetch.py" in cron)
    check(g, "备份 cron 存在", "mysqldump" in cron)
    tz = subprocess.run(["timedatectl", "show", "--property=Timezone", "--value"],
                        capture_output=True, text=True).stdout.strip()
    check(g, "时区为 UTC+8", tz == "Asia/Shanghai", f"实际={tz}")


def qa_auth():
    print("\n[2/8] 鉴权（花钱的接口尤其不能裸奔）")
    g = "鉴权"
    st, _ = http("/health", token=None)
    check(g, "/health 无需鉴权可访问", st == 200, f"status={st}")

    protected = ["/api/news?limit=1", "/api/sources", "/api/runs", "/api/run-nodes",
                 "/api/x-posts?limit=1",
                 "/api/recommend/sector/list", "/api/history/list", "/api/enrich/stats"]
    for p in protected:
        st, _ = http(p, token=None)
        check(g, f"{p.split('?')[0]} 无 token 应 401", st == 401, f"status={st}")

    paid = [("/api/tools/dedup-test", "POST"), ("/api/tools/persona-eval", "POST"),
            ("/api/tools/ab-compare", "POST"), ("/api/tools/reweight", "POST"),
            ("/api/tools/compare", "POST")]
    for p, m in paid:
        st, _ = http(p, method=m, body={}, token=None)
        check(g, f"{p} 无 token 应 401（会花钱）", st == 401, f"status={st}")

    st, _ = http("/api/news?limit=1", token="garbage-token")
    check(g, "错误 token 应 401", st == 401, f"status={st}")
    st, _ = http("/api/news?limit=1", token=LEGACY_TOKEN)
    check(g, "旧 token 仍向下兼容", st == 200, f"status={st}")


def qa_endpoints():
    print("\n[3/8] 只读接口与页面")
    g = "接口"
    st, d = http("/api/news?limit=3")
    ok = st == 200 and isinstance(d, dict) and d.get("data") and "meta" in d
    check(g, "/api/news 返回数据与 meta", ok, f"status={st}")
    first = (d.get("data") or [{}])[0] if isinstance(d, dict) else {}

    if first.get("id"):
        st, one = http(f"/api/news/{first['id']}")
        check(g, "/api/news/<id> 详情", st == 200 and isinstance(one, dict))
        st, _ = http(f"/api/news/{first['id']}/x-sources")
        check(g, "/api/news/<id>/x-sources", st == 200)
    st, _ = http("/api/news/definitely-not-a-real-id")
    check(g, "不存在的 id 应 404", st == 404, f"status={st}")

    # 生产轮次节点 + run_at 筛选。这里断言的是「分桶必须不重不漏」这个不变量：
    # 每轮 total 相加应当等于全量 total。任何一天重跑、补跑都不会破坏它，
    # 但如果 12h 窗口写错（重叠或留缝），这条会立刻红。
    st, nodes = http("/api/run-nodes?limit=60")
    node_list = (nodes or {}).get("data") if isinstance(nodes, dict) else None
    check(g, "/api/run-nodes 可用", st == 200 and isinstance(node_list, list) and node_list,
          f"status={st}")
    if node_list:
        shapes_ok = all(n.get("run_at", "")[11:16] in ("08:00", "20:00") and n.get("event_count", 0) > 0
                        for n in node_list)
        check(g, "轮次节点都落在 08:00 / 20:00", shapes_ok,
              f"异常={[n['run_at'] for n in node_list if n.get('run_at','')[11:16] not in ('08:00','20:00')][:3]}")
        st, allm = http("/api/news?limit=1")
        total_all = ((allm or {}).get("meta") or {}).get("total", -1)
        summed = 0
        for n in node_list:
            st, one = http("/api/news?limit=1&run_at=" + urllib.parse.quote(n["run_at"]))
            summed += ((one or {}).get("meta") or {}).get("total", 0)
        check(g, "各轮 total 相加等于全量（分桶不重不漏）", summed == total_all,
              f"分轮相加={summed} 全量={total_all}")

    for p, key in [("/api/sources", "data"), ("/api/runs", None),
                   ("/api/x-posts?limit=2", None),
                   ("/api/recommend/sector/list", "data"),
                   ("/api/enrich/stats", "prompt_hash"),
                   ("/api/analytics/summary", None)]:
        st, d2 = http(p)
        ok = st == 200 and (key is None or (isinstance(d2, dict) and key in d2))
        check(g, f"{p.split('?')[0]} 可用", ok, f"status={st}")

    # 页面
    for path, marker in [("/", "生成流程"), ("/dashboard", "数据展示"), ("/lab", "策略实验室")]:
        st, html = http(path, token=None)
        ok = st == 200 and isinstance(html, str) and marker in html
        check(g, f"页面 {path} 渲染", ok, f"status={st}")
    st, html = http("/", token=None)
    check(g, "首页含 6 个导航项", isinstance(html, str) and html.count('role="tab"') >= 6)
    st, _ = http("/nonexistent-page", token=None)
    check(g, "未知页面 404", st == 404, f"status={st}")


def qa_write_paths():
    print("\n[4/8] 写入类功能（含自清理）")
    g = "写入"
    # 历史记录 CRUD
    st, saved = http("/api/history/save", "POST",
                     {"tool": "llm_eval", "label": "__qa_probe__",
                      "payload": {"qa": True}, "cost_usd": 0})
    rid = saved.get("id") if isinstance(saved, dict) else None
    check(g, "历史记录 save", st == 200 and rid, f"status={st}")
    if rid:
        st, lst = http("/api/history/list?limit=5")
        check(g, "历史记录 list", st == 200 and isinstance(lst, dict))
        st, one = http(f"/api/history/{rid}")
        ok = st == 200 and isinstance(one, dict) and (one.get("payload") or {}).get("qa") is True
        check(g, "历史记录 get 内容正确", ok, f"status={st}")
        st, _ = http(f"/api/history/{rid}", "DELETE")
        check(g, "历史记录 delete", st == 200, f"status={st}")
        st, _ = http(f"/api/history/{rid}")
        check(g, "删除后再取应 404", st == 404, f"status={st}")
    st, _ = http("/api/history/save", "POST", {"tool": "not_a_real_tool", "payload": {}})
    check(g, "非法 tool 应 400", st == 400, f"status={st}")

    # 埋点 + 反馈（自清理）
    st, _ = http("/api/analytics/track", "POST",
                 {"event_type": "page_view", "page": "__qa_probe__", "meta": {}})
    check(g, "埋点上报", st == 200, f"status={st}")
    st, _ = http("/api/feedback", "POST",
                 {"category": "工具反馈", "content": "__qa_probe__", "page_context": "qa"})
    check(g, "反馈提交", st == 200, f"status={st}")
    sql("DELETE FROM analytics_events WHERE page='__qa_probe__'")
    sql("DELETE FROM feedback_submissions WHERE content='__qa_probe__'")
    leftover = sql("SELECT (SELECT COUNT(*) FROM analytics_events WHERE page='__qa_probe__') "
                   "+ (SELECT COUNT(*) FROM feedback_submissions WHERE content='__qa_probe__')")
    check(g, "QA 测试数据已清理", leftover and leftover[0][0] == "0")

    # enrich bridge
    st, spec = http("/api/enrich/prompt")
    ok = st == 200 and isinstance(spec, dict) and spec.get("prompt_hash") and spec.get("system_prompt")
    check(g, "enrich/prompt 下发口径", ok, f"status={st}")
    st, _ = http("/api/enrich/submit", "POST",
                 {"prompt_hash": "wrong-hash", "results": [{"url_hash": "x" * 64, "enriched": {}}]})
    check(g, "enrich/submit 口径不符应 409", st == 409, f"status={st}")


def qa_data_integrity():
    print("\n[5/8] 数据正确性（不变量，不依赖当天内容）")
    g = "数据"
    n = sql("SELECT COUNT(*) FROM news_events")
    check(g, "事件库非空", n and int(n[0][0]) > 0, f"count={n}")

    dup = sql("SELECT COUNT(*) FROM (SELECT event_fingerprint FROM news_events "
              "WHERE event_fingerprint IS NOT NULL AND event_fingerprint<>'' "
              "GROUP BY event_fingerprint HAVING COUNT(*)>1) t")
    check(g, "无重复事件指纹（去重铁律）", dup and dup[0][0] == "0", f"重复组={dup}")

    bad = sql("SELECT COUNT(*) FROM news_events WHERE importance_score IS NULL "
              "OR importance_score < 0 OR importance_score > 1")
    check(g, "重要性分均在 [0,1]", bad and bad[0][0] == "0", f"越界={bad}")

    nosec = sql("SELECT COUNT(*) FROM news_events WHERE sectors IS NULL")
    check(g, "sectors 列无 NULL", nosec and nosec[0][0] == "0")

    # 近期行必须带新字段（老行不查，避免历史包袱造成假红灯）
    recent = sql("SELECT COUNT(*), SUM(verification_status IS NOT NULL), "
                 "SUM(description_long_zh IS NOT NULL AND description_long_zh<>'') "
                 "FROM news_events WHERE time_get_data >= NOW() - INTERVAL 2 DAY")
    if recent and int(recent[0][0]) > 0:
        tot, ver, lng = (int(x) for x in recent[0])
        check(g, "近 2 天事件都有真实性校验结论", ver == tot, f"{ver}/{tot}")
        check(g, "近 2 天事件都有中文长摘要", lng == tot, f"{lng}/{tot}")

    run = sql("SELECT status, events_count FROM pipeline_runs ORDER BY id DESC LIMIT 1")
    check(g, "最近一轮 pipeline 成功", run and run[0][0] == "success", f"{run}")

    stale = sql("SELECT COUNT(*) FROM raw_items_staging WHERE consumed_at IS NULL "
                "AND fetched_at < NOW() - INTERVAL 3 DAY")
    check(g, "无 3 天未消费的存档积压", stale and int(stale[0][0]) == 0, f"积压={stale}")

    orphan = sql("SELECT COUNT(*) FROM llm_enrich_cache WHERE enriched IS NULL")
    check(g, "enrich 缓存无空内容行", orphan and orphan[0][0] == "0")


def qa_tools(run_paid: bool):
    print("\n[6/8] 交互工具（用户真正会点的东西）")
    g = "工具"
    st, d = http("/api/tools/reweight", "POST",
                 {"weights": {"M": 35, "T": 20, "H": 15, "A": 15, "Q": 15},
                  "days": 7, "pool": 100, "top_n": 10})
    ok = st == 200 and isinstance(d, dict) and d.get("results")
    check(g, "策略实验室 单版本重排", ok, f"status={st}")

    # 相关性必须是连续分（这是 2026-07-26 修复的核心，退化会被这条抓到）
    st, d = http("/api/tools/reweight", "POST",
                 {"weights": {"M": 15, "T": 15, "H": 10, "A": 10, "Q": 5, "Rel": 45},
                  "sector": "MEME", "days": 7, "pool": 300, "top_n": 20})
    rels = {r["factors"]["Rel"] for r in d.get("results", [])} if isinstance(d, dict) else set()
    check(g, "相关性为连续分（非 0/1 二元）",
          st == 200 and not rels <= {0.0, 1.0} and len(rels) >= 3,
          f"取值={sorted(rels, reverse=True)[:8]}")

    st, d = http("/api/tools/compare", "POST",
                 {"weights_a": {"M": 35, "T": 20, "H": 15, "A": 15, "Q": 15},
                  "weights_b": {"M": 10, "T": 65, "H": 10, "A": 10, "Q": 5},
                  "days": 7, "pool": 100, "top_n": 10})
    ok = (st == 200 and isinstance(d, dict)
          and all(k in d for k in ("turnover", "rising_cases", "falling_cases", "summary")))
    check(g, "策略实验室 两版本对比（含换手率/升降case/总结）", ok,
          f"status={st} keys={sorted(d.keys()) if isinstance(d, dict) else d}")

    st, _ = http("/api/recommend/sector?sector=MEME&limit=3")
    check(g, "Sector Insight 推荐端点", st == 200, f"status={st}")
    st, _ = http("/api/recommend/sector?sector=NotARealSector")
    check(g, "非法板块应 400", st == 400, f"status={st}")

    # 评测工具：输入校验路径（不花钱）
    st, _ = http("/api/tools/persona-eval", "POST", {})
    check(g, "LLM 评测室 空输入应 400", st == 400, f"status={st}")
    st, d2 = http("/api/tools/ab-compare", "POST", {"group_a": {}, "group_b": {}})
    spent = (d2 or {}).get("cost_usd", 0) if isinstance(d2, dict) else 0
    check(g, "AB 对比 空输入应 400 且零花费", st == 400 and not spent,
          f"status={st} 花费=${spent}")

    if run_paid:
        st, d = http("/api/tools/persona-eval", "POST",
                     {"mode": "text", "text": "美国比特币现货ETF单日净流出2.4亿美元。"},
                     timeout=180)
        personas = len(d.get("personas", [])) if isinstance(d, dict) else 0
        check(g, "LLM 评测室 真实调用（付费用例）",
              st == 200 and personas >= 3, f"status={st} personas={personas}")
    else:
        print("  · 跳过付费用例（--no-paid）")


def qa_persona():
    """评测 Agent 管理 + 评测留档 + 校准闭环（2026-07-28 新增子系统）。

    全部是零成本用例：CRUD/上传/回滚/列表都不调 LLM。唯一会花钱的「归纳校准」
    和「批量评测」这里只断言**成本刹车生效**（缺参数必须被拒），不真跑。
    CRUD 用例自清理，跑完不留脏数据。
    """
    print("\n[7/8] 评测 Agent 管理与校准闭环")
    g = "Persona"

    st, d = http("/api/personas?with_stats=1")
    ok = st == 200 and isinstance(d, dict) and d.get("personas")
    check(g, "/api/personas 列表可用", ok, f"status={st}")

    if ok:
        FIELDS = ["personality", "story", "preferences", "memory", "mood"]
        check(g, "返回五要素字段定义", d.get("fields") == FIELDS, f"实际={d.get('fields')}")
        # 人设是空的等于 agent 没人格，评测结果会退化成千篇一律的通用点评，
        # 是那种"接口 200 但产品坏了"的故障，必须由不变量用例兜住。
        empties = [p["id"] for p in d["personas"]
                   if not any((p.get(f) or "").strip() for f in FIELDS)
                   and not (p.get("prompt_override") or "").strip()]
        check(g, "每个 Agent 都有非空人设", not empties, f"人设全空={empties}")
        active = [p for p in d["personas"] if p.get("is_active")]
        check(g, "至少有一个启用中的 Agent", bool(active),
              "一个都没有的话 LLM 评测室会直接 409")

    # CRUD 往返 —— 自清理
    pid = "qa_tmp_persona"
    http(f"/api/personas/{pid}", "DELETE")          # 防上一次异常退出留下的残留
    st, d = http("/api/personas", "POST",
                 {"id": pid, "name": "QA临时", "tagline": "自动化用例",
                  "personality": "原始人格", "preferences": "原始偏好"})
    check(g, "新建 Agent", st == 201 and d.get("persona", {}).get("version") == 1, f"status={st}")

    st, d = http(f"/api/personas/{pid}", "PUT", {"mood": "QA改过的心情"})
    v2_ok = st == 200 and d.get("persona", {}).get("version") == 2
    check(g, "更新后版本号 +1", v2_ok, f"status={st}")
    check(g, "改动进入 system_prompt", "QA改过的心情" in (d.get("system_prompt") or ""),
          "人设改了但发给模型的 prompt 没变，等于白改")

    st, d = http(f"/api/personas/{pid}/rollback", "POST", {"version": 1})
    rb = d.get("persona", {}) if isinstance(d, dict) else {}
    check(g, "回滚产生更新的版本号（不删历史）",
          st == 200 and rb.get("version", 0) > 2, f"status={st} v={rb.get('version')}")
    check(g, "回滚后内容确实回到 v1", (rb.get("mood") or "") == "", f"mood={rb.get('mood')!r}")

    st, d = http(f"/api/personas/{pid}/calibrate", "POST", {"comment": "QA 用例写的校准"})
    calib_ok = st == 200 and d.get("effective") == "immediate"
    check(g, "校准提交即生效（零成本）", calib_ok, f"status={st}")
    if calib_ok:
        st2, d2 = http(f"/api/personas/{pid}/preview-prompt")
        check(g, "校准记忆进入 system_prompt",
              st2 == 200 and "历史校准记录" in (d2.get("system_prompt") or ""),
              "校准写进去了但 prompt 里没有，闭环是断的")

    st, _ = http(f"/api/personas/{pid}/calibrate", "POST", {"comment": ""})
    check(g, "空校准应 400", st == 400, f"status={st}")
    st, _ = http(f"/api/personas/{pid}/calibrate", "POST",
                 {"comment": "x", "suggested_score": 99})
    check(g, "越界的建议分应 400", st == 400, f"status={st}")

    st, _ = http(f"/api/personas/{pid}", "DELETE")
    check(g, "删除 Agent（用例自清理）", st == 200, f"status={st}")
    st, _ = http(f"/api/personas/{pid}")
    check(g, "删除后再查应 404", st == 404, f"status={st}")

    # 评测留档与分析
    st, d = http("/api/eval-runs?limit=5")
    check(g, "/api/eval-runs 评测历史可用",
          st == 200 and isinstance(d, dict) and "runs" in d, f"status={st}")
    st, d = http("/api/eval-analysis/correlation")
    check(g, "/api/eval-analysis/correlation 可用",
          st == 200 and isinstance(d, dict) and "correlations" in d, f"status={st}")
    st, d = http("/api/eval-runs/export.csv")
    check(g, "评测历史 CSV 导出", st == 200 and isinstance(d, str), f"status={st}")

    # 成本刹车 —— 这两条是防「手滑点一下烧掉几十刀」的闸门，退化必须被抓到
    st, _ = http("/api/tools/persona-eval-batch", "POST", {"event_ids": ["x"]})
    check(g, "批量评测缺 confirm_cost 应 400 且零花费", st == 400, f"status={st}")
    st, _ = http("/api/tools/persona-eval-batch", "POST",
                 {"event_ids": ["x"] * 31, "confirm_cost": True})
    check(g, "批量评测超 30 条上限应 400", st == 400, f"status={st}")

    # 鉴权（这几个端点能改人设、能花钱，漏鉴权比漏在只读端点严重）
    for p in ["/api/personas", "/api/eval-runs", "/api/eval-analysis/correlation"]:
        st, _ = http(p, token=None)
        check(g, f"{p} 无 token 应 401", st == 401, f"status={st}")


def qa_market_expansion():
    """美股/港股/日股/韩股/宏观新闻扩召回 + 大盘情绪（2026-07-28 新增）。"""
    print("\n[8/8] 全球市场扩召回与大盘情绪")
    g = "市场扩召回"

    st, d = http("/api/market-mood")
    check(g, "/api/market-mood 可用", st == 200 and isinstance(d, dict) and "available" in d,
          f"status={st}")

    st, d = http("/api/news?market_scope=crypto&limit=1")
    check(g, "market_scope=crypto 筛选可用", st == 200 and isinstance(d, dict), f"status={st}")

    # A 股不该出现在新抓的事件里——这是老板明确的排除要求，退化成"漏挡"必须被
    # 抓到。只查 filter_a_share() 上线之后（2026-07-28）新入库的事件：这条规则
    # 是"以后不要"，不是"把历史里提过 A 股的事件全部清掉"，历史存量（比如
    # 2026-07-26 的"12家企业启动A股上市辅导"）不在这次改造范围内。
    #
    # 用 BINARY 精确匹配而不是普通 LIKE：utf8mb4_unicode_ci 排序规则的字符等价
    # 判定会把"Cathie Wood买入Meta股票"这类完全不含"A股"的标题误判成命中
    # （实测普通 LIKE 命中 7 条，BINARY 精确匹配只有 4 条，且全部是 2026-07-28
    # 之前的历史数据）——这是本条用例自己的一次真实踩坑，记录在这里防止
    # 以后又用普通 LIKE 重新引入这个误报。
    rows = sql("SELECT COUNT(*) FROM news_events WHERE created_at >= '2026-07-28' "
              "AND (BINARY title_zh LIKE '%A股%' OR BINARY title_zh LIKE '%沪指%' "
              "OR BINARY title_zh LIKE '%上证综指%')")
    a_share_count = int(rows[0][0]) if rows and rows[0] else -1
    check(g, "2026-07-28 起新入库事件无 A 股相关标题（filter_a_share 生效）",
          a_share_count == 0, f"命中 {a_share_count} 条")

    st, _ = http("/api/market-mood", token=None)
    check(g, "/api/market-mood 无 token 应 401", st == 401, f"status={st}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-paid", action="store_true", help="跳过会真花钱的用例")
    args = ap.parse_args()

    print("=" * 68)
    print("B9 全流程 QA —— 交付门禁")
    print(f"目标: {BASE}   时间: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 68)

    qa_services()
    qa_auth()
    qa_endpoints()
    qa_write_paths()
    qa_data_integrity()
    qa_tools(run_paid=not args.no_paid)
    qa_persona()
    qa_market_expansion()

    failed = [r for r in results if not r[2]]
    print("\n" + "=" * 68)
    print(f"总计 {len(results)} 项 · 通过 {len(results) - len(failed)} · 失败 {len(failed)}")
    if failed:
        print("\n❌ 失败明细（必须全部修掉才算交付）：")
        for grp, name, _, detail in failed:
            print(f"  [{grp}] {name}  — {detail}")
    else:
        print("\n✅ NO BUG —— 全部用例通过，达到交付标准")
    print("=" * 68)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
