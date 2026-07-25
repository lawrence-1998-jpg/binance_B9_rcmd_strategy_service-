"""
策略实验室（Strategy Lab）— Tab 5 后端。独立 Flask Blueprint，只读数据库。

╔══════════════════════════════════════════════════════════════════════════╗
║ 接入方法 —— 需要在 api/server.py 里加两行（不要改动本文件之外的任何东西）：  ║
║                                                                            ║
║   1) 在文件顶部 import 区加：                                             ║
║        from api.lab_tools import lab_bp                                  ║
║                                                                            ║
║   2) 在所有路由定义之后、`if __name__ == "__main__":` 之前加：            ║
║        app.register_blueprint(lab_bp)                                    ║
║                                                                            ║
║ 加上这两行后，以下路由会自动生效：                                        ║
║   GET  /lab                     —— 策略实验室前端页面（web/lab.html）      ║
║   POST /api/tools/reweight      —— 单版本权重调节 + 实时重排              ║
║   POST /api/tools/compare       —— 两版本权重对比（换手率/升降 case/summary）║
╚══════════════════════════════════════════════════════════════════════════╝

设计原则：
  - 打分逻辑 100% 复用 crawler/scoring.py 里的 compute_impact / compute_timeliness /
    compute_hotness / compute_authority / compute_quality，不重新实现任何因子算法，
    只是把权重从写死的常量变成请求参数。
  - 相关性（Rel）因子：news_events 表里没有 sector_relevance 之类的字段（已用
    `DESCRIBE news_events` 核实），这里用退化方案 —— 用户选择的板块若命中事件
    的 sectors JSON 数组则记 1.0，否则 0.0（二元判断）。前端已明确标注这是
    简化版，完整版 Sector Insight 相关性算法尚未上线，这是已知技术债务，不是
    本模块要解决的范围。
  - 全程只 SELECT，不写 news_events 或任何表。
  - 不依赖 api/server.py 的任何内部函数（get_db/require_api_key 等），完全自
    包含，避免和同时在改 server.py 的另一个 agent产生耦合冲突。
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, request, jsonify, send_from_directory

from crawler import scoring, storage

# ─────────────────────────────────────────────────────────────────────────────
# 鉴权：与 api/server.py 里的 require_api_key 逻辑保持一致（同一个静态 token），
# 但独立实现，不 import server.py。
# ─────────────────────────────────────────────────────────────────────────────
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "***REMOVED***")


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not key:
            key = request.args.get("token", "")
        if key != API_SECRET_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

lab_bp = Blueprint("lab_tools", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# 前端页面（静态吐出，无需鉴权，与 index.html 的 /dashboard 同一模式）
# ─────────────────────────────────────────────────────────────────────────────
@lab_bp.route("/lab", methods=["GET"])
def lab_page():
    resp = send_from_directory(WEB_DIR, "lab.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# 数据拉取
# ─────────────────────────────────────────────────────────────────────────────
POOL_COLUMNS = """
    id, title_en, title_zh, date, time_event, time_get_data,
    sectors, coins, news_type, event_tier,
    score_market_impact, score_timeliness, score_hotness, score_authority, score_quality,
    importance_score, is_rumor, source_names, source_count, social_interactions,
    verification_status
"""

MAX_POOL_LIMIT = 500


def fetch_pool(conn, days: int, limit: int) -> list[dict]:
    """拉取近 N 天入库的事件，转成 scoring.py 各 compute_* 函数能直接吃的 dict。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT {POOL_COLUMNS} FROM news_events WHERE time_get_data >= %s "
        f"ORDER BY time_get_data DESC LIMIT %s",
        (since, limit),
    )
    cols = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    cursor.close()

    events = []
    for row in rows:
        d = dict(zip(cols, row))
        for f in ("sectors", "coins", "source_names"):
            v = d.get(f)
            if isinstance(v, str):
                try:
                    d[f] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    d[f] = []
            elif v is None:
                d[f] = []
        # scoring.compute_timeliness 要读 published_at；库里是 time_event（真实新闻时间），
        # 缺失时退化用 time_get_data（入库时间），比给 0.5 中性分更贴近真实新鲜度。
        published = d.get("time_event") or d.get("time_get_data")
        d["published_at"] = published.isoformat() if hasattr(published, "isoformat") else published
        for k in ("date", "time_event", "time_get_data"):
            v = d.get(k)
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        events.append(d)
    return events


# ─────────────────────────────────────────────────────────────────────────────
# 权重归一化 + 因子计算（复用 scoring.py，不重新发明）
# ─────────────────────────────────────────────────────────────────────────────
FACTOR_KEYS = ["M", "T", "H", "A", "Q", "Rel"]
FACTOR_NAME = {"M": "影响面", "T": "时效性", "H": "热度", "A": "权威性", "Q": "质量", "Rel": "相关性"}
DEFAULT_RAW_WEIGHTS = {"M": 0.35, "T": 0.20, "H": 0.15, "A": 0.15, "Q": 0.15, "Rel": 0.0}

REL_NOTE = (
    "当前为简化版相关性：选中板块命中事件 sectors 数组即记 1.0，否则记 0.0（二元判断）。"
    "完整版 Sector Insight 相关性算法（语义相关度、多板块加权等）尚未上线，这是已知的产品待办项，"
    "本工具如实标注，不假装存在一个精细的相关性模型。"
)


def normalize_weights(raw: dict, use_rel: bool) -> dict:
    """把用户输入的任意权重归一化成合计 1.0。用户不需要自己凑够 1.0。

    全 0 或非法输入时退化为参与因子间的等权，而不是报错——这是个探索工具，
    不该因为用户把滑块全拖到 0 就崩掉。
    """
    raw = raw or {}
    w = {}
    for k in FACTOR_KEYS:
        try:
            v = float(raw.get(k, DEFAULT_RAW_WEIGHTS[k]))
        except (TypeError, ValueError):
            v = DEFAULT_RAW_WEIGHTS[k]
        w[k] = max(0.0, v)
    if not use_rel:
        w["Rel"] = 0.0

    total = sum(w.values())
    if total <= 0:
        active = ["M", "T", "H", "A", "Q"] + (["Rel"] if use_rel else [])
        eq = 1.0 / len(active)
        return {k: (eq if k in active else 0.0) for k in FACTOR_KEYS}
    return {k: v / total for k, v in w.items()}


def compute_factors(event: dict, baseline: float, now: datetime, sector: str | None) -> dict:
    """五因子 + 可选 Rel，逐字段调用 scoring.py 的既有函数。"""
    factors = {
        "M": scoring.compute_impact(event),
        "T": scoring.compute_timeliness(event, now),
        "H": scoring.compute_hotness(event, baseline),
        "A": scoring.compute_authority(event),
        "Q": scoring.compute_quality(event),
    }
    if sector:
        factors["Rel"] = 1.0 if sector in (event.get("sectors") or []) else 0.0
    else:
        factors["Rel"] = 0.0
    return factors


def weighted_score(factors: dict, weights: dict) -> float:
    return sum(weights[k] * factors[k] for k in FACTOR_KEYS)


def source_class(source_names) -> str:
    """粗粒度信源分类，仅供 summary 里做规则统计用，不进打分。

    命名约定本身就带类型信息：X/ 前缀 = KOL 推文原声，"快讯" = 快讯类聚合信源，
    "公告" = 官方公告；三者都不是就归到"主流媒体/研究机构"一档。
    """
    names = source_names or []
    if any(str(n).startswith("X/") for n in names):
        return "social"
    if any("快讯" in str(n) for n in names):
        return "flash"
    if any("公告" in str(n) for n in names):
        return "official"
    return "media"


CLASS_LABEL = {
    "social": "社交媒体/KOL 来源",
    "flash": "快讯类信源",
    "official": "官方公告类信源",
    "media": "主流媒体/研究机构来源",
}


def event_card(e: dict, factors: dict | None = None, score: float | None = None,
                rank: int | None = None, prod_rank: int | None = None) -> dict:
    card = {
        "id": e["id"],
        "title_zh": e.get("title_zh"),
        "title_en": e.get("title_en"),
        "event_tier": e.get("event_tier"),
        "news_type": e.get("news_type"),
        "sectors": e.get("sectors"),
        "source_names": e.get("source_names"),
        "is_rumor": bool(e.get("is_rumor")),
        "verification_status": e.get("verification_status"),
        "importance_score": e.get("importance_score"),
    }
    if factors is not None:
        card["factors"] = {k: round(v, 4) for k, v in factors.items()}
    if score is not None:
        card["score"] = round(score, 4)
    if rank is not None:
        card["rank"] = rank
    if prod_rank is not None:
        card["production_rank"] = prod_rank
    return card


def rank_pool(events: list[dict], factors_by_id: dict, weights: dict):
    """按给定权重给整批事件打分排序，返回 [(event, factors, score), ...] 降序。"""
    scored = [(e, factors_by_id[e["id"]], weighted_score(factors_by_id[e["id"]], weights))
              for e in events]
    scored.sort(key=lambda x: -x[2])
    return scored


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/tools/reweight —— 单版本权重调节 + 实时重排
# ─────────────────────────────────────────────────────────────────────────────
@lab_bp.route("/api/tools/reweight", methods=["POST"])
@require_api_key
def reweight():
    body = request.get_json(force=True, silent=True) or {}
    days = max(1, int(body.get("days", 7)))
    pool_limit = min(int(body.get("pool_limit", 300)), MAX_POOL_LIMIT)
    sector = (body.get("sector") or None) or None
    weights_raw = body.get("weights", {})

    conn = storage.get_mysql_conn()
    try:
        events = fetch_pool(conn, days, pool_limit)
    finally:
        conn.close()

    top_n = min(int(body.get("top_n", 30)), max(1, len(events)))
    now = datetime.now(timezone.utc)
    baseline = scoring.social_baseline(events)
    use_rel = bool(sector)
    weights = normalize_weights(weights_raw, use_rel)

    factors_by_id = {e["id"]: compute_factors(e, baseline, now, sector) for e in events}
    scored = rank_pool(events, factors_by_id, weights)

    prod_order = sorted(events, key=lambda e: -(e.get("importance_score") or 0))
    prod_rank = {e["id"]: i + 1 for i, e in enumerate(prod_order)}

    results = []
    for rank, (e, factors, s) in enumerate(scored[:top_n], start=1):
        card = event_card(e, factors, s, rank, prod_rank.get(e["id"]))
        p_rank = prod_rank.get(e["id"])
        card["rank_delta"] = (p_rank - rank) if p_rank is not None else None
        results.append(card)

    return jsonify({
        "meta": {
            "pool_size": len(events),
            "days": days,
            "sector": sector,
            "rel_enabled": use_rel,
            "rel_note": REL_NOTE if use_rel else None,
            "weights_normalized": {k: round(v, 4) for k, v in weights.items()},
            "social_baseline": round(baseline, 1),
            "generated_at": now.isoformat(),
        },
        "results": results,
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/tools/compare —— 两版本对比：换手率 / 上升下降 case / 自动 summary
# ─────────────────────────────────────────────────────────────────────────────
@lab_bp.route("/api/tools/compare", methods=["POST"])
@require_api_key
def compare():
    body = request.get_json(force=True, silent=True) or {}
    days = max(1, int(body.get("days", 7)))
    pool_limit = min(int(body.get("pool_limit", 300)), MAX_POOL_LIMIT)
    sector = (body.get("sector") or None) or None
    weights_a_raw = body.get("weights_a", {})
    weights_b_raw = body.get("weights_b", {})
    label_a = str(body.get("label_a") or "版本 A")[:40]
    label_b = str(body.get("label_b") or "版本 B")[:40]

    conn = storage.get_mysql_conn()
    try:
        events = fetch_pool(conn, days, pool_limit)
    finally:
        conn.close()

    if not events:
        return jsonify({"error": "指定时间范围内没有事件数据"}), 200

    top_n = min(int(body.get("top_n", 20)), len(events))
    case_limit = min(int(body.get("case_limit", 8)), 30)

    now = datetime.now(timezone.utc)
    baseline = scoring.social_baseline(events)
    use_rel = bool(sector)
    weights_a = normalize_weights(weights_a_raw, use_rel)
    weights_b = normalize_weights(weights_b_raw, use_rel)

    # 因子只需算一次：M/T/H/A/Q/Rel 不依赖权重，权重只影响加权求和。
    factors_by_id = {e["id"]: compute_factors(e, baseline, now, sector) for e in events}
    event_by_id = {e["id"]: e for e in events}

    scored_a = rank_pool(events, factors_by_id, weights_a)
    scored_b = rank_pool(events, factors_by_id, weights_b)

    rank_a = {e["id"]: i + 1 for i, (e, _, _) in enumerate(scored_a)}
    rank_b = {e["id"]: i + 1 for i, (e, _, _) in enumerate(scored_b)}
    score_a = {e["id"]: s for e, _, s in scored_a}
    score_b = {e["id"]: s for e, _, s in scored_b}

    top_a_ids = [e["id"] for e, _, _ in scored_a[:top_n]]
    top_b_ids = [e["id"] for e, _, _ in scored_b[:top_n]]
    set_a, set_b = set(top_a_ids), set(top_b_ids)
    overlap = set_a & set_b
    turnover_rate = 1.0 - (len(overlap) / top_n if top_n else 0.0)

    only_in_a = [event_card(event_by_id[i], factors_by_id[i], score_a[i], rank_a[i], None)
                 for i in top_a_ids if i not in set_b]
    only_in_b = [event_card(event_by_id[i], factors_by_id[i], score_b[i], rank_b[i], None)
                 for i in top_b_ids if i not in set_a]

    # 排名变化 case：限定在"至少在其中一个版本里排得比较靠前"的范围内看，
    # 避免把两个都在第 280 名徘徊的无关紧要事件也算作显著变化。
    zone = max(top_n * 3, 60)
    deltas = []
    for eid in rank_a:
        ra, rb = rank_a[eid], rank_b[eid]
        if min(ra, rb) <= zone:
            deltas.append((eid, rb - ra))  # 正数 = 相对 B，在 A 里排名上升

    def _case(eid, delta):
        e = event_by_id[eid]
        c = event_card(e, factors_by_id[eid])
        c["rank_a"] = rank_a[eid]
        c["rank_b"] = rank_b[eid]
        c["score_a"] = round(score_a[eid], 4)
        c["score_b"] = round(score_b[eid], 4)
        c["delta"] = delta
        return c

    rising = sorted([d for d in deltas if d[1] > 0], key=lambda x: -x[1])[:case_limit]
    falling = sorted([d for d in deltas if d[1] < 0], key=lambda x: x[1])[:case_limit]
    rising_cases = [_case(eid, d) for eid, d in rising]
    falling_cases = [_case(eid, d) for eid, d in falling]

    summary = build_summary(
        events=event_by_id, rank_a=rank_a, rank_b=rank_b,
        weights_a=weights_a, weights_b=weights_b,
        turnover_rate=turnover_rate, top_n=top_n,
        label_a=label_a, label_b=label_b, sector=sector,
        rising_cases=rising_cases, falling_cases=falling_cases,
    )

    top_a_list = [event_card(event_by_id[i], factors_by_id[i], score_a[i], r + 1)
                  for r, i in enumerate(top_a_ids)]
    top_b_list = [event_card(event_by_id[i], factors_by_id[i], score_b[i], r + 1)
                  for r, i in enumerate(top_b_ids)]

    return jsonify({
        "meta": {
            "pool_size": len(events),
            "days": days,
            "sector": sector,
            "rel_enabled": use_rel,
            "rel_note": REL_NOTE if use_rel else None,
            "weights_a_normalized": {k: round(v, 4) for k, v in weights_a.items()},
            "weights_b_normalized": {k: round(v, 4) for k, v in weights_b.items()},
            "label_a": label_a, "label_b": label_b,
            "social_baseline": round(baseline, 1),
            "generated_at": now.isoformat(),
        },
        "top_a": top_a_list,
        "top_b": top_b_list,
        "turnover": {
            "top_n": top_n,
            "overlap_count": len(overlap),
            "turnover_rate": round(turnover_rate, 4),
            "only_in_a": only_in_a,
            "only_in_b": only_in_b,
        },
        "rising_cases": rising_cases,
        "falling_cases": falling_cases,
        "summary": summary,
    })


def build_summary(events, rank_a, rank_b, weights_a, weights_b, turnover_rate, top_n,
                   label_a, label_b, sector, rising_cases, falling_cases) -> str:
    """纯规则生成的对比总结，不调用任何 LLM。"""
    lines = []

    # 1) 权重差异最大的因子
    diffs = {k: weights_a.get(k, 0) - weights_b.get(k, 0) for k in FACTOR_KEYS}
    top_factor = max(diffs, key=lambda k: abs(diffs[k]))
    diff_val = diffs[top_factor]
    if abs(diff_val) >= 0.005:
        direction = "提高" if diff_val > 0 else "降低"
        lines.append(
            f"{label_a} 相较 {label_b}，「{FACTOR_NAME[top_factor]}」权重{direction}了 "
            f"{abs(diff_val) * 100:.0f} 个百分点"
            f"（{weights_b.get(top_factor, 0) * 100:.0f}% → {weights_a.get(top_factor, 0) * 100:.0f}%），"
            f"是本次对比里变化最大的因子。"
        )

    # 2) 换手率
    changed = round(turnover_rate * top_n)
    lines.append(f"Top{top_n} 换手率 {turnover_rate * 100:.0f}%：两版本 Top{top_n} 里约有 {changed} 条新闻不重合。")

    # 3) 按信源类型分组的平均排名变化（规则统计，不猜测语义）
    group_deltas = defaultdict(list)
    for eid in rank_a:
        cls = source_class(events[eid].get("source_names"))
        group_deltas[cls].append(rank_b[eid] - rank_a[eid])  # 正数：在 A 里排名相对上升
    group_avg = {c: sum(v) / len(v) for c, v in group_deltas.items() if v}
    ordered = sorted(group_avg.items(), key=lambda x: -x[1])
    if len(ordered) >= 2 and (ordered[0][1] - ordered[-1][1]) >= 1.0:
        best_c, best_v = ordered[0]
        worst_c, worst_v = ordered[-1]
        lines.append(
            f"{CLASS_LABEL.get(best_c, best_c)}平均排名"
            f"{'上升' if best_v >= 0 else '下降'} {abs(best_v):.1f} 位，"
            f"{CLASS_LABEL.get(worst_c, worst_c)}平均"
            f"{'上升' if worst_v >= 0 else '下降'} {abs(worst_v):.1f} 位。"
        )

    # 4) 相关性因子说明（如果启用了）
    if sector and (weights_a.get("Rel", 0) > 0 or weights_b.get("Rel", 0) > 0):
        lines.append(
            f"已启用「{sector}」板块相关性因子（简化版：命中记 1.0，否则 0.0）；"
            f"完整版 Sector Insight 相关性算法尚未上线。"
        )

    # 5) 举例佐证（最多各举 1 条，具体列表见 rising_cases/falling_cases）
    if rising_cases:
        c = rising_cases[0]
        title = c.get("title_zh") or c.get("title_en") or c["id"]
        lines.append(f"上升幅度最大：《{title}》从第 {c['rank_b']} 名升至第 {c['rank_a']} 名。")
    if falling_cases:
        c = falling_cases[0]
        title = c.get("title_zh") or c.get("title_en") or c["id"]
        lines.append(f"下降幅度最大：《{title}》从第 {c['rank_b']} 名降至第 {c['rank_a']} 名。")

    return " ".join(lines) if lines else "两版本权重差异极小，排序基本没有变化。"
