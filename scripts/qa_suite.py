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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crawler import scoring  # noqa: E402  （用它的 SCORING_VERSION 常量，不重复定义一份）

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


def _days_ago_str(n: int) -> str:
    """n 天前的 YYYY-MM-DD，给时效用例做边界比较用。"""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - n * 86400))


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
        # 用 max_age_days=0 关掉展示层时效闸再比：分轮查询带 run_at 时本来就
        # 绕过那道闸（见 server.py 的说明），全量这边不关就是拿"7天内"和
        # "所有轮次"相比，必然对不上——这条用例要验的是**分桶不重不漏**，
        # 不是时效策略，两者不能混在一个断言里。
        st, allm = http("/api/news?limit=1&max_age_days=0")
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

    # ── 排序策略基线配置（2026-07-30）───────────────────────────────
    # 表：strategy_config（migration 016），端点在 api/lab_tools.py，校验在
    # api/strategy_config.py。这组断言的重点是**写路径的严格性**——一份坏配置
    # 被置为 active 的影响面是全站默认，所以非法载荷必须被 400 挡住而不是
    # 静默夹紧；读路径的宽松兜底（表坏了退默认值）由「GET 必须 200 且含
    # config」间接覆盖（兜底失败会直接 500）。
    st, d = http("/api/strategy-config")
    ok = st == 200 and isinstance(d, dict) and "config" in d and "versions" in d
    check(g, "基线配置 GET 可用且含 config/versions", ok, f"status={st}")
    active_ver = (d.get("config") or {}).get("_version") if isinstance(d, dict) else None
    check(g, "基线配置有生效版本（种子迁移已跑）",
          isinstance(active_ver, int) and active_ver >= 1, f"_version={active_ver}")
    st, _d = http("/api/strategy-config", "POST",
                  {"config": {"base_weights": {"M": 30, "B": 16, "T": 16, "I": 14,
                                               "H": 10, "A": 10, "Q": 8, "XX": 5}}})
    check(g, "基线配置：未知因子应 400", st == 400, f"status={st}")
    st, _d = http("/api/strategy-config", "POST",
                  {"config": {"market_weights": {"us_stock": 5.0}}})
    check(g, "基线配置：市场权重越界应 400", st == 400, f"status={st}")
    st, _d = http("/api/strategy-config", "POST",
                  {"config": {"bonus": {"k_align": 0.4, "k_reversal": 0.3, "cap": 0.5}}})
    check(g, "基线配置：加分项超封顶应 400", st == 400, f"status={st}")
    st, _d = http("/api/strategy-config/rollback", "POST", {"version": 999999})
    check(g, "基线配置：回滚到不存在版本应 400", st == 400, f"status={st}")
    # 实验室与生产必须用同一根时间轴取数（2026-07-30 回填事故的直接教训：
    # 实验室按入库时间取池、生产按事件日期过滤，一次历史回填就让实验室首屏
    # 变成单一信源的旧闻）。这里断言 reweight 默认池里最新事件不早于昨天——
    # pipeline 每小时都在产出，池子里连 24 小时内的事件都没有只能是取数轴错了。
    st, d = http("/api/tools/reweight", "POST",
                 {"weights": {"M": 26, "B": 16, "T": 16, "I": 14, "H": 10, "A": 10, "Q": 8},
                  "days": 7, "pool": 100, "top_n": 10})
    newest = ""
    if isinstance(d, dict):
        for r in d.get("results", []):
            t = (r.get("time_event") or r.get("date") or "")[:10]
            newest = max(newest, t)
    from datetime import date as _date, timedelta as _td
    check(g, "实验室池子含近24小时事件（取数轴与生产一致）",
          st == 200 and newest >= (_date.today() - _td(days=1)).isoformat(),
          f"最新事件日期={newest or '无'}")

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
    # 2026-07-29 两处扩口径，都是这条用例漏掉真问题之后补的：
    #  1) 原来只查"上证综指"这类**全称**，于是「亚太股市重挫 上证失守3800」
    #     一路过闸，还在策略实验室排到了第 1 名。财经标题里指数名几乎总是简写，
    #     按全称匹配等于没匹配。改成查裸词（上证/深证/沪深/创业板指…）。
    #  2) 原来只查 created_at >= '2026-07-28'（"这条规则是以后不要"）。存量已在
    #     同日清干净，红线改成覆盖**整个 7 天展示窗口**——用户看到的是窗口里的
    #     全部内容，"历史存量不在范围内"这个借口对着屏幕讲不通。
    # BINARY 精确匹配保留：utf8mb4_unicode_ci 会把"Meta股票"判成命中"a股"。
    rows = sql("SELECT COUNT(*) FROM news_events "
              "WHERE date >= CURDATE() - INTERVAL 7 DAY "
              "AND (BINARY title_zh REGEXP '(^|[^A-Za-z])A股' "
              "OR BINARY title_zh LIKE '%沪指%' OR BINARY title_zh LIKE '%沪深%' "
              "OR BINARY title_zh LIKE '%上证%' OR BINARY title_zh LIKE '%深证%' "
              "OR BINARY title_zh LIKE '%深成指%' OR BINARY title_zh LIKE '%创业板%' "
              "OR BINARY title_zh LIKE '%科创板%' OR BINARY title_zh LIKE '%科创50%' "
              "OR BINARY title_zh LIKE '%北证50%' OR BINARY title_zh LIKE '%北交所%' "
              "OR BINARY title_zh LIKE '%上交所%' OR BINARY title_zh LIKE '%深交所%' "
              "OR market_scope = 'cn_a_share')")
    a_share_count = int(rows[0][0]) if rows and rows[0] else -1
    check(g, "7 天展示窗口内无 A 股相关标题（filter_a_share 生效）",
          a_share_count == 0, f"命中 {a_share_count} 条")

    st, _ = http("/api/market-mood", token=None)
    check(g, "/api/market-mood 无 token 应 401", st == 401, f"status={st}")

    # ── 打分口径一致性（2026-07-29 事故后新增的红线用例）───────────────
    #
    # 事故：改完排序公式之后顺手反算了一遍全库，发现 3174 行里只有 402 行（13%）
    # 的 importance_score 是按当时的现行七因子公式算的，其余是旧五因子或某个
    # 中间版本——公式改了三次，老行从来没有重算过。这个故障在构造上是隐形的：
    # 错的分仍然是 [0,1] 的浮点数，仍然能排序，页面照常渲染，不报错不告警。
    # 靠人是发现不了的，必须是一条能拦截发布的断言。
    #
    # 断言本身很直接：scoring_version 落后于 crawler/scoring.SCORING_VERSION
    # 的行，就是没有按当前公式重算过的行，数量必须是 0。这条红了，说明要么
    # 是刚改过公式但忘了跑 scripts/rescore_factors.py，要么是 write_events 的
    # UPSERT 漏刷了 scoring_version（历史上 score_breadth 就漏刷过一次）。
    g3 = "打分口径"
    rows = sql("SELECT COUNT(*) FROM news_events "
              f"WHERE scoring_version < {scoring.SCORING_VERSION} "
              "AND score_market_impact IS NOT NULL")
    stale_formula_n = int(rows[0][0]) if rows and rows[0] else -1
    check(g3, f"库内无打分版本落后于当前公式(v{scoring.SCORING_VERSION})的行",
          stale_formula_n == 0, f"命中 {stale_formula_n} 条 —— 需要跑 scripts/rescore_factors.py")

    # 光有版本号还不够——版本号本身可能被错误地标高（比如 migration 里手滑
    # 标了 2 但其实没跑重算）。所以再核对一遍**数值真的对得上**当前公式，
    # 抽样而不是全量（全库逐行算一遍对 QA gate 来说太重，抽样已经够暴露"标记
    # 与实际不符"这类问题）。
    rows = sql("""
        SELECT COUNT(*) FROM (
          SELECT importance_score,
                 ROUND(0.26*score_market_impact + 0.16*score_breadth + 0.16*score_timeliness
                     + 0.14*score_punch + 0.10*score_hotness + 0.10*score_authority
                     + 0.08*score_quality, 3) AS recalculated
          FROM news_events
          WHERE scoring_version = {v} AND score_market_impact IS NOT NULL
          ORDER BY updated_at DESC LIMIT 300
        ) t
        WHERE ABS(importance_score - recalculated) > 0.01
    """.format(v=scoring.SCORING_VERSION))
    mismatch_n = int(rows[0][0]) if rows and rows[0] else -1
    check(g3, f"抽样 300 条：标记为 v{scoring.SCORING_VERSION} 的行分数与当前公式吻合",
          mismatch_n == 0, f"不吻合 {mismatch_n}/300 条 —— 权重可能改了但版本号没跟着变")

    # ── 时效性（2026-07-29 线上事故后新增的红线用例）─────────────────
    #
    # 事故：一条 2024-08-21 的币安广场帖（DOGS 第 57 期 Launchpool）以
    # date=2026-07-26 的身份进了事件库并在前端展示。根因是 ddgs 搜索没有日期，
    # 而 normalize_published_at 把"无日期"回落成"当前时间"，等于伪造新鲜度。
    # 下面三条是防复发的红线，任何一条红都说明时效防线破了。
    g2 = "时效"
    st, d = http("/api/news?limit=100")
    rows = (d or {}).get("data") or [] if isinstance(d, dict) else []
    check(g2, "/api/news 默认只返回近 7 天内容", bool(rows) and all(
        (r.get("date") or "")[:10] >= _days_ago_str(8) for r in rows),
        f"最旧={min((r.get('date') or '') for r in rows) if rows else 'N/A'}")

    rows_db = sql("SELECT COUNT(*) FROM news_events WHERE DATEDIFF(time_get_data, date) > 7")
    stale_n = int(rows_db[0][0]) if rows_db and rows_db[0] else -1
    check(g2, "库内无「事件日期比采集早 7 天以上」的行", stale_n == 0, f"命中 {stale_n} 条")

    # 无日期来源不得再进库：BinanceSquare 走 ddgs 搜索、结构性拿不到发布时间，
    # 已默认关闭；库里若再次出现它的条目，说明开关被误开或又引入了同类无日期源。
    rows_bs = sql("SELECT COUNT(*) FROM news_events "
                 "WHERE JSON_SEARCH(source_names,'one','BinanceSquare') IS NOT NULL")
    bs_n = int(rows_bs[0][0]) if rows_bs and rows_bs[0] else -1
    check(g2, "库内无 BinanceSquare（无发布时间的搜索源）条目", bs_n == 0, f"命中 {bs_n} 条")

    # ── 信源时间可信度（2026-07-29 数字税旧闻事故后新增的红线）─────────
    #
    # 事故：一条 6/27 的旧闻以 A 档、日期 2026-07-28 进库并展示，差整整一个月。
    # 根因是搜索聚合器（Google News）给的 published_at 是它重新分发的时间，
    # 而这类条目没有正文，导致 LLM 后的 filter_by_event_date 兜底闸拿不到
    # 材料去纠正——两道防线同时失效。详见 crawler/source_trust.py。
    #
    # 同一批清理里还抓到第二种失败模式：S 档"韩股据报暴跌33%"（实际当天
    # KOSPI 跌 10.84%，那个 33% 是把 7 月累计跌幅当成单日崩盘）——同样是
    # "只有标题没有正文，LLM 把有歧义的数字读错"。
    g4 = "信源可信度"
    # 判定必须是「**全部**信源都是聚合器」，不是「任一信源是聚合器」——这条断言
    # 第一版写成了后者，立刻误报了 3 条：它们都是同一篇文章被直连 RSS/爬虫和
    # Google News 各收了一次（PANews 爬虫版 + PANews 搜索版这种），直连那一份
    # 带着可信时间戳，正是设计上要保留的。口径必须和 purge_untrusted_stale.py /
    # source_trust.event_sources_all_aggregated 完全一致，否则 QA 会永远红。
    #
    # 另外 JSON_SEARCH 必须用 '$[*].type' 限定只查 type 字段：不限定的话，
    # 任何 name/url 里恰好含 "rss" 的信源都会被误匹配（Google News 的 url 里
    # 就带 /rss/articles/，是个必然踩中的坑）。
    _NON_AGG = ("rss", "scraper", "social", "calendar", "market_signal", "dxfeed", "benzinga")
    _no_direct = " AND ".join(
        f"JSON_SEARCH(sources,'one','{t}',NULL,'$[*].type') IS NULL" for t in _NON_AGG)
    rows = sql("SELECT COUNT(*) FROM news_events "
              "WHERE date >= CURDATE() - INTERVAL 30 DAY AND source_count = 1 "
              "AND JSON_SEARCH(sources,'one','web_search',NULL,'$[*].type') IS NOT NULL "
              f"AND {_no_direct}")
    orphan_n = int(rows[0][0]) if rows and rows[0] else -1
    check(g4, "库内无「聚合器孤证」事件（单一信源且全部来自搜索聚合，真实发布时间不可验证）",
          orphan_n == 0, f"命中 {orphan_n} 条 —— 需要跑 scripts/purge_untrusted_stale.py")

    # 展示窗口收紧到 5 天后，接口与库两侧口径必须一致
    rows = sql("SELECT COUNT(*) FROM news_events "
              "WHERE date < CURDATE() - INTERVAL 5 DAY AND date >= CURDATE() - INTERVAL 7 DAY "
              "AND event_tier IN ('S','A')")
    stale_sa = int(rows[0][0]) if rows and rows[0] else -1
    # 这条不是硬失败：5-7 天之间的 S/A 档留在库里是允许的（历史分析要用），
    # 只是**不能出现在默认接口结果里**。下面直接查接口验证。
    # ── 市场重要性权重（PRD-04，2026-07-29）─────────────────────────
    #
    # 起因：tier 由 LLM 相对"事件自己所在的市场"判定，但排序是全局的——实测
    # 韩股 S 档率 13.6%、美股 0.15%（差 90 倍），而韩股供给量只有美股的 1/15，
    # 结果小市场的本地大新闻长期霸占首屏（用户原话"韩国的都排在了上面"）。
    g5 = "市场重要性"
    st, d = http("/api/news?limit=20")
    rows_mk = (d or {}).get("data") or [] if isinstance(d, dict) else []
    kr_top20 = sum(1 for r in rows_mk
                   if (r.get("market") or {}).get("market_scope") == "kr_stock")
    check(g5, "首屏 Top20 里 kr_stock 不超过 2 条",
          bool(rows_mk) and kr_top20 <= 2, f"命中 {kr_top20} 条")

    # 每条都要带 market 明细——前端展开区和排序都依赖它，缺了会静默退化成
    # "所有市场一视同仁"而没有任何报错
    missing_mk = sum(1 for r in rows_mk if not (r.get("market") or {}).get("multiplier"))
    check(g5, "/api/news 每条都带 market 倍率明细",
          bool(rows_mk) and missing_mk == 0, f"缺失 {missing_mk} 条")

    st, d = http("/api/news?limit=100")
    rows_api = (d or {}).get("data") or [] if isinstance(d, dict) else []
    check(g4, "/api/news 默认窗口已收紧到 5 天",
          bool(rows_api) and all((r.get("date") or "")[:10] >= _days_ago_str(6) for r in rows_api),
          f"库内5-7天S/A={stale_sa}（允许），接口最旧="
          f"{min((r.get('date') or '') for r in rows_api) if rows_api else 'N/A'}")


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
