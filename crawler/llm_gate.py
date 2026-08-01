"""成本硬闸 —— 个人 OpenAI key 的唯一收费闸口（ADR-002 块 A）。

╔══════════════════════════════════════════════════════════════════════════╗
║ 一句话：**这个模块只管一件事——现在能不能花 Lawrence 个人账号的钱。**     ║
╚══════════════════════════════════════════════════════════════════════════╝

## 为什么需要它

改造前全项目有 4 处各自独立的 `OpenAI(**kwargs)` 构造、9 个实际付费调用点，
没有任何统一入口。"加一个总开关"这件事在那种结构下做不到——总会漏掉一处，
而漏掉的那处不会报错，只会在月底账单上出现。这正是检修报告里"手写副本必
腐化"的同族问题：**没有单一闸口，就没有单一开关。**

## 职责边界（重要，别搞混）

本模块**只管个人 key**，不管公司额度。原因是物理性的：VM 连不通公司内网的
LiteLLM 网关，公司额度只有 Lawrence 的 Mac 用得上，走的是 enrich bridge
那条异步通路（Mac 拉任务 → 网关算 → 回写 llm_enrich_cache）。所以：

    个人 key 花钱   →  由本模块把关（同步、有客户端对象）
    公司额度花钱   →  由 Mac worker + key 注册表把关（异步、没有客户端对象）

两条通路的治理机制不同，硬套成一套只会把两边都搞乱。

## 三条设计原则

1. **Fail-closed**：DB 连不上、表不存在、值解析失败——一律当"关闭"处理。
   成本闸的默认行为必须是不花钱。一个因为读不到配置就放行的闸口不叫闸口。
2. **开启必须带自动失效**：个人 key 是"紧急才用"，而人在救火时最容易忘记
   关回去。把"忘记关"从流程纪律变成机制保证，到点自动回到不花钱状态。
3. **拒绝要留痕**：跳过了什么、为什么跳过、跳过多少次，都要能查。否则就是
   检修报告里"静默失败家族"再犯一次——只不过这次静默的是"没数据"而不是
   "没备份"。

## 用法

    from crawler import llm_gate

    client = llm_gate.acquire("enrich", item=staging_row)
    if client is None:
        llm_gate.record_deferred([row_ids], llm_gate.last_reason())
        return []            # 不付费、不消费、留给下一轮
    resp = client.chat.completions.create(...)
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime

logger = logging.getLogger(__name__)

# ── 开关键名（与 migration 018 的 runtime_flags 行一一对应）──────────
FLAG_ALLOW_PERSONAL = "allow_personal_key"
FLAG_MAX_PRIORITY = "emergency_max_priority"
FLAG_DAILY_CAP = "emergency_daily_item_cap"

# fail-closed 默认值。这些值在**任何**读取失败的情况下生效。
_DEFAULTS = {
    FLAG_ALLOW_PERSONAL: "0",   # 关闭
    FLAG_MAX_PRIORITY: "2",     # 只放行 P0-P2（权威大盘/大盘指数/加密头部）
    FLAG_DAILY_CAP: "2000",
}

# 环境变量逃生门：DB 挂了也要能在紧急时开闸。
# 刻意只认 "1"——不认 "true"/"yes"，避免手滑打个 "0 " 或 "false" 被当成真值。
ENV_ESCAPE_HATCH = "B9_ALLOW_PERSONAL_KEY"

# 缓存开关读取结果，避免每条目一次 DB 往返（enrich 是几百条并发的循环）。
# TTL 短是刻意的：Lawrence 在网页/命令行改了开关，最多 30 秒内生效，
# 不用重启任何进程。
_FLAG_TTL_S = 30
_flag_cache: dict = {"at": 0.0, "values": {}}
_flag_lock = threading.Lock()

# 本轮统计。record_deferred 累加，run_pipeline 收尾时落进 pipeline_runs。
_stats_lock = threading.Lock()
_stats = {"allowed": 0, "deferred": 0, "reasons": {}}
_last_reason = "not_evaluated"

# 本轮**被成本闸拦下**的 url 集合。
#
# 为什么要精确到 url 而不是只记条数：staging 的消费标记必须区分"没被处理"的
# 两种情况——被成本闸推迟（要留在队列里等下一轮）vs 被时间可信度闸/预过滤
# 故意丢弃（已经判定不要，必须标记消费）。2026-08-02 首版用"成功结构化的
# url 集合"取反来判断，结果把 68 条被信任闸丢弃的聚合器条目也留在了队列里，
# 队列会无限增长且每轮重复处理同一批。反过来记"被闸拦下的"才是准的。
_deferred_urls: set = set()


# ── 内部：读开关 ─────────────────────────────────────────────────────

def _now() -> datetime:
    from .timeutil import now_local
    return now_local()


def _load_flags(conn=None) -> dict:
    """从 runtime_flags 读全部开关。任何异常都回落到 _DEFAULTS（fail-closed）。"""
    import time
    with _flag_lock:
        if time.time() - _flag_cache["at"] < _FLAG_TTL_S and _flag_cache["values"]:
            return _flag_cache["values"]

    values = dict(_DEFAULTS)
    own_conn = False
    try:
        if conn is None:
            from . import storage
            conn = storage.get_mysql_conn()
            own_conn = True
        cur = conn.cursor()
        cur.execute("SELECT flag_key, flag_value, expires_at FROM runtime_flags")
        for key, val, expires_at in cur.fetchall():
            # 过期的开关等于没开。这里是"自动失效"真正生效的地方——
            # 不依赖任何定时任务去回写，读的时候判一次就够了，
            # 定时任务本身也可能挂（而挂了不会有人知道）。
            if expires_at and _now().replace(tzinfo=None) > expires_at:
                if key == FLAG_ALLOW_PERSONAL and val == "1":
                    logger.warning(
                        f"成本闸：个人 key 开关已于 {expires_at} 自动失效，回落到禁用")
                continue
            values[key] = val
        cur.close()
    except Exception as e:
        # 读不到就当关闭。不抛异常——闸口自身故障不该搞垮整条 pipeline，
        # 但也绝不能因为自己坏了就放行。
        logger.warning(f"成本闸：读取 runtime_flags 失败，按禁用处理（{e}）")
        values = dict(_DEFAULTS)
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    with _flag_lock:
        _flag_cache["at"] = __import__("time").time()
        _flag_cache["values"] = values
    return values


def _int_flag(values: dict, key: str) -> int:
    try:
        return int(values.get(key, _DEFAULTS[key]))
    except (TypeError, ValueError):
        logger.warning(f"成本闸：{key} 值非法，用默认 {_DEFAULTS[key]}")
        return int(_DEFAULTS[key])


def _today_personal_count(conn) -> int:
    """今天已经用个人 key 处理了多少条（日配额用）。

    数的是 staging 里今天被消费掉的条目——不是完美口径（命中缓存的也算在内），
    但配额是个安全兜底而不是计费依据，宁可**高估**：高估的后果是提前停手，
    低估的后果是超预算。方向选对了比精度更重要。
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM raw_items_staging "
                    "WHERE consumed_at >= CURDATE()")
        n = cur.fetchone()[0]
        cur.close()
        return int(n or 0)
    except Exception as e:
        logger.warning(f"成本闸：日配额计数失败，按已用满处理（{e}）")
        return 10 ** 9      # 读不到就当用满 —— 同样是 fail-closed


# ── 对外：申请客户端 ─────────────────────────────────────────────────

def is_personal_enabled(conn=None) -> bool:
    """个人 key 总闸是否打开。环境变量逃生门优先于 DB。"""
    if os.environ.get(ENV_ESCAPE_HATCH) == "1":
        return True
    return _load_flags(conn).get(FLAG_ALLOW_PERSONAL) == "1"


def acquire(purpose: str, item: dict | None = None, conn=None):
    """申请一个**个人 key** 客户端。不允许则返回 None（调用方必须处理）。

    `purpose`：用途标签，进日志与统计（enrich / embedding / sector_relevance…）
    `item`   ：staging 行或 enriched 条目。带 priority 时参与紧急模式档位过滤。

    返回 None 的三种原因（可用 last_reason() 取）：
      personal_key_disabled     总闸关闭（默认状态）
      below_emergency_priority  开着，但这条不够重要
      daily_cap_reached         开着，但今天的配额用完了
    """
    global _last_reason

    values = _load_flags(conn)
    env_on = os.environ.get(ENV_ESCAPE_HATCH) == "1"

    if not env_on and values.get(FLAG_ALLOW_PERSONAL) != "1":
        _last_reason = "personal_key_disabled"
        _bump("deferred", _last_reason, item)
        return None

    # 紧急模式的档位闸。
    #
    # 注意这里用的是 staging.priority 而不是 event_tier——event_tier(S/A/B/C/D)
    # 是 LLM **产出**的字段，在"要不要花钱处理这条"的决策点上它还不存在。
    # priority 在抓取入库时就算好了（见 staging.resolve_priority），正是为
    # "哪些内容值得优先处理"设计的，是这里唯一可用的重要性代理。
    if item is not None:
        max_prio = _int_flag(values, FLAG_MAX_PRIORITY)
        prio = item.get("priority")
        if prio is not None and int(prio) > max_prio:
            _last_reason = "below_emergency_priority"
            _bump("deferred", _last_reason, item)
            return None

    # 日配额兜底：开关的自动失效管的是"忘记关"，配额管的是"开着的这几小时里
    # 量突然暴涨"。两道闸方向不同，都要有。
    cap = _int_flag(values, FLAG_DAILY_CAP)
    own_conn = False
    try:
        if conn is None:
            from . import storage
            conn = storage.get_mysql_conn()
            own_conn = True
        if _today_personal_count(conn) >= cap:
            _last_reason = "daily_cap_reached"
            _bump("deferred", _last_reason, item)
            logger.warning(f"成本闸：今日个人 key 配额 {cap} 已用满，停止付费处理")
            return None
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    # 闸放行了，但"允许花钱"不等于"有钱可花"——个人 key 可能压根没配、
    # 被吊销、或余额耗尽被移出 .env。OpenAI SDK 在缺凭据时是**抛异常**而不是
    # 返回 None，直接让它抛会炸掉整批 enrich（一条没配好的 key 搞垮一整轮）。
    # 这两种情况必须区分：拒绝放行是设计内的降级，凭据缺失是配置问题，
    # 但对调用方来说处理方式相同——拿不到客户端就把条目留给下一轮。
    # 2026-08-02 行为矩阵测试实测到的，不是预防性防御。
    try:
        from .pipeline import get_openai_client
        client = get_openai_client()
    except Exception as e:
        _last_reason = "personal_key_unavailable"
        _bump("deferred", _last_reason, item)
        logger.warning(f"成本闸：开关已开但个人 key 不可用（{e}）——按拒绝处理")
        return None

    _last_reason = "allowed"
    _bump("allowed", purpose)
    return client


def last_reason() -> str:
    return _last_reason


# ── 对外：留痕与统计 ─────────────────────────────────────────────────

def _bump(bucket: str, reason: str, item: dict | None = None) -> None:
    with _stats_lock:
        _stats[bucket] = _stats.get(bucket, 0) + 1
        _stats["reasons"][reason] = _stats["reasons"].get(reason, 0) + 1
        if bucket == "deferred" and item and item.get("url"):
            _deferred_urls.add(item["url"])


def deferred_urls() -> set:
    """本轮被成本闸拦下的 url。pipeline 用它决定哪些条目**不能**标记消费。"""
    with _stats_lock:
        return set(_deferred_urls)


def record_deferred(conn, staging_ids: list, reason: str) -> int:
    """把"这些条目因为成本闸被跳过"落库，供 backlog 端点与看板查询。

    刻意**不**动 consumed_at —— 跳过的条目必须留在待办队列里，
    等公司 key 恢复或 Mac 上线后被自然重新领取。这正是"自动回补"的地基：
    回补不需要额外的补数脚本，只要跳过时什么都别标记就行。
    """
    if not staging_ids:
        return 0
    try:
        cur = conn.cursor()
        placeholders = ", ".join(["%s"] * len(staging_ids))
        cur.execute(
            f"""UPDATE raw_items_staging
                   SET deferred_count   = deferred_count + 1,
                       last_deferred_at = NOW(),
                       defer_reason     = %s
                 WHERE id IN ({placeholders})""",
            (reason[:64], *staging_ids))
        n = cur.rowcount
        conn.commit()
        cur.close()
        return n
    except Exception as e:
        logger.warning(f"成本闸：defer 留痕失败（{e}）")
        return 0


def stats() -> dict:
    """本轮统计快照，run_pipeline 收尾时写进 pipeline_runs。"""
    with _stats_lock:
        return {"allowed": _stats["allowed"], "deferred": _stats["deferred"],
                "reasons": dict(_stats["reasons"])}


def reset_stats() -> None:
    global _last_reason
    with _stats_lock:
        _stats["allowed"] = 0
        _stats["deferred"] = 0
        _stats["reasons"] = {}
        _deferred_urls.clear()
    _last_reason = "not_evaluated"


# ── 对外：开关操作（给 CLI / API 用）─────────────────────────────────

def enable(conn, hours: float = 6.0, who: str = "cli", note: str = "") -> dict:
    """紧急开启个人 key。**必须**带失效时间，最长 24 小时。

    没有"永久开启"这个选项，这是刻意的：需求原话是个人 key"只在紧急情况用"，
    而紧急是有时限的。真需要长期开，就重复执行本命令——让"还开着"这件事
    始终是一个需要主动维持的状态，而不是一个会被遗忘的状态。
    """
    hours = max(0.1, min(24.0, float(hours)))
    from datetime import timedelta
    expires = _now().replace(tzinfo=None) + timedelta(hours=hours)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO runtime_flags (flag_key, flag_value, expires_at, updated_by, note)
           VALUES (%s, '1', %s, %s, %s)
           ON DUPLICATE KEY UPDATE flag_value='1', expires_at=VALUES(expires_at),
                                   updated_by=VALUES(updated_by), note=VALUES(note)""",
        (FLAG_ALLOW_PERSONAL, expires, who[:64], note or f"紧急启用 {hours}h"))
    conn.commit()
    cur.close()
    _invalidate_cache()
    logger.warning(f"成本闸：个人 key 已启用，{expires} 自动失效（{who}）")
    return {"enabled": True, "expires_at": expires.isoformat(), "hours": hours}


def disable(conn, who: str = "cli") -> dict:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO runtime_flags (flag_key, flag_value, expires_at, updated_by, note)
           VALUES (%s, '0', NULL, %s, '手动关闭')
           ON DUPLICATE KEY UPDATE flag_value='0', expires_at=NULL,
                                   updated_by=VALUES(updated_by), note=VALUES(note)""",
        (FLAG_ALLOW_PERSONAL, who[:64]))
    conn.commit()
    cur.close()
    _invalidate_cache()
    logger.info(f"成本闸：个人 key 已关闭（{who}）")
    return {"enabled": False}


def status(conn=None) -> dict:
    """当前闸口状态，给 API / 看板用。"""
    values = _load_flags(conn)
    env_on = os.environ.get(ENV_ESCAPE_HATCH) == "1"
    expires = None
    try:
        own = False
        if conn is None:
            from . import storage
            conn = storage.get_mysql_conn()
            own = True
        cur = conn.cursor()
        cur.execute("SELECT expires_at FROM runtime_flags WHERE flag_key=%s",
                    (FLAG_ALLOW_PERSONAL,))
        row = cur.fetchone()
        expires = row[0].isoformat() if row and row[0] else None
        cur.close()
        if own:
            conn.close()
    except Exception:
        pass
    return {
        "personal_key_enabled": env_on or values.get(FLAG_ALLOW_PERSONAL) == "1",
        "via_env_escape_hatch": env_on,
        "expires_at": expires,
        "emergency_max_priority": _int_flag(values, FLAG_MAX_PRIORITY),
        "emergency_daily_item_cap": _int_flag(values, FLAG_DAILY_CAP),
        "round_stats": stats(),
    }


def _invalidate_cache() -> None:
    with _flag_lock:
        _flag_cache["at"] = 0.0
        _flag_cache["values"] = {}
