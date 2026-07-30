"""排序策略配置读写 —— api/strategy_config.py（2026-07-30）

配套 `config/migrations/016_strategy_config.sql`（表结构与设计取舍见那个文件的
头部注释）。本模块负责三件事：**读当前生效配置**、**存新基线**、**回滚到旧版本**。

## 设计原则：配置永远不能让排序坏掉

排序是这个产品的主路径，配置表是它新增的一个依赖——依赖越多，坏掉的方式越多。
所以这里的每一处失败都必须**退化成"用代码里的默认值"，而不是抛异常**：

  · 表不存在（迁移没跑）        → 返回 DEFAULTS
  · 表是空的                    → 返回 DEFAULTS
  · payload 不是合法 JSON       → 返回 DEFAULTS
  · payload 缺字段 / 类型不对   → 用 DEFAULTS 逐项补齐，只接受合法的那部分
  · 数据库连不上                → 返回 DEFAULTS

反过来，**写入路径必须严格**：`validate()` 拒绝任何不认识的键、越界的值、
归一化对不上的权重组。宽进严出在这里是反的——读要宽（不能让前端白屏），
写要严（不能让一份坏配置变成 active 之后污染所有人）。

## 为什么校验放在这里而不是前端

前端校验只能防手滑，防不住直接打 API。而这张表一旦写进一份坏配置并置为
active，影响面是全站排序。校验必须在写入这一侧，前端那份只是体验优化。
"""
import copy
import json
import logging

logger = logging.getLogger(__name__)

# 七个基础因子的键，与 api/lab_tools.py 的 FACTOR_KEYS 对齐（Rel 不在这里：
# 它是 Sector Insight 模式下的板块相关性，属于「查询时选了哪个板块」而不是
# 「全站基线策略」，不进基线配置）。
BASE_KEYS = ("M", "B", "T", "I", "H", "A", "Q")

MARKET_KEYS = ("us_stock", "crypto", "macro_policy", "social_signal",
               "general", "hk_stock", "jp_stock", "kr_stock")

# 与各模块代码里的现行值逐项对齐——见 016 迁移文件里的对应关系表。
# 这份 DEFAULTS 同时是「配置读不到时的兜底」和「校验时补齐缺失字段的来源」。
DEFAULTS = {
    "base_weights": {"M": 26, "B": 16, "T": 16, "I": 14, "H": 10, "A": 10, "Q": 8},
    "bonus": {"k_align": 0.25, "k_reversal": 0.20, "cap": 0.50},
    "market_weights": {"us_stock": 1.20, "crypto": 1.00, "macro_policy": 1.00,
                       "social_signal": 0.85, "general": 0.70, "hk_stock": 0.65,
                       "jp_stock": 0.60, "kr_stock": 0.55},
    "freshness": {"halflife_hours": 48, "floor": 0.15, "enabled": True},
    "mood": {"lookback_hours": 24, "manual_override": None},
}

# 各字段的允许区间。超界直接拒绝而不是夹紧——夹紧会让"我明明填了 500"
# 变成静默的 200，用户以为生效了其实没有，比报错更难查。
_RANGES = {
    "bonus": {"k_align": (0.0, 1.0), "k_reversal": (0.0, 1.0), "cap": (0.0, 2.0)},
    "freshness": {"halflife_hours": (1.0, 720.0), "floor": (0.0, 1.0)},
    "mood": {"lookback_hours": (1, 720), "manual_override": (-1.0, 1.0)},
    "market": (0.0, 2.0),      # 与 crawler/market_weight.py 的 MIN/MAX_WEIGHT 一致
    "base": (0.0, 100.0),
}


class ConfigError(ValueError):
    """校验失败。调用方应转成 HTTP 400 并把 message 原样给前端。"""


def _num(value, field):
    if isinstance(value, bool):    # bool 是 int 的子类，必须先挡掉
        raise ConfigError(f"{field} 需要数字，收到布尔值")
    if not isinstance(value, (int, float)):
        raise ConfigError(f"{field} 需要数字，收到 {type(value).__name__}")
    return float(value)


def _check_range(value, lo, hi, field):
    if not (lo <= value <= hi):
        raise ConfigError(f"{field} 超出允许范围 [{lo}, {hi}]，收到 {value}")
    return value


def validate(payload: dict) -> dict:
    """校验并归一成一份完整配置。任何一项不合法直接抛 ConfigError。

    缺失的整节用 DEFAULTS 补（允许只提交想改的那部分），但**节内不允许缺键**
    ——半份权重表算出来的分没有意义，见 016 迁移文件的说明。
    """
    if not isinstance(payload, dict):
        raise ConfigError("配置必须是对象")

    unknown = set(payload) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"不认识的配置节：{sorted(unknown)}")

    out = copy.deepcopy(DEFAULTS)

    # ── 基础因子权重 ──────────────────────────────────────────────
    if "base_weights" in payload:
        bw = payload["base_weights"]
        if not isinstance(bw, dict):
            raise ConfigError("base_weights 必须是对象")
        missing = set(BASE_KEYS) - set(bw)
        if missing:
            raise ConfigError(f"base_weights 缺少因子：{sorted(missing)}")
        extra = set(bw) - set(BASE_KEYS)
        if extra:
            raise ConfigError(f"base_weights 含未知因子：{sorted(extra)}")
        lo, hi = _RANGES["base"]
        vals = {k: _check_range(_num(bw[k], f"base_weights.{k}"), lo, hi,
                                f"base_weights.{k}") for k in BASE_KEYS}
        total = sum(vals.values())
        if total <= 0:
            raise ConfigError("base_weights 合计必须大于 0")
        # 归一化到 100：实验室滑杆本来就是按份额语义展示的，这里统一成
        # 「存进去的一定是归一化后的值」，避免下游每次读都要再判断一次。
        out["base_weights"] = {k: round(v * 100.0 / total, 4) for k, v in vals.items()}

    # ── 情绪加分项 ────────────────────────────────────────────────
    if "bonus" in payload:
        b = payload["bonus"]
        if not isinstance(b, dict):
            raise ConfigError("bonus 必须是对象")
        extra = set(b) - set(DEFAULTS["bonus"])
        if extra:
            raise ConfigError(f"bonus 含未知字段：{sorted(extra)}")
        for k, (lo, hi) in _RANGES["bonus"].items():
            if k in b:
                out["bonus"][k] = _check_range(_num(b[k], f"bonus.{k}"), lo, hi, f"bonus.{k}")
        if out["bonus"]["k_align"] + out["bonus"]["k_reversal"] > out["bonus"]["cap"] + 1e-9:
            # 不自动夹紧：两个系数之和超过封顶说明用户对封顶的理解和实现不一致，
            # 这时候静默截断会让实验室显示的加成和实际生效的对不上。
            raise ConfigError(
                f"同向({out['bonus']['k_align']}) + 反转({out['bonus']['k_reversal']}) "
                f"超过封顶 {out['bonus']['cap']}，请调低系数或提高封顶")

    # ── 市场重要性 ────────────────────────────────────────────────
    if "market_weights" in payload:
        mw = payload["market_weights"]
        if not isinstance(mw, dict):
            raise ConfigError("market_weights 必须是对象")
        extra = set(mw) - set(MARKET_KEYS)
        if extra:
            raise ConfigError(f"market_weights 含未知市场：{sorted(extra)}")
        lo, hi = _RANGES["market"]
        for k in MARKET_KEYS:
            if k in mw:
                out["market_weights"][k] = _check_range(
                    _num(mw[k], f"market_weights.{k}"), lo, hi, f"market_weights.{k}")

    # ── 新鲜度衰减 ────────────────────────────────────────────────
    if "freshness" in payload:
        f = payload["freshness"]
        if not isinstance(f, dict):
            raise ConfigError("freshness 必须是对象")
        extra = set(f) - set(DEFAULTS["freshness"])
        if extra:
            raise ConfigError(f"freshness 含未知字段：{sorted(extra)}")
        for k, (lo, hi) in _RANGES["freshness"].items():
            if k in f:
                out["freshness"][k] = _check_range(_num(f[k], f"freshness.{k}"), lo, hi,
                                                   f"freshness.{k}")
        if "enabled" in f:
            if not isinstance(f["enabled"], bool):
                raise ConfigError("freshness.enabled 必须是布尔值")
            out["freshness"]["enabled"] = f["enabled"]

    # ── 大盘情绪 ──────────────────────────────────────────────────
    if "mood" in payload:
        m = payload["mood"]
        if not isinstance(m, dict):
            raise ConfigError("mood 必须是对象")
        extra = set(m) - set(DEFAULTS["mood"])
        if extra:
            raise ConfigError(f"mood 含未知字段：{sorted(extra)}")
        if "lookback_hours" in m:
            lo, hi = _RANGES["mood"]["lookback_hours"]
            out["mood"]["lookback_hours"] = int(_check_range(
                _num(m["lookback_hours"], "mood.lookback_hours"), lo, hi, "mood.lookback_hours"))
        if "manual_override" in m:
            mo = m["manual_override"]
            # None 是合法值且语义明确：用实时计算的情绪，不做人工干预。
            if mo is None:
                out["mood"]["manual_override"] = None
            else:
                lo, hi = _RANGES["mood"]["manual_override"]
                out["mood"]["manual_override"] = _check_range(
                    _num(mo, "mood.manual_override"), lo, hi, "mood.manual_override")

    return out


def _coerce(raw) -> dict:
    """把库里读出来的 payload 宽松地补成一份完整配置（读路径，见模块说明）。"""
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            logger.warning("strategy_config payload 不是合法 JSON，回退默认值")
            return copy.deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return copy.deepcopy(DEFAULTS)

    out = copy.deepcopy(DEFAULTS)
    for section, defaults in DEFAULTS.items():
        got = raw.get(section)
        if not isinstance(got, dict):
            continue
        for key in defaults:
            if key in got:
                out[section][key] = got[key]
    return out


def get_active(conn) -> dict:
    """当前生效配置。任何异常都退化成 DEFAULTS——排序不能因为配置表而挂。"""
    try:
        cur = conn.cursor()
        cur.execute("SELECT payload, version FROM strategy_config WHERE is_active = 1 LIMIT 1")
        row = cur.fetchone()
        cur.close()
    except Exception as e:
        logger.warning(f"读取 strategy_config 失败，回退默认值：{e}")
        return {**copy.deepcopy(DEFAULTS), "_version": 0, "_fallback": True}

    if not row:
        return {**copy.deepcopy(DEFAULTS), "_version": 0, "_fallback": True}

    cfg = _coerce(row[0])
    cfg["_version"] = int(row[1])
    cfg["_fallback"] = False
    return cfg


def list_versions(conn, limit: int = 30) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT version, note, created_by, is_active, created_at, is_prod, payload "
        "FROM strategy_config ORDER BY version DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    cur.close()
    # payload 一并返回（版本管理弹窗要"点开看具体参数"）——整表也就几十行、
    # 每行 <1KB，全量带出去比再做一个按版本取参数的端点简单得多。
    return [{"version": r[0], "note": r[1], "created_by": r[2],
             "is_active": bool(r[3]),
             "created_at": r[4].isoformat() if r[4] else None,
             "is_prod": bool(r[5]),
             "payload": _coerce(r[6])} for r in rows]


def get_prod(conn) -> dict | None:
    """当前部署到生产的配置；**没有部署过任何版本时返回 None**。

    None 与「回退默认值」在这里是两个语义：None = 生产仍走旧路径（存量
    importance_score 排序），调用方据此保持迁移前行为；一旦有版本被部署，
    读失败才回退 DEFAULTS（生产不能因为配置表抖动而挂）。"""
    try:
        cur = conn.cursor()
        cur.execute("SELECT payload, version FROM strategy_config WHERE is_prod = 1 LIMIT 1")
        row = cur.fetchone()
        cur.close()
    except Exception as e:
        logger.warning(f"读取生产配置失败，按未部署处理：{e}")
        return None
    if not row:
        return None
    cfg = _coerce(row[0])
    cfg["_version"] = int(row[1])
    return cfg


def deploy_to_prod(conn, version: int) -> dict:
    """把某个版本部署到生产（is_prod 唯一指针挪过去）。不动 is_active——
    实验室默认和生产运行是两个独立指针，见 migration 017 说明。"""
    cur = conn.cursor()
    try:
        cur.execute("SELECT payload FROM strategy_config WHERE version = %s", (version,))
        row = cur.fetchone()
        if not row:
            raise ConfigError(f"版本 {version} 不存在")
        cur.execute("UPDATE strategy_config SET is_prod = 0 WHERE is_prod = 1")
        cur.execute("UPDATE strategy_config SET is_prod = 1, deployed_at = NOW() "
                    "WHERE version = %s", (version,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    cfg = _coerce(row[0])
    cfg["_version"] = version
    return cfg


def save_baseline(conn, payload: dict, note: str | None = None,
                  created_by: str = "lab") -> dict:
    """校验 → 追加新版本 → 置为唯一 active。返回新版本号与生效配置。

    先把旧的 active 清零再插新行：uk_active 唯一索引不允许两行同时 active，
    顺序反过来会直接撞唯一键。整个过程在一个事务里，中途失败不会留下
    "全表没有 active" 的空窗。
    """
    clean = validate(payload)          # 失败直接抛 ConfigError，不碰数据库

    cur = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM strategy_config")
        next_version = int(cur.fetchone()[0])
        cur.execute("UPDATE strategy_config SET is_active = 0 WHERE is_active = 1")
        cur.execute(
            "INSERT INTO strategy_config (version, payload, note, created_by, is_active) "
            "VALUES (%s, %s, %s, %s, 1)",
            (next_version, json.dumps(clean, ensure_ascii=False), note, created_by))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    clean["_version"] = next_version
    clean["_fallback"] = False
    return clean


def rollback(conn, version: int) -> dict:
    """把某个历史版本重新置为 active。**不删除任何行、也不复制成新版本**
    ——回滚后 version 号仍然是那个旧号，历史因此保持线性可读（"现在跑的是
    v3" 比 "现在跑的是 v7，内容和 v3 一样" 更容易对账）。"""
    cur = conn.cursor()
    try:
        cur.execute("SELECT payload FROM strategy_config WHERE version = %s", (version,))
        row = cur.fetchone()
        if not row:
            raise ConfigError(f"版本 {version} 不存在")
        cur.execute("UPDATE strategy_config SET is_active = 0 WHERE is_active = 1")
        cur.execute("UPDATE strategy_config SET is_active = 1 WHERE version = %s", (version,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    cfg = _coerce(row[0])
    cfg["_version"] = version
    cfg["_fallback"] = False
    return cfg
