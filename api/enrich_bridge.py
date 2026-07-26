"""
Enrich Bridge —— 本地 Claude 预处理的任务分发与结果回收端点。

╔══════════════════════════════════════════════════════════════════════════╗
║ 全链路（谁在什么时候调谁）：                                              ║
║                                                                            ║
║   Lawrence 的 Mac（launchd 每 30 分钟唤醒 scripts/local_enrich_worker.py）║
║     ① GET  /api/enrich/prompt   → 拿当前 SYSTEM_PROMPT/schema/prompt_hash ║
║     ② GET  /api/enrich/pending  → 领一批 staging 里还没人处理的条目       ║
║     ③ 本地 `claude -p` 逐条结构化（花的是 Claude Max 订阅额度，非 API 钱）║
║     ④ POST /api/enrich/submit   → 校验后写入 llm_enrich_cache             ║
║                                                                            ║
║   VM 的 pipeline（cron 每 12h）                                           ║
║     Step 4 先查 llm_enrich_cache（storage.load_enrich_cache），命中免费， ║
║     未命中走 OpenAI —— Mac 不在线时缓存全 miss，行为与从前完全一致。      ║
╚══════════════════════════════════════════════════════════════════════════╝

设计要点：
- pull 模式：Mac 主动来拉，VM 永远不需要反连 Mac（工作机没有公网入口，
  且不能保证开机——这是用户给的硬约束）。
- prompt_hash 闸门：worker 领任务时拿到的 prompt 指纹必须原样带回；提交时
  不一致直接 409 拒收。pipeline 读取时再验一次。两道闸保证"缓存里的结果
  一定是用当前口径算的"。
- pending 端点顺手清理 7 天前的旧缓存行（prompt 迭代残留、pipeline 已消费
  的行），表不会无限膨胀，也不用单独的清理 cron。

接入 server.py（与其它 blueprint 同一模式）：
    from enrich_bridge import enrich_bridge_bp
    app.register_blueprint(enrich_bridge_bp)
"""
import json
import logging
import os
import sys
from functools import wraps

from flask import Blueprint, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector  # noqa: E402

from crawler.pipeline import (  # noqa: E402
    LLM_LITE_TYPES, NEWS_SCHEMA, PROMPT_VERSION_HASH, SYSTEM_PROMPT,
    _REQUIRED_ENRICH_KEYS, build_enrich_input,
)

logger = logging.getLogger(__name__)

enrich_bridge_bp = Blueprint("enrich_bridge", __name__)

API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "***REMOVED***")
API_TOKENS = {
    "lawrence":  os.environ.get("API_TOKEN_LAWRENCE",  "***REMOVED***"),
    "team-a":    os.environ.get("API_TOKEN_TEAM_A",    "***REMOVED***"),
    "team-b":    os.environ.get("API_TOKEN_TEAM_B",    "***REMOVED***"),
    "partner-1": os.environ.get("API_TOKEN_PARTNER1",  "***REMOVED***"),
    "partner-2": os.environ.get("API_TOKEN_PARTNER2",  "***REMOVED***"),
    "web":       os.environ.get("API_TOKEN_WEB",       "***REMOVED***"),
}
VALID_API_KEYS = {API_SECRET_KEY, *API_TOKENS.values()}


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not key:
            key = request.args.get("token", "")
        if key not in VALID_API_KEYS:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def _db():
    return mysql.connector.connect(
        host="localhost", user="root",
        password=os.environ.get("MYSQL_PASSWORD", "***REMOVED***"),
        database="crypto_news", charset="utf8mb4",
    )


@enrich_bridge_bp.route("/api/enrich/prompt", methods=["GET"])
@require_api_key
def enrich_prompt():
    """worker 的口径来源。把 prompt/schema/输入格式全部下发，worker 端零硬编码，
    VM 上改了 prompt，worker 下一次唤醒自动用新口径。"""
    return jsonify({
        "prompt_hash": PROMPT_VERSION_HASH,
        "system_prompt": SYSTEM_PROMPT,
        "schema": NEWS_SCHEMA["json_schema"]["schema"],
        "required_keys": sorted(_REQUIRED_ENRICH_KEYS),
        "lite_types": sorted(LLM_LITE_TYPES),
        "input_template_example": build_enrich_input({
            "source": "<source>", "title": "<title>", "summary": "<summary>",
            "url": "<url>", "published_at": "<published_at>",
        }),
    })


@enrich_bridge_bp.route("/api/enrich/pending", methods=["GET"])
@require_api_key
def enrich_pending():
    """领任务：staging 里未被 pipeline 消费、且当前口径下还没有缓存的条目。"""
    try:
        limit = max(1, min(200, int(request.args.get("limit", 40))))
    except ValueError:
        limit = 40
    conn = _db()
    try:
        cursor = conn.cursor(dictionary=True)
        # 顺手清理：7 天前的缓存行（已消费的、prompt 已换代的都覆盖在内）
        cursor.execute(
            "DELETE FROM llm_enrich_cache WHERE created_at < NOW() - INTERVAL 7 DAY")
        conn.commit()
        cursor.execute(
            """SELECT s.url_hash, s.source, s.title, s.url, s.summary,
                      s.published_at, s.lang, s.authority, s.type
                 FROM raw_items_staging s
            LEFT JOIN llm_enrich_cache c
                   ON c.url_hash = s.url_hash AND c.prompt_hash = %s
                WHERE s.consumed_at IS NULL
                  AND s.fetched_at >= NOW() - INTERVAL 7 DAY
                  AND c.url_hash IS NULL
             ORDER BY s.fetched_at DESC
                LIMIT %s""",
            (PROMPT_VERSION_HASH, limit),
        )
        rows = cursor.fetchall()
        cursor.close()
        return jsonify({"prompt_hash": PROMPT_VERSION_HASH,
                        "count": len(rows), "items": rows})
    finally:
        conn.close()


@enrich_bridge_bp.route("/api/enrich/submit", methods=["POST"])
@require_api_key
def enrich_submit():
    """收结果。prompt_hash 不匹配整批拒收（409）；单条缺必填字段跳过该条。"""
    body = request.get_json(silent=True) or {}
    if body.get("prompt_hash") != PROMPT_VERSION_HASH:
        return jsonify({"error": "prompt_hash mismatch — prompt was updated, "
                                 "re-fetch /api/enrich/prompt",
                        "current": PROMPT_VERSION_HASH}), 409
    results = body.get("results") or []
    if not isinstance(results, list) or not results:
        return jsonify({"error": "results must be a non-empty list"}), 400
    if len(results) > 200:
        return jsonify({"error": "max 200 results per submit"}), 400

    accepted, rejected = 0, []
    conn = _db()
    try:
        cursor = conn.cursor()
        for r in results:
            url_hash = (r or {}).get("url_hash", "")
            enriched = (r or {}).get("enriched")
            if (not isinstance(url_hash, str) or len(url_hash) != 64
                    or not isinstance(enriched, dict)
                    or not _REQUIRED_ENRICH_KEYS.issubset(enriched.keys())):
                rejected.append(url_hash[:16] if isinstance(url_hash, str) else "?")
                continue
            cursor.execute(
                """INSERT INTO llm_enrich_cache (url_hash, prompt_hash, enriched, model)
                   VALUES (%s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     prompt_hash = VALUES(prompt_hash),
                     enriched    = VALUES(enriched),
                     model       = VALUES(model),
                     created_at  = CURRENT_TIMESTAMP,
                     consumed_at = NULL""",
                (url_hash, PROMPT_VERSION_HASH,
                 json.dumps(enriched, ensure_ascii=False),
                 (r.get("model") or "claude-local")[:64]),
            )
            accepted += 1
        conn.commit()
        cursor.close()
    finally:
        conn.close()
    logger.info(f"enrich bridge submit: {accepted} accepted, {len(rejected)} rejected")
    return jsonify({"accepted": accepted, "rejected": rejected})


@enrich_bridge_bp.route("/api/enrich/stats", methods=["GET"])
@require_api_key
def enrich_stats():
    """桥的水位：缓存量、消费量、当前口径覆盖率。观测用，预估级别。"""
    conn = _db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT COUNT(*), SUM(consumed_at IS NOT NULL),
                      SUM(prompt_hash = %s)
                 FROM llm_enrich_cache""", (PROMPT_VERSION_HASH,))
        total, consumed, current = cursor.fetchone()
        cursor.execute(
            """SELECT COUNT(*) FROM raw_items_staging
                WHERE consumed_at IS NULL
                  AND fetched_at >= NOW() - INTERVAL 7 DAY""")
        backlog = cursor.fetchone()[0]
        cursor.close()
        return jsonify({
            "cache_total": int(total or 0),
            "cache_consumed_by_pipeline": int(consumed or 0),
            "cache_current_prompt": int(current or 0),
            "staging_backlog_unconsumed": int(backlog or 0),
            "prompt_hash": PROMPT_VERSION_HASH,
        })
    finally:
        conn.close()
