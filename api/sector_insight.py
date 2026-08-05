"""
Sector Insight API —— 板块相关性推荐。独立 Flask Blueprint，只读数据库
（打分逻辑本身会调用 OpenAI，但不写 news_events 或任何表）。

╔══════════════════════════════════════════════════════════════════════════╗
║ 接入方法 —— 需要在 api/server.py 里加两行（不要改动本文件之外的任何东西，   ║
║ 也不要自己去改 server.py——按用户要求，server.py 的改动由统一的后续步骤处理）║
║                                                                            ║
║   1) 在文件顶部，`from lab_tools import lab_bp` 那两行 import 旁边加：     ║
║        from sector_insight import sector_insight_bp                      ║
║                                                                            ║
║   2) 在 `app.register_blueprint(lab_bp)` / `app.register_blueprint        ║
║      (eval_bp)` 那两行旁边加：                                            ║
║        app.register_blueprint(sector_insight_bp)                         ║
║                                                                            ║
║ 加上这两行后，以下路由自动生效：                                          ║
║   GET /api/recommend/sector?sector=<板块名>&limit=<1-3，默认3>            ║
║                             &hours=<候选池时间窗，默认72>&lang=<zh|en>     ║
╚══════════════════════════════════════════════════════════════════════════╝

## 这个模块解决的是什么问题

`api/lab_tools.py` 头部注释里写得很直白："完整版 Sector Insight 相关性算法
尚未上线，这是已知技术债务"——它当时的退化方案是"板块命中 sectors 数组记
1.0，否则 0.0"的二元判断。本模块就是把这块技术债务实现掉：真正按
`docs/skill-sector-news-recommendation-v5.md` 的公式做连续打分、硬门、
体裁/传导链/板块类型化的 bad case 处理、Sector Insight 专属去重（cosine
>=0.75，不同于 Macro Insight 已标定的 0.82）、宁缺毋滥。

打分全部实现在 `crawler/sector_relevance.py`，本文件只是一层薄薄的 HTTP
包装：解析请求参数 → 拿一条数据库连接 → 调
`crawler.sector_relevance.recommend_sector()` → 序列化返回。所有业务逻辑
（两层预筛+精判、硬门打分、去重、宁缺毋滥）都在那个模块，不在这里重复。

## 成本与延迟提示

每次请求会：
  1. 对板块锚点文本算 1 次 embedding（近乎零成本）；
  2. 对预筛通过的候选跑 gpt-5.4 结构化判定（按 LLM_BATCH_SIZE 批量调用，
     不是逐条调用，但仍是本请求里最慢、最贵的一步）。
这不是一个能扛高 QPS 的端点——每次请求的延迟主要取决于候选池大小和预筛
通过率（实测数据见交付报告）。本文件加了一个简单的进程内短 TTL 缓存
（见 _CACHE_TTL_SECONDS）防止同一板块在几分钟内被反复请求时重复烧 LLM
调用；需要跨进程/跨实例共享缓存，或需要更长缓存时间，应在此基础上加
Redis 或直接把结果写回 news_events 之类的持久层，本文件不做这个决定。
"""
import os
import sys
import time
from functools import wraps

from flask import Blueprint, jsonify, request

# 仓库根目录塞进 sys.path——和 eval_tools.py 用一样的防御性写法，不管本文件是被
# server.py（sys.path[0]=api/）同目录 import，还是被独立当脚本跑，都能找到 crawler 包。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from crawler import storage  # noqa: E402
from crawler.sector_relevance import (  # noqa: E402
    DEFAULT_CANDIDATE_HOURS, MAX_RECOMMEND, SECTOR_ANCHORS, get_openai_client,
    recommend_sector,
)
from crawler.sources import SECTOR_LABELS  # noqa: E402
from crawler.usage_tracker import UsageTracker  # noqa: E402

sector_insight_bp = Blueprint("sector_insight", __name__)

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")

# 2026-07-26：跟 api/server.py 的 VALID_API_KEYS 保持同步，5 个可分发给不同人的 token。
API_TOKENS = {
    "lawrence":  os.environ.get("API_TOKEN_LAWRENCE", ""),
    "team-a":    os.environ.get("API_TOKEN_TEAM_A", ""),
    "team-b":    os.environ.get("API_TOKEN_TEAM_B", ""),
    "partner-1": os.environ.get("API_TOKEN_PARTNER1", ""),
    "partner-2": os.environ.get("API_TOKEN_PARTNER2", ""),
    "web":       os.environ.get("API_TOKEN_WEB", ""),
}
# 2026-08-05 仓库转 public：所有凭据的**硬编码兜底一律删除**，只从环境变量读。
# 取不到就是空字符串，而空值**必须被剔除**——否则空 token 会成为一个合法凭据，
# 把"忘了配 .env"直接变成"任何人空手就能过鉴权"，是最典型的 fail-open。
VALID_API_KEYS = {k for k in (API_SECRET_KEY, *API_TOKENS.values()) if k}


def require_api_key(f):
    """与 api/server.py 的 require_api_key 逻辑一致，独立实现不 import server.py
    （原因同 lab_tools.py 头部注释：避免和同时改 server.py 的另一个任务耦合）。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not key:
            key = request.args.get("token", "")
        if key not in VALID_API_KEYS:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── 进程内短 TTL 缓存 ────────────────────────────────────────────────────
# 目的仅仅是防止"同一板块几分钟内被点了好几次刷新"重复烧 LLM 调用，不是为了
# 支撑高 QPS（那需要持久层，见文件头注释）。key = (sector, hours, limit, lang)。
_CACHE_TTL_SECONDS = int(os.environ.get("SECTOR_INSIGHT_CACHE_TTL", "180"))
_cache: dict[tuple, tuple[float, dict]] = {}


def _cached_recommend(sector: str, hours: int, limit: int, lang: str) -> dict:
    key = (sector, hours, limit, lang)
    now = time.time()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < _CACHE_TTL_SECONDS:
        result = dict(hit[1])
        result["_cache_hit"] = True
        return result

    conn = storage.get_mysql_conn()
    tracker = UsageTracker()
    try:
        result = recommend_sector(
            sector, conn, hours=hours, limit=limit,
            client=get_openai_client(), tracker=tracker, lang=lang,
        )
        result["usage"] = tracker.snapshot()
    finally:
        conn.close()

    _cache[key] = (now, result)
    result = dict(result)
    result["_cache_hit"] = False
    return result


@sector_insight_bp.route("/api/recommend/sector", methods=["GET"])
@require_api_key
def get_sector_recommendation():
    sector = request.args.get("sector", "").strip()
    if not sector:
        return jsonify({"error": "missing required query param 'sector'",
                        "valid_sectors": SECTOR_LABELS}), 400
    if sector not in SECTOR_LABELS:
        return jsonify({"error": f"unknown sector '{sector}'",
                        "valid_sectors": SECTOR_LABELS}), 400

    try:
        limit = int(request.args.get("limit", MAX_RECOMMEND))
    except (TypeError, ValueError):
        limit = MAX_RECOMMEND
    # 下界必须是 1，不是 0。之前写的 max(0, ...) 会把 ?limit=0 原样放行：请求照样
    # 跑完整套两层预筛 + gpt-5.4 精判（真花钱、也真占 Flask worker），最后返回一个
    # 空列表——用户以为"这个板块没有可推的新闻"，实际上是自己把 limit 传成了 0；
    # 而且和文件头注释、skill 文档写的 limit=1-3 对不上。负数同理钳到 1。
    # 上界 Top3 见 skill 文档"宁缺毋滥"。
    limit = max(1, min(limit, MAX_RECOMMEND))

    try:
        hours = int(request.args.get("hours", DEFAULT_CANDIDATE_HOURS))
    except (TypeError, ValueError):
        hours = DEFAULT_CANDIDATE_HOURS
    hours = max(1, min(hours, 24 * 14))   # 上限 14 天，防止候选池无节制增长拖垮请求

    lang = request.args.get("lang", "zh").strip().lower()
    if lang not in ("zh", "en"):
        lang = "zh"

    try:
        result = _cached_recommend(sector, hours, limit, lang)
    except Exception as e:
        return jsonify({"error": f"sector recommendation failed: {e}"}), 500

    return jsonify(result)


# ── 板块列表（供前端下拉框展示每个板块的类型，避免前端自己去猜赛道型/公链/机制型）
@sector_insight_bp.route("/api/recommend/sector/list", methods=["GET"])
@require_api_key
def list_sectors():
    return jsonify({
        "data": [
            {"sector": s, "type": SECTOR_ANCHORS.get(s, {}).get("type", "track")}
            for s in SECTOR_LABELS
        ]
    })


if __name__ == "__main__":
    # 独立自测：python3 api/sector_insight.py MEME
    import json as _json
    sector_arg = sys.argv[1] if len(sys.argv) > 1 else "MEME"
    conn = storage.get_mysql_conn()
    try:
        out = recommend_sector(sector_arg, conn, client=get_openai_client())
        print(_json.dumps(out, ensure_ascii=False, indent=2, default=str))
    finally:
        conn.close()
