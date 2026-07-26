"""项目统一时间基准 —— UTC+8（Asia/Shanghai）。

2026-07-26 Lawrence："这个项目的所有时间都改成 utc+8"。

那次改动只切了 VM 系统时区、cron 和 MySQL，**代码里的写入口径漏了**：
`storage.write_events()` 仍然用 `datetime.now(timezone.utc)` 给 time_get_data
盖戳，于是 20:00 那轮的事件被写成 12:xx，前端「生产轮次」下拉里直接少了一整轮
（08:00 桶里混进了晚间轮的数据）。这个文件就是为了让"现在几点"只有一个答案。

用法约定：
  - 需要"当前时间"→ `now_local()`，返回 **aware** datetime（tzinfo=UTC+8）
  - 需要写进 MySQL DATETIME 列 → `local_str()` / `to_mysql_datetime()`
  - 不要再直接写 `datetime.now(timezone.utc)` 或 `datetime.utcnow()`

为什么返回 aware 而不是 naive：两个 aware datetime 相减得到的是真实时间差，
与各自挂的时区无关。所以把 now 从 UTC-aware 换成 +08-aware，**所有新鲜度/
时效性计算的结果一字不变**，变的只是"落库时打印成什么字符串"。这也是这次
迁移能安全做的原因。

固定 +08:00 而不是读系统时区：VM 的 TZ 是可以被人改掉的，而这套数据的口径
必须稳定；中国不使用夏令时，固定偏移不会有 DST 陷阱。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# 项目唯一时间基准。改这一个常量就能整体迁移到别的时区。
PROJECT_TZ = timezone(timedelta(hours=8), name="UTC+8")

MYSQL_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


def now_local() -> datetime:
    """当前时间，tz-aware，UTC+8。取代所有 datetime.now(timezone.utc)。"""
    return datetime.now(PROJECT_TZ)


def local_str(dt: datetime | None = None) -> str:
    """aware/naive datetime → UTC+8 的 MySQL DATETIME 字符串。

    naive 输入按"已经是 UTC+8"处理（历史遗留的裸字符串走这条路）。
    """
    dt = dt or now_local()
    if dt.tzinfo is None:
        return dt.strftime(MYSQL_DATETIME_FMT)
    return dt.astimezone(PROJECT_TZ).strftime(MYSQL_DATETIME_FMT)


def since_str(*, hours: int = 0, days: int = 0) -> str:
    """「N 小时/天以前」的 UTC+8 字符串，用于和 DB 里的 DATETIME 列比较。

    这类 since 条件必须和列本身同口径，否则窗口会整体偏 8 小时——
    跨轮归并的 72h 窗口曾经就是这样悄悄变成 80h 的。
    """
    return local_str(now_local() - timedelta(hours=hours, days=days))


def to_mysql_datetime(value: str | None) -> str | None:
    """ISO8601（含 T/Z/毫秒/时区）→ UTC+8 的 MySQL DATETIME 字符串。

    历史 bug：X API 返回 '2026-07-25T14:02:54.000Z'，MySQL DATETIME 直接拒绝，
    曾导致 77 条 X 事件静默丢失。所有入库时间都必须过这个函数。

    带时区的输入会被换算到 UTC+8（'…14:02:54Z' → '2026-07-25 22:02:54'）；
    不带时区的输入视为已经是 UTC+8，原样保留。
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return local_str(dt)
