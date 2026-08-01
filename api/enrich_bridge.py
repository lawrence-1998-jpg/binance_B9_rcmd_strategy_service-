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
import struct
import sys
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector  # noqa: E402

from crawler.pipeline import (  # noqa: E402
    LLM_LITE_TYPES, NEWS_SCHEMA, PROMPT_VERSION_HASH, SYSTEM_PROMPT,
    _REQUIRED_ENRICH_KEYS, build_enrich_input,
)
# 派活窗口必须与 pipeline 取数窗口用**同一个常量**：两边不一致的话，会出现
# "pipeline 已经不要了、但桥还在派"或反过来"桥不派了、pipeline 却还在等"的
# 死角，而且不报错。这正是本项目反复踩的"同一事实两处手写"。
from crawler.staging import STAGING_MAX_AGE_DAYS  # noqa: E402
# 向量维度取 dedup 的常量，不在这里重写一个数字——两处不一致会让存进来的
# 向量长度对不上，blob_to_embedding 一律判 None，静默退化成"从来没有向量"。
from crawler.dedup import EMBED_DIM, EMBED_MODEL  # noqa: E402

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
        # 向量口径也由 VM 下发，worker 端零硬编码（与 prompt 同一原则）：
        # 换模型/换维度只改 VM，worker 下次唤醒自动跟上。
        "embedding_model": EMBED_MODEL,
        "embedding_dim": EMBED_DIM,
        "input_template_example": build_enrich_input({
            "source": "<source>", "title": "<title>", "summary": "<summary>",
            "url": "<url>", "published_at": "<published_at>",
        }),
    })


@enrich_bridge_bp.route("/api/enrich/pending", methods=["GET"])
@require_api_key
def enrich_pending():
    """领任务：staging 里未被 pipeline 消费、且当前口径下还没有缓存的条目。"""
    # 2026-07-28：上限从 200 提到 1000。原来的 200 是按"Mac 用 claude CLI 逐条
    # 处理、一次唤醒也就啃几十条"的旧节奏定的；现在 worker 走网关、29 RPM、
    # 并发 12，一次唤醒能吃掉几百条，200 会让它领完就空转等下次唤醒。
    try:
        limit = max(1, min(1000, int(request.args.get("limit", 40))))
    except ValueError:
        limit = 40
    conn = _db()
    try:
        cursor = conn.cursor(dictionary=True)
        # 顺手清理：7 天前的缓存行（已消费的、prompt 已换代的都覆盖在内）
        cursor.execute(
            "DELETE FROM llm_enrich_cache WHERE created_at < NOW() - INTERVAL 7 DAY")
        conn.commit()
        # 派活按**当前 prompt_hash** 过滤，而复用（storage.load_enrich_cache）
        # 不按 hash 过滤——两边口径刻意不对称，这是想清楚之后的选择，别"统一"掉：
        #
        #   · 复用侧问的是"我现在能不能直接用"→ 任何算过的都行，字段不全的会被
        #     _valid_cached_enrichment 挡掉自动回退，安全。
        #   · 派活侧问的是"还有什么需要按当前口径算"→ 必须认当前 hash。
        #
        # 2026-07-28 我一度把派活侧也改成"有任何缓存就不派"，当场踩了坑：那天
        # 给 schema 加了 market_scope 必填字段，旧缓存 400 条 SQL 上全命中、
        # 字段校验却 0 条通过（缺 market_scope）。派活侧一旦不认 hash，这些条目
        # 就永远不会被重新派出去补算，而复用侧又用不了它们——结果是每轮都稳定
        # 回落到付费的 OpenAI 直连，且没有任何机制能自愈。改回按 hash 派活后，
        # 这类条目会被重新派给 Mac 用公司额度补算，一轮之后就能被复用侧吃到。
        cursor.execute(
            """SELECT s.url_hash, s.source, s.title, s.url, s.summary,
                      s.published_at, s.lang, s.authority, s.type
                 FROM raw_items_staging s
            LEFT JOIN llm_enrich_cache c
                   ON c.url_hash = s.url_hash AND c.prompt_hash = %s
                WHERE s.consumed_at IS NULL
                  AND s.fetched_at >= NOW() - INTERVAL %s DAY
                  AND c.url_hash IS NULL
             -- 优先级在前：断供恢复后要先把权威大盘内容补回来，而不是
             -- 按时间顺序先啃几千条长尾。与 staging.fetch_staged_items 同口径。
             ORDER BY s.priority ASC, s.fetched_at ASC
                LIMIT %s""",
            (PROMPT_VERSION_HASH, STAGING_MAX_AGE_DAYS, limit),
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
            # 可选向量（ADR-002 A4）：Mac 算 enrich 时顺手用公司网关算好的
            # 256 维 float32。格式不对就当没有——向量是加速/提质项，
            # 绝不能因为它有问题而丢掉已经算好的结构化结果。
            emb_blob = None
            vec = (r or {}).get("embedding")
            if isinstance(vec, list) and len(vec) == EMBED_DIM:
                try:
                    emb_blob = struct.pack(f"<{EMBED_DIM}f", *(float(x) for x in vec))
                except (TypeError, ValueError, struct.error):
                    emb_blob = None
            cursor.execute(
                """INSERT INTO llm_enrich_cache
                     (url_hash, prompt_hash, enriched, model, embedding)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     prompt_hash = VALUES(prompt_hash),
                     enriched    = VALUES(enriched),
                     model       = VALUES(model),
                     embedding   = VALUES(embedding),
                     created_at  = CURRENT_TIMESTAMP,
                     consumed_at = NULL""",
                (url_hash, PROMPT_VERSION_HASH,
                 json.dumps(enriched, ensure_ascii=False),
                 (r.get("model") or "claude-local")[:64], emb_blob),
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
                  AND fetched_at >= NOW() - INTERVAL %s DAY""",
            (STAGING_MAX_AGE_DAYS,))
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


@enrich_bridge_bp.route("/api/enrich/credential-meta", methods=["GET", "POST"])
@require_api_key
def credential_meta():
    """公司 key 的**元数据**登记与查询（ADR-002 A2）。

    ⚠️ 这个端点永远不接收、不存储、不返回 key 本身。密钥只存在 Lawrence 的
    Mac 上（~/.b9/credentials.json），因为只有那台机器连得通公司内网网关。
    这里存的是"还剩几天到期、上次成功调用是什么时候、连续失败几次"——
    足够支撑看板和预警，泄露了也没有任何利用价值。

    POST 由 scripts/b9key.py 在轮换/自测时调用；GET 给监控看板用。
    """
    conn = _db()
    try:
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            name = (body.get("name") or "").strip()[:64]
            if not name:
                return jsonify({"error": "name required"}), 400
            # 防呆：万一哪天有人手滑把 key 塞进来，直接拒收并明确报错，
            # 而不是"顺手存下来"——秘密一旦落进这张表就等于进了公网可达的库。
            for v in body.values():
                if isinstance(v, str) and v.startswith("sk-"):
                    return jsonify({"error": "refusing payload containing a secret; "
                                             "this endpoint stores metadata only"}), 400
            ok = body.get("ok")
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO llm_credentials_meta
                     (name, provider, status, expires_at, last_ok_at,
                      last_error, consecutive_failures)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     provider   = VALUES(provider),
                     status     = VALUES(status),
                     expires_at = VALUES(expires_at),
                     last_ok_at = COALESCE(VALUES(last_ok_at), last_ok_at),
                     last_error = VALUES(last_error),
                     consecutive_failures = IF(VALUES(last_ok_at) IS NOT NULL,
                                               0, consecutive_failures + 1)""",
                (name, body.get("provider", "litellm-gateway"),
                 body.get("status", "active"), body.get("expires_at") or None,
                 datetime.now() if ok else None,
                 (body.get("error") or "")[:500] or None, 0 if ok else 1))
            conn.commit()
            cur.close()
            return jsonify({"ok": True, "name": name})

        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT name, provider, status, expires_at, last_ok_at,
                      last_error, consecutive_failures,
                      DATEDIFF(expires_at, CURDATE()) AS days_left
                 FROM llm_credentials_meta
             ORDER BY FIELD(status,'active','replaced','expired','disabled'),
                      expires_at DESC""")
        rows = cur.fetchall()
        cur.close()
        out = []
        for r in rows:
            days_left = r.get("days_left")
            out.append({
                "name": r["name"], "provider": r["provider"], "status": r["status"],
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "last_ok_at": r["last_ok_at"].isoformat() if r["last_ok_at"] else None,
                "last_error": r["last_error"],
                "consecutive_failures": int(r["consecutive_failures"] or 0),
                "days_left": int(days_left) if days_left is not None else None,
                # 看板直接用这个字段决定要不要飘红，别让前端各自算一遍口径
                "needs_rotation": days_left is not None and days_left <= 2,
            })
        return jsonify({"credentials": out,
                        "warn_threshold_days": 2})
    finally:
        conn.close()


@enrich_bridge_bp.route("/api/enrich/backlog", methods=["GET"])
@require_api_key
def enrich_backlog():
    """积压全景 —— 对应需求的"停掉后能有记录或可查能力"。

    断供期间最需要回答的三个问题，这里一次给全：
      · 还欠多少、最老的欠了多久（会不会撞上 30 天回补天花板）
      · 是被成本闸挡的，还是根本没人来领（defer_reason 区分）
      · 按现在的速度，排干要多久（预计值，给运维一个量级感）
    """
    conn = _db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT COUNT(*) AS total,
                      SUM(deferred_count > 0)               AS deferred,
                      MIN(fetched_at)                       AS oldest,
                      TIMESTAMPDIFF(HOUR, MIN(fetched_at), NOW()) AS oldest_hours,
                      -- 别名刻意不叫 high_priority：那是 MySQL 保留字
                      -- （SELECT HIGH_PRIORITY …），不加反引号直接 1064。
                      SUM(priority <= 2)                    AS urgent_count
                 FROM raw_items_staging
                WHERE consumed_at IS NULL
                  AND fetched_at >= NOW() - INTERVAL %s DAY""",
            (STAGING_MAX_AGE_DAYS,))
        summary = cur.fetchone() or {}

        # 超窗条目：**不静默丢弃**，单独报出来。它们已经过了回补天花板，
        # 要不要救回来是一个需要人做的决定，不该由一个 WHERE 条件替人决定。
        cur.execute(
            """SELECT COUNT(*) AS cold FROM raw_items_staging
                WHERE consumed_at IS NULL
                  AND fetched_at < NOW() - INTERVAL %s DAY""",
            (STAGING_MAX_AGE_DAYS,))
        cold = (cur.fetchone() or {}).get("cold", 0)

        cur.execute(
            """SELECT defer_reason, COUNT(*) AS n
                 FROM raw_items_staging
                WHERE consumed_at IS NULL AND deferred_count > 0
             GROUP BY defer_reason ORDER BY n DESC""")
        reasons = cur.fetchall()

        cur.execute(
            """SELECT DATE(fetched_at) AS day, COUNT(*) AS n
                 FROM raw_items_staging
                WHERE consumed_at IS NULL
                  AND fetched_at >= NOW() - INTERVAL %s DAY
             GROUP BY DATE(fetched_at) ORDER BY day DESC LIMIT 30""",
            (STAGING_MAX_AGE_DAYS,))
        by_day = cur.fetchall()

        # 排干速度按最近 24h 实际消费量估。桥不在线时分母为 0——
        # 那种情况下给 None 而不是硬算出个无穷大或 0，让调用方自己表达"未知"。
        cur.execute(
            """SELECT COUNT(*) AS n FROM raw_items_staging
                WHERE consumed_at >= NOW() - INTERVAL 24 HOUR""")
        drained_24h = (cur.fetchone() or {}).get("n", 0) or 0
        total = int(summary.get("total") or 0)
        eta_hours = round(total / (drained_24h / 24), 1) if drained_24h else None
        cur.close()

        return jsonify({
            "backlog_total": total,
            "backlog_deferred_by_cost_gate": int(summary.get("deferred") or 0),
            "backlog_high_priority": int(summary.get("urgent_count") or 0),
            "oldest_fetched_at": (summary.get("oldest").isoformat()
                                  if summary.get("oldest") else None),
            "oldest_age_hours": int(summary.get("oldest_hours") or 0),
            "cold_beyond_horizon": int(cold or 0),
            "horizon_days": STAGING_MAX_AGE_DAYS,
            "defer_reasons": [{"reason": r["defer_reason"], "count": int(r["n"])}
                              for r in reasons],
            "by_day": [{"day": str(r["day"]), "count": int(r["n"])} for r in by_day],
            "drained_last_24h": int(drained_24h),
            "eta_hours_to_drain": eta_hours,
        })
    finally:
        conn.close()
