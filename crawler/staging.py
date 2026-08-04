"""
原始条目存档层 —— 解耦"抓取频率"与"LLM 处理频率"。

背景（2026-07-26）：cron 从每 4 小时改成每 12 小时降本后，排查漏召案例
（Triple-A 支付平台被盗事件）发现：吴说等高频源的 RSS 是服务端固定窗口
（约 30-50 条），12 小时间隔会让发布密集的源把窗口内的旧内容挤出去——
不是我们的新鲜度过滤或去重误杀（两者实测误杀率均为 0），是内容在我们
抓取之前就已经从源头消失了。

抓取 RSS/HTML/搜索引擎本身不花钱，真正的成本大头是下游 LLM 结构化
（`crawler/pipeline.py:enrich_one`，约 $0.0076/条）。所以把两件事分开：

    高频（如每 1-2 小时，由 scripts/stage_fetch.py 独立 cron 调用）
        跑 crawler.main.fetch_cheap_sources()，只做「抓取 + 存档」，
        不进 LLM，成本接近 0

    低频（现有 12 小时 pipeline 节奏不变）
        pipeline.run_pipeline() 从存档表里捞出所有未消费的条目，
        叠加当轮实时抓取的 X（KOL + 搜索，按用户要求维持原节奏不提速），
        走原有的 粗去重 → LLM → 聚合 → 打分 → 入库

这样高频源不再受 12 小时窗口限制而滚屏丢失，但 LLM 调用次数和频率完全不变。

X 不走存档：按用户明确要求，"除了 X 这种要 API 额度的接口，其它都可以更高频
拉取"——X 维持现有节奏，不加入这条高频路径。
"""
import hashlib
import logging
import os
from datetime import datetime, timezone
from .dxfeed_news import DXFEED_INDEX_SYMBOLS
from .timeutil import now_local

logger = logging.getLogger(__name__)


def _url_hash(url: str) -> str:
    return hashlib.sha256((url or "").strip().rstrip("/").encode()).hexdigest()


# 公开别名：enrich bridge（本地 Claude 预处理缓存）用同一把尺子算 key，
# 保证 staging 表、缓存表、pipeline 三方对同一 url 算出同一个 hash。
url_hash = _url_hash


# ── 处理优先级（PRD-03 R1 / ADR-001 D4）─────────────────────────────
#
# 起因：实测 301 条权威大盘源（CNBC/MarketWatch/Nikkei…）已抓回，只有 8 条被
# 处理过——它们排在几百条 dxFeed 个股新闻和长尾 RSS 后面。CNBC 首页那种
# 「大盘级、有冲击力」的内容因此迟迟进不了事件库。
#
# 用**优先级**而不是**过滤**：Lawrence 明确要保留 dxFeed 个股的大底池。
# 过滤不可逆（今天丢掉的以后要不回来），优先级可逆（随时能调档）。
#
# 值越小越先处理。默认 3（中间档）——新接入的源在没被显式归档前既不会
# 意外插队、也不会饿死。
PRIORITY_AUTHORITATIVE_MACRO = 0   # 权威大盘媒体
PRIORITY_DXFEED_INDEX        = 1   # dxFeed 大盘/ETF symbol
PRIORITY_CRYPTO_TOP          = 2   # 加密头部媒体 + 行情异动
PRIORITY_DEFAULT             = 3   # 其他 RSS / 搜索召回
PRIORITY_DXFEED_SINGLE       = 4   # dxFeed 个股 symbol

_AUTHORITATIVE_MACRO_SOURCES = {
    "CNBC-TopNews", "CNBC-Economy", "CNBC-Investing", "CNBC-Finance",
    "MarketWatch", "NikkeiAsia", "SCMP-GlobalEcon", "SCMP-Business",
    "KoreaHerald", "Reuters", "Bloomberg",
    # 2026-07-29：crawler/sources.py 新接的 Bloomberg/Forbes RSS 用的是带频道
    # 后缀的名字（"Bloomberg-Markets" 不是 "Bloomberg"）——resolve_priority 是
    # 精确字符串匹配，不改这里的话，这批新源会静默落到默认的 P3，跟"插队优先
    # 处理"的需求原意（"把 CNBC 等权威媒体拉回来的数据插队优先处理"）正好相反。
    # 这正是本项目这一周反复出现的同一类问题——新老命名对不上，问题不报错，
    # 只是静默地不生效——这次是在部署前发现的，不是事后查出来的。
    "Bloomberg-Markets", "Bloomberg-Economics", "Bloomberg-Technology",
    "Bloomberg-Politics", "Forbes-Business", "WSJ-Markets", "FT-Home",
    # 2026-07-30：Benzinga（经 Massive 平台直连 API）——原生结构化实时源，
    # 发布即可抓取，同样归入"实时性要更强"这批优先处理（见 crawler/
    # benzinga_news.py 模块说明：优先级和 authority 是独立的两条轴线，
    # 这里只提优先级，不改 authority）。
    "Benzinga",
}

# 加密侧的头部媒体（authority 5 的那批）+ 行情异动信号
_CRYPTO_TOP_SOURCES = {
    "CoinDesk", "TheBlock", "吴说区块链", "BlockBeats快讯", "币安上币公告",
    "market_signal",
}


def resolve_priority(item: dict) -> int:
    """按信源与 dxFeed symbol 归属定处理优先级。纯函数，便于单测。"""
    source = (item.get("source") or "").strip()

    if source in _AUTHORITATIVE_MACRO_SOURCES:
        return PRIORITY_AUTHORITATIVE_MACRO

    if source.startswith("dxFeed"):
        # 命中大盘/ETF symbol 的走高优先级，纯个股的垫底。
        # 一条新闻同时挂大盘和个股时按大盘算——它能影响指数，就是大盘级信息。
        symbols = {s.strip() for s in (item.get("matched_symbols") or "").split(",") if s.strip()}
        if symbols & DXFEED_INDEX_SYMBOLS:
            return PRIORITY_DXFEED_INDEX
        return PRIORITY_DXFEED_SINGLE

    if source in _CRYPTO_TOP_SOURCES or (item.get("type") == "market_signal"):
        return PRIORITY_CRYPTO_TOP

    return PRIORITY_DEFAULT


def stage_items(items: list[dict], conn) -> dict:
    """把抓到的条目写入存档表，按 url 去重（重复 url 只更新 fetched_at）。

    返回 {"new": 新增条数, "duplicate": 已存在条数}——duplicate 高不代表抓取
    有问题，相邻两次高频抓取本来就该有大量重叠，这正是"提高抓取频率、
    降低滚屏丢失概率"这个设计要生效的地方。
    """
    if not items:
        return {"new": 0, "duplicate": 0}

    cursor = conn.cursor()
    new_count = duplicate_count = 0

    for item in items:
        url = item.get("url", "")
        if not url:
            continue
        url_hash = _url_hash(url)
        try:
            cursor.execute(
                """INSERT INTO raw_items_staging
                   (source, title, url, url_hash, summary, published_at,
                    lang, authority, type, priority, matched_symbols)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE fetched_at = CURRENT_TIMESTAMP,
                       -- 优先级取更高档（数值更小）：同一条 url 可能先由长尾源
                       -- 抓到、后来权威源也发了，此时该按权威源的档位处理。
                       priority = LEAST(priority, VALUES(priority)),
                       matched_symbols = COALESCE(VALUES(matched_symbols), matched_symbols)""",
                (item.get("source", ""), item.get("title", ""), url, url_hash,
                 item.get("summary", ""), item.get("published_at", ""),
                 item.get("lang", "en"), item.get("authority", 3),
                 item.get("type", "rss"), resolve_priority(item),
                 item.get("matched_symbols") or None),
            )
            if cursor.rowcount == 1:  # INSERT 走的是 1，UPDATE 分支走的是 2
                new_count += 1
            else:
                duplicate_count += 1
        except Exception as e:
            logger.warning(f"Stage failed for {url[:80]}: {e}")

    conn.commit()
    cursor.close()
    logger.info(f"Staging: {new_count} new, {duplicate_count} duplicate "
               f"(of {len(items)} fetched)")
    return {"new": new_count, "duplicate": duplicate_count}


# 单轮消费上限（2026-07-28 加，配合 pipeline 从每2天1轮改为每小时1轮）。
#
# 改成每小时之前这里没有上限是安全的——两天才跑一次，一次把攒下的全吃掉正是
# 想要的行为。改成每小时之后，无上限有两个真问题：
#   1. 存量积压（当时 3468 条）会在第一次触发时被一口气送进 LLM，单轮跑几小时、
#      费用集中爆发，且期间下一个整点的 cron 会照常触发造成叠跑；
#   2. 任何一次抓取异常导致的积压堆积都会以同样方式放大。
# 400 的取法：每轮 stage_fetch 实测新增约 180 条，400 给了 2 倍余量能持续追平
# 增量，同时把积压按每小时 400 条的速度平滑消化（3468 条约 9 小时化完），
# 而 Mac 侧 enrich worker 的吞吐是 1200 条/小时（25 req/min × 4 次唤醒），
# 跑在前面把这些条目预处理成缓存命中——所以这个速度差是刻意的：让免费的
# 那条腿始终领先于付费的那条腿。
MAX_ITEMS_PER_RUN = int(os.environ.get("B9_PIPELINE_BATCH", "400"))

# 已停用信源的黑名单——消费端的闸。抓取端的开关在 crawler/main.py
# （BINANCE_SQUARE_ENABLED），但那只能拦住"以后不再抓"，拦不住 staging 里
# 的历史存量继续被送进 LLM 并入库。
#
# SQL 里必须按数量展开成 %s,%s,...：`NOT IN %s` 直接传元组是 psycopg2 的行为，
# mysql-connector 会直接报 "Python type tuple cannot be converted"。
DISABLED_SOURCES = ("BinanceSquare",)


# 积压回溯窗口。2026-08-02（ADR-002 A3）由 7 天放宽到 30 天。
#
# 起因是需求"重新开启后重新扫描并处理积压"暴露的结构性障碍：这个窗口和
# /api/enrich/pending 的同名窗口是**数据能不能回补的硬天花板**——公司 key 断供
# 或 Mac 离线一旦超过窗口天数，那批条目就再也不会被任何一方取走，而且是静默的
# （没有报错、没有计数，只是查询条件把它们排除掉了）。7 天对"每 7 天轮换一次
# key"的节奏毫无余量：轮换晚一天就开始丢数据。
#
# 30 天的代价是 staging 表变大（约 6000 条/天 → 约 18 万行），已配套加了
# idx_unconsumed_age 复合索引（migration 018）。
STAGING_MAX_AGE_DAYS = int(os.environ.get("B9_STAGING_MAX_AGE_DAYS", "30"))


def fetch_staged_items(conn, max_age_days: int | None = None) -> list[dict]:
    """只读取（不标记）未消费的存档条目，返回可直接送入 pipeline 的 item 列表。

    2026-07-26 review 修复（HIGH）：旧版 consume_staged_items 在 SELECT 之后
    立即标记 consumed_at 并 commit，而 pipeline 真正写库要到十几分钟之后的
    Step 8——中间任何一步（实时抓 X 的网络异常、LLM 全面故障、进程被杀）失败，
    整批条目就永久丢失：没有任何代码会把 consumed_at 置回 NULL，且 stage_items
    的 ON DUPLICATE 只刷新 fetched_at，同 URL 再被高频 cron 抓到也不会复活。
    现在拆成 fetch（这里）+ mark_staged_consumed（写库成功后由 pipeline 调用）：
    中途崩溃 → 什么都没标记 → 下一轮原样重取。代价是"写库成功但标记前崩溃"
    会重付一次 LLM 费用（写库有指纹幂等键，数据不会重）——用小概率的钱换
    数据不丢，值得。

    `max_age_days` 兜底：防存档表堆积时把过老内容当"新鲜存货"送进 LLM。
    不传则用 STAGING_MAX_AGE_DAYS（30 天，见该常量的说明——它同时是"断供多久
    之内的数据还能回补"的硬天花板）。
    """
    if max_age_days is None:
        max_age_days = STAGING_MAX_AGE_DAYS
    cursor = conn.cursor(dictionary=True)
    disabled_ph = ", ".join(["%s"] * len(DISABLED_SOURCES))
    cursor.execute(
        # 投影列表：新增字段**必须同步加到这里**，否则下游拿到的永远是 None
        # 且不报错。本项目已经栽过 4 次（EVENT_COLUMNS 少 4 列让广度因子恒为
        # 默认值、_get_market_mood 少 3 列让新鲜度衰减恒为 1.0…）。这次一次补两个：
        #   · priority        —— 成本闸紧急模式按它过滤档位；不取的话
        #                        item.get("priority") 恒为 None，档位闸静默失效
        #   · matched_symbols —— Benzinga/dxFeed 编辑部标注的真实 ticker，
        #                        98.1%/95% 覆盖率，此前一路取不到，交易实体
        #                        因此全靠 LLM 猜（实测美股侧覆盖率仅 0.8%）
        f"""SELECT id, source, title, url, summary, published_at, lang, authority,
                  type, priority, matched_symbols
           FROM raw_items_staging
           WHERE consumed_at IS NULL
             AND fetched_at >= NOW() - INTERVAL %s DAY
             -- 被停用的信源不但要停止抓取，**存量也必须停止消费**。
             -- 2026-07-29 实测：币安广场（无发布时间，是陈旧新闻事故的源头）
             -- 在 crawler/main.py 里已经关了抓取开关，但 staging 里还压着 119
             -- 条历史存货，流水线照常把它们捞出来送进 LLM，又入库了 3 条——
             -- QA 红线因此重新亮红。关水龙头不等于清管道，两头都要堵。
             AND source NOT IN ({disabled_ph})
           -- 优先级在前、时间在后：权威大盘媒体插队（PRD-03 R1）。
           --
           -- 2026-08-04 同优先级内改成"新的先出"（DESC）。原来是 FIFO，停摆 3 天
           -- 攒到 1.1 万条后暴露了问题：恢复时先啃两天前的稿子，首屏全是旧闻，
           -- 而大盘情绪取 24h 窗口一直算不出来——队列在追平，产品还是坏的。
           -- 新闻价值随时间衰减，排队久不该获得优先权。
           --
           -- ⚠️ 这个 ORDER BY 必须与 api/enrich_bridge.py 的派活 SQL 逐字一致：
           -- 派活侧（Mac 算什么）与消费侧（pipeline 取什么）一旦错位，pipeline 取到的
           -- 800 条正好是桥没算过的，llm_cache_hits 会直接掉到 0，表现为"worker 明明
           -- 在跑、事件却一条不涨"。QA 有断言钉住两处一致。
           ORDER BY priority ASC, fetched_at DESC
           LIMIT %s""",
        (max_age_days, *DISABLED_SOURCES, MAX_ITEMS_PER_RUN),
    )
    rows = cursor.fetchall()
    cursor.close()

    if not rows:
        logger.info("Staging: no unconsumed items")
        return []

    if len(rows) >= MAX_ITEMS_PER_RUN:
        # 触顶要显式说出来：否则"每轮都恰好 400 条"看起来像正常水位，
        # 实际是积压在涨而这轮只啃掉了一部分（静默截断 = 看起来覆盖全了但没有）。
        cur2 = conn.cursor()
        cur2.execute("SELECT COUNT(*) FROM raw_items_staging WHERE consumed_at IS NULL")
        backlog = cur2.fetchone()[0]
        cur2.close()
        logger.warning(
            f"Staging: 本轮取满上限 {MAX_ITEMS_PER_RUN} 条，未消费积压仍有 {backlog} 条"
            f"（按每小时 {MAX_ITEMS_PER_RUN} 条消化，约需 {backlog // MAX_ITEMS_PER_RUN + 1} 小时追平）")

    items = [{
        "_staging_id": r["id"],   # 供 mark_staged_consumed 回标；下游不消费此键
        "source": r["source"], "title": r["title"], "url": r["url"],
        "summary": r["summary"] or "", "published_at": r["published_at"] or "",
        "lang": r["lang"] or "en", "authority": r["authority"] or 3,
        "type": r["type"] or "rss",
        # 取到了就要传下去——SELECT 补了列却忘了往 item 里塞，等于没补。
        "priority": r["priority"],
        "matched_symbols": r["matched_symbols"] or "",
    } for r in rows]
    logger.info(f"Staging: fetched {len(items)} unconsumed items (not yet marked)")
    return items


def mark_staged_consumed(conn, staged_items: list[dict],
                         deferred_urls: set | None = None) -> None:
    """写库成功后统一标记本轮取走的存档条目。只在 pipeline 的 Step 9 之后调用。

    `deferred_urls`：**被成本闸拦下**的 url 集合（llm_gate.deferred_urls()）。
    这些**不**标记消费，原样留在队列里等公司额度或紧急开闸；其余一律标记。

    2026-08-02（ADR-002）加这个参数，起因是成本闸的端到端验证：闸口关闭时
    `enrich_one` 返回 None、条目被丢弃，但这里照样把**本轮取出的全部**条目
    标记成已消费——桥再也领不到它们，数据永久丢失。这与"断供期间数据不丢、
    恢复后自动回补"的需求正好相反，而且是静默的（日志只说 marked N items）。

    **口径必须是"排除被闸拦下的"，不能是"只标记成功结构化的"**——这一版
    改对之前先踩了一次：用"成功结构化的 url"做正向筛选，结果把 68 条被时间
    可信度闸故意丢弃的聚合器条目、以及被预过滤去重掉的条目一并留在了队列里。
    它们已经判定不要，却每轮都被重新捞出来处理一遍，队列还会无限增长。
    "没被处理"有两种截然不同的原因，只有成本闸那一种该重试。
    """
    if deferred_urls:
        ids = [it["_staging_id"] for it in staged_items
               if it.get("_staging_id") and it.get("url") not in deferred_urls]
        held = len(staged_items) - len(ids)
        if held:
            logger.info(f"Staging: {held} 条被成本闸拦下，保留在队列中等下一轮")
    else:
        ids = [it["_staging_id"] for it in staged_items if it.get("_staging_id")]
    if not ids:
        return
    cursor = conn.cursor()
    placeholders = ",".join(["%s"] * len(ids))
    cursor.execute(
        f"UPDATE raw_items_staging SET consumed_at = %s WHERE id IN ({placeholders})",
        (now_local().strftime("%Y-%m-%d %H:%M:%S"), *ids),
    )
    conn.commit()
    cursor.close()
    logger.info(f"Staging: marked {len(ids)} items consumed (post-write)")


def staging_stats(conn) -> dict:
    """存档表水位，供运维/监控使用。"""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT COUNT(*), SUM(consumed_at IS NULL), MIN(fetched_at), MAX(fetched_at)
           FROM raw_items_staging"""
    )
    total, unconsumed, oldest, newest = cursor.fetchone()
    cursor.close()
    return {
        "total": total or 0,
        "unconsumed": unconsumed or 0,
        "oldest_fetched_at": oldest.isoformat() if oldest else None,
        "newest_fetched_at": newest.isoformat() if newest else None,
    }
