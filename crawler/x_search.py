"""
X（Twitter）全网关键词搜索召回 v1.0

补的是 fetch_x_kols() 的结构性缺口：KOL 时间线只能看见 32 个固定账号，
"新闻发生了但名单里没人第一时间发"的内容（小交易所被盗、二线项目上币、
区域性监管动作）在现有链路里完全召不回。本模块用 recent search 端点做
全网关键词召回，再靠客户端质量过滤把噪音压回可控范围。

接口契约与 fetch_x_kols() 完全一致：返回 (news_items, raw_posts)，字段结构
逐字段对齐，可以直接拼进 run_rss_and_scraper_crawler() 的 all_items。

配额账本（Basic 层，450 请求 / 15 分钟）：
    现有 KOL 拉取   ~192 请求/天（32 账号 × 6 轮）
    本模块          21 查询 × 1 页 = 21 请求/轮，6 轮/天 = 126 请求/天
    单轮硬上限      MAX_REQUESTS_PER_RUN = 60
  单轮峰值 21+32=53 «450，留足重试和临时加查询的余量。
"""
import os
import re
import time
import logging
import requests
from datetime import datetime, timedelta, timezone

from .sources import X_SEARCH_QUERIES, CRYPTO_KOLS

logger = logging.getLogger(__name__)

X_SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"


# ── 可调参数 ─────────────────────────────────────────────────────────
# 下面这组常量是本模块唯一需要调的旋钮。调之前先跑 `python -m crawler.x_search`
# （模块自带 dry-run，见文件末尾），它会打印各阶段的过滤水位。

# 单条查询回取的推文数。上限 100（API 限制），压低会直接损失召回。
MAX_RESULTS_PER_QUERY = 100

# 单轮请求硬上限。超过就停止发请求并告警——防止查询集被扩得太大或分页失控
# 把配额吃穿，影响同一 token 上的 KOL 拉取。
MAX_REQUESTS_PER_RUN = 60

# 每条查询最多翻几页。窗口拉长到 14 小时后，热门查询（market/macro）一页 100 条
# 很容易被截断，所以翻 2 页。请求数 = 查询数 × 页数 = 21 × 2 = 42，仍在
# MAX_REQUESTS_PER_RUN(60) 和 API 限额(450/15min) 之内。
MAX_PAGES_PER_QUERY = 2

# 回看窗口，必须 >= cron 周期，否则两轮之间会有盲区。
#
# 2026-07-26 cron 从每 4 小时改为每 12 小时（降本），窗口相应从 6 小时改为 14——
# 12 小时周期 + 2 小时重叠。留重叠是因为 X 的索引对低粉账号有分钟级到小时级延迟，
# 窗口卡死等于周期会漏掉"发的时候还没被索引到"的推文。
# 重叠部分由 tweet_id 去重 + 下游 prefilter_duplicates 兜住，不会重复计费。
SEARCH_LOOKBACK_HOURS = 14

# 互动量阈值：like+retweet+reply+quote 低于该值直接丢。这是省下游 LLM 成本的
# 主力开关——全网搜索的原始结果里 70%+ 是零互动的散人推文。
#
# 按 category 分档的理由：突发安全/尾部风险类新闻在爆出后的头几分钟互动量天然
# 很低（往往是安全公司的小号先发），阈值卡高会把最有价值的抢先信息全滤掉；
# 而行情异动/宏观类的推文基数极大且大部分是散人喊单，必须卡高。
#
# 调参方向：
#   召回不够 → 先降 market/macro（噪音大但基数也大），再降 breaking
#   LLM 成本超标 → 先提 market/macro，security 和 risk 不要动
MIN_ENGAGEMENT_BY_CATEGORY = {
    "security":   3,    # 抢先性 > 精确性
    "risk":       3,    # 脱锚/挤兑同上
    "listing":    5,
    "whale":      5,
    "funding":    5,
    "unlock":     5,
    "regulation": 10,
    "etf":        10,
    "breaking":   10,   # "BREAKING" 是钓鱼党最爱用的词，卡严一点
    "market":     25,   # 噪音最大的一类
    "macro":      25,
}
MIN_ENGAGEMENT_DEFAULT = 10

# 作者粉丝数下限。低于该值的账号即使某条推文互动量达标，也基本是
# 互刷/抽奖号。设 0 可关闭这项过滤。
MIN_AUTHOR_FOLLOWERS = 500

# 单账号单轮最多保留几条（2026-07-26 新增）。
#
# 起因：实测发现 Rubycryptoz 单账号一轮就贡献 18 条，全部是同一个项目（TRON）
# 的模板化"商业分析"软文——每条话术不同、都不触发 spam 正则，但重复推销同一
# 项目本身就是内容农场的行为特征，不是新闻。逐条猜测新话术的正则打不完，
# 从"单账号不该主导结果"这个更通用的假设上防：正经新闻源（媒体号/链上监测号）
# 报道的是不同事件，不会一轮里对同一账号产出两位数条目。
MAX_ITEMS_PER_AUTHOR = 3

# 本模块单轮最多向下游（LLM 结构化）输出多少条（2026-07-26 新增，成本控制）。
#
# 起因：Lawrence 反馈"X API 的钱烧得很快"。实测查证后发现真正的成本大头不是
# X API 本身（search/recent 在配额内是固定层级费用，不按调用量计费），而是
# **下游 gpt-5.4 结构化**——本模块过滤后单轮曾产出 528 条，全部进 LLM 结构化，
# 单条约 $0.0076（950 输入 + 350 输出 token），仅这一个模块就让单轮 LLM 成本从
# ~$3.65 涨到 ~$9+，2.5 倍。
#
# 硬顶在这里卡，而不是继续收紧质量阈值：质量阈值调过了容易连好内容一起误杀，
# 数量顶是最后一道防线，按互动量降序保留最有价值的部分，多出来的直接丢弃
# （不进 LLM，不产生任何费用）。200 条约合 $1.5/轮，是原有量的一半出头，
# 需要更多召回时优先调这个数字，而不是松开质量阈值。
MAX_ITEMS_PER_RUN = 200

# 正文最少字符数（已剔除 URL / @提及 / #标签 后）。中日韩语信息密度高于英文，
# 分开设阈值，否则中文快讯会被英文的阈值误杀。
MIN_TEXT_CHARS_EN = 40
MIN_TEXT_CHARS_CJK = 18

# 单条推文允许的最大 $ticker / #标签 / @提及 数量。超过即判定为
# 刷标签的喊单或抽奖推——正经新闻不会一条里挂 8 个币种标签。
MAX_CASHTAGS = 4
MAX_HASHTAGS = 5
MAX_MENTIONS = 5

# 429 退避：遇到限流后的重试次数与基础退避秒数（指数增长）。
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_BASE = 15

# 查询之间的间隔，避免瞬时打满速率窗口。
SLEEP_BETWEEN_QUERIES = 1.0


# ── 垃圾内容识别 ─────────────────────────────────────────────────────
# 只匹配"结构性垃圾"（抽奖/喊单/拉群），不匹配话题词本身。
# 反例警告：不要直接把 airdrop / 空投 加进来——"XX 项目空投上线"是正经新闻，
# 只有和 follow/RT/claim 这类动作词同现时才是垃圾。
_SPAM_PATTERNS = [
    # 抽奖 / 互动骗粉
    r"\bgiveaway\b",
    r"\b(follow|rt|retweet|like)\b[^.\n]{0,40}\b(win|enter|qualify|eligible|chance)\b",
    r"\blike\s*\+\s*(rt|retweet)\b",
    r"\btag\s+\d+\s+(friends?|people)\b",
    r"\b(drop|leave)\s+(your\s+)?(wallet|address|sol address|eth address)\b",
    r"\bclaim\s+(your\s+)?(free|airdrop|reward)\b",
    r"\bfree\s+(mint|nft|crypto|airdrop|tokens?)\b",
    # 拉群 / 私信
    r"\bjoin\s+(our|the|my)\s+(telegram|discord|group|channel|vip)\b",
    r"\bdm\s+(me|us)\b",
    r"\blink\s+in\s+bio\b",
    # 喊单 / 传销话术
    r"\b\d{2,4}\s*x\b[^.\n]{0,20}\b(gem|potential|incoming|soon|guaranteed)\b",
    r"\bnext\s+(100x|1000x|gem|moonshot|shiba|pepe)\b",
    r"\b(presale|pre-sale|whitelist spots?|early access)\b[^.\n]{0,30}\b(live|open|now)\b",
    r"\bguaranteed\s+(profit|returns?|gains?)\b",
    r"\bpump\s+(group|signal|call)s?\b",
    # 中文垃圾
    r"(私信|加群|进群|带单|喊单|内部消息|稳赚|包赚|免费领取|一对一指导)",
    r"(关注|转发)[^。\n]{0,10}(抽|送|领)",
    # 微额"鲸鱼"机器人模板（2026-07-26 新增）——实测 whalewatchalert/whalewatchRH
    # 这类账号机械发布 "A XXX whale just bought $1.6K of $TICKER at $2.3M MC"，
    # 格式上像鲸鱼追踪（我们已有 lookonchain 等真正的链上监测源），但金额只有
    # 几千美元、标的是几十万到几百万市值的微型币，对板块/大盘毫无实际影响，
    # 纯属噪音而非信号。用模板结构本身识别，不看金额（金额本身就已证明不重要）。
    r"\bwhale\s+just\s+bought\s+\$[\d.]+[KM]?\s+of\s+\$\w+\s+at\s+\$[\d.]+[KM]\s+MC\b",
    # 中文 PR 通稿套话（2026-07-26 新增）——实测 Richdegen67 发的是项目方付费软文
    # （"解锁 8% APY：通过 XXX 参与 YYY DeFi Summer"），符合 skill 文档
    # PROMO 体裁定义，但英文 _SPAM_PATTERNS 里没有对应的中文识别
    r"(赋能|新范式|无锁仓|资金自由无上限)[^。\n]{0,20}(理财|挖矿|质押|收益)",
    r"解锁\s*\d+%?\s*(APY|年化)",
    r"\d{2,4}\s*倍[^。\n]{0,10}(potential|币|机会|收益)",
]
_SPAM_RE = re.compile("|".join(_SPAM_PATTERNS), re.IGNORECASE)

_URL_RE = re.compile(r"https?://\S+")
_MENTION_RE = re.compile(r"@\w+")
_HASHTAG_RE = re.compile(r"#\w+")
_CASHTAG_RE = re.compile(r"\$[A-Za-z]{2,10}\b")
_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")

# 付费大使/水军号识别（2026-07-26 新增）——实测 Rubycryptoz/Richdegen67 的
# 推文正文本身不含 spam 关键词（写得像正经内容甚至像深度分析），但账号 bio
# 挂着多个项目的 "Ambassador"/"OG" 头衔，是典型的加密圈付费推广号身份标记。
# 这类账号发的所有内容都应视为软文，在账号层面过滤比逐条猜内容更可靠。
_PROMO_BIO_RE = re.compile(
    r"\bambassador\b.{0,80}\bambassador\b"      # 挂 2 个以上项目大使头衔
    r"|\b(OG|KOL)\s*:\s*@\w+.{0,40}@\w+"         # "OG: @a @b" 这类多标签自我介绍
    r"|boost\s+your\s+coin",                     # whalewatchalert 类"付费推广"服务号
    re.IGNORECASE,
)

# KOL 名单的权威分复用：搜索召回里如果作者恰好是名单内账号，沿用其权威分，
# 保证同一个人的推文不会因为召回路径不同而拿到两个分数。
_KOL_AUTHORITY = {u.lower(): a for u, a, _ in CRYPTO_KOLS}

# 名单外账号的权威分。全网搜索到的作者绝大多数是无从背书的个人账号，
# 按粉丝量给一个保守分档，对齐 pipeline 提示词里 "aggregator/search" 的定位。
AUTHORITY_UNKNOWN_LARGE = 3    # ≥10 万粉
AUTHORITY_UNKNOWN_SMALL = 2
LARGE_ACCOUNT_FOLLOWERS = 100_000


def _engagement(metrics: dict) -> int:
    return (metrics.get("like_count", 0) + metrics.get("retweet_count", 0)
            + metrics.get("reply_count", 0) + metrics.get("quote_count", 0))


def _clean_text(text: str) -> str:
    """剥掉 URL / @提及 / #标签，剩下的才算"正文"。"""
    t = _URL_RE.sub(" ", text)
    t = _MENTION_RE.sub(" ", t)
    t = _HASHTAG_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _passes_quality(tweet: dict, user: dict, category: str, stats: dict) -> bool:
    """客户端质量闸门。每丢一条都记一次 stats，便于事后调阈值。

    顺序是刻意的：先做零成本的字符串判断，再做需要 user 字典的判断。
    """
    text = tweet.get("text", "")
    body = _clean_text(text)

    # 1) 正文过短 / 纯链接
    min_chars = MIN_TEXT_CHARS_CJK if _CJK_RE.search(body) else MIN_TEXT_CHARS_EN
    if len(body) < min_chars:
        stats["drop_short"] += 1
        return False

    # 2) 标签刷屏
    if (len(_CASHTAG_RE.findall(text)) > MAX_CASHTAGS
            or len(_HASHTAG_RE.findall(text)) > MAX_HASHTAGS
            or len(_MENTION_RE.findall(text)) > MAX_MENTIONS):
        stats["drop_tagspam"] += 1
        return False

    # 3) 抽奖 / 喊单 / 拉群
    if _SPAM_RE.search(text):
        stats["drop_spam"] += 1
        return False

    # 4) 互动量
    threshold = MIN_ENGAGEMENT_BY_CATEGORY.get(category, MIN_ENGAGEMENT_DEFAULT)
    if _engagement(tweet.get("public_metrics") or {}) < threshold:
        stats["drop_engagement"] += 1
        return False

    # 5) 作者粉丝量
    followers = (user.get("public_metrics") or {}).get("followers_count", 0)
    if MIN_AUTHOR_FOLLOWERS and followers < MIN_AUTHOR_FOLLOWERS:
        stats["drop_followers"] += 1
        return False

    # 6) 付费大使/推广号 bio 识别——账号身份判定，比逐条猜内容更可靠
    if _PROMO_BIO_RE.search(user.get("description", "") or ""):
        stats["drop_promo_account"] += 1
        return False

    return True


def _authority_for(username: str, followers: int) -> int:
    known = _KOL_AUTHORITY.get(username.lower())
    if known:
        return known
    return (AUTHORITY_UNKNOWN_LARGE if followers >= LARGE_ACCOUNT_FOLLOWERS
            else AUTHORITY_UNKNOWN_SMALL)


def _normalized_key(text: str) -> str:
    """用于识别跨账号的复制粘贴。同一条快讯常被十几个搬运号原样转发，
    tweet_id 不同但正文一致，不在这里掐掉就会十几条一起进 LLM。"""
    body = _clean_text(text).lower()
    return re.sub(r"[^\w一-鿿]+", "", body)[:120]


# ── HTTP 层 ──────────────────────────────────────────────────────────

class _Budget:
    """单轮请求预算。计数 + 硬上限，避免把 KOL 拉取的配额吃掉。"""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0
        self.rate_limited = 0

    def can_spend(self) -> bool:
        return self.used < self.limit


def _search_once(query: str, bearer: str, budget: _Budget,
                 start_time: str, next_token: str | None = None) -> dict | None:
    """发一次 recent search。429 走指数退避重试，其余错误直接放弃这条查询。"""
    params = {
        "query": query,
        "max_results": MAX_RESULTS_PER_QUERY,
        "start_time": start_time,
        "tweet.fields": "created_at,public_metrics,lang,author_id",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics,verified,description",
    }
    if next_token:
        params["next_token"] = next_token

    for attempt in range(RATE_LIMIT_RETRIES + 1):
        if not budget.can_spend():
            logger.warning(f"X search: request budget exhausted ({budget.limit}), stopping")
            return None
        try:
            budget.used += 1
            resp = requests.get(
                X_SEARCH_URL, params=params,
                headers={"Authorization": f"Bearer {bearer}"}, timeout=30,
            )
            if resp.status_code == 429:
                budget.rate_limited += 1
                if attempt >= RATE_LIMIT_RETRIES:
                    logger.warning("X search: 429 after all retries, giving up on query")
                    return None
                # 优先用服务端给的重置时间，拿不到再退回指数退避
                wait = RATE_LIMIT_BACKOFF_BASE * (2 ** attempt)
                reset = resp.headers.get("x-rate-limit-reset")
                if reset:
                    try:
                        wait = max(1, min(120, int(reset) - int(time.time()) + 2))
                    except ValueError:
                        pass
                logger.warning(f"X search: 429, backing off {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                logger.warning(f"X search HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            return resp.json()
        except Exception as e:
            logger.warning(f"X search request failed: {e}")
            return None
    return None


# ── 主函数 ───────────────────────────────────────────────────────────

def fetch_x_search(known_tweet_ids: set[str] | None = None,
                   queries: list[tuple[str, str, str]] | None = None,
                   collect_stats: dict | None = None) -> tuple[list[dict], list[dict]]:
    """全网关键词搜索召回。返回 (news_items, x_raw_posts)，结构同 fetch_x_kols()。

    known_tweet_ids: 已经由别的路径（通常是 fetch_x_kols）召回的 tweet_id，
                     命中的直接跳过，避免同一条推文进两次 LLM。
    collect_stats:   传入一个 dict 会被填入各阶段水位，供调参/验证使用。
    """
    # 运维开关：这是新模块且和 KOL 拉取共用一个 token，出问题时要能不发版就停掉。
    if os.environ.get("X_SEARCH_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        logger.info("X search disabled via X_SEARCH_ENABLED, skipped")
        return [], []

    bearer = os.environ.get("X_BEARER_TOKEN", "")
    if not bearer:
        logger.warning("X_BEARER_TOKEN not set, skip X search")
        return [], []

    queries = queries if queries is not None else X_SEARCH_QUERIES
    seen_ids = set(known_tweet_ids or ())
    seen_texts: set[str] = set()
    budget = _Budget(MAX_REQUESTS_PER_RUN)
    start_time = (datetime.now(timezone.utc)
                  - timedelta(hours=SEARCH_LOOKBACK_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    stats = collect_stats if collect_stats is not None else {}
    stats.update({
        "requests": 0, "raw": 0, "kept": 0,
        "drop_short": 0, "drop_tagspam": 0, "drop_spam": 0,
        "drop_engagement": 0, "drop_followers": 0, "drop_no_author": 0,
        "drop_dup_id": 0, "drop_dup_text": 0, "drop_promo_account": 0,
        "drop_author_cap": 0,
        "by_group": {},
    })

    news_items, raw_posts = [], []
    author_counts: dict[str, int] = {}

    for group_id, category, query in queries:
        if not budget.can_spend():
            logger.warning(f"X search: budget exhausted, {group_id} and later skipped")
            break

        group_raw = group_kept = 0
        next_token = None

        for _ in range(MAX_PAGES_PER_QUERY):
            data = _search_once(query, bearer, budget, start_time, next_token)
            if not data:
                break
            tweets = data.get("data") or []
            users = {u["id"]: u for u in (data.get("includes", {}).get("users") or [])}
            group_raw += len(tweets)
            stats["raw"] += len(tweets)

            for tw in tweets:
                tid = tw.get("id")
                if not tid or tid in seen_ids:
                    stats["drop_dup_id"] += 1
                    continue
                # 作者信息缺失（账号在抓取瞬间被封/转私密）。没有粉丝数就无法
                # 判权威分，直接丢，不猜。
                user = users.get(tw.get("author_id")) or {}
                if not user:
                    stats["drop_no_author"] += 1
                    continue
                if not _passes_quality(tw, user, category, stats):
                    continue

                text = tw.get("text", "").strip()
                key = _normalized_key(text)
                if key in seen_texts:
                    stats["drop_dup_text"] += 1
                    continue

                username = user.get("username", "")
                if author_counts.get(username, 0) >= MAX_ITEMS_PER_AUTHOR:
                    stats["drop_author_cap"] += 1
                    continue

                seen_ids.add(tid)
                seen_texts.add(key)
                author_counts[username] = author_counts.get(username, 0) + 1
                followers = (user.get("public_metrics") or {}).get("followers_count", 0)
                metrics = tw.get("public_metrics") or {}
                tweet_url = f"https://x.com/{username}/status/{tid}"
                title = _URL_RE.sub("", text).strip().replace("\n", " ")[:180]

                news_items.append({
                    "source": f"X/{username}",
                    "title": title,
                    "url": tweet_url,
                    "summary": text[:500],
                    "published_at": tw.get("created_at", ""),
                    "lang": tw.get("lang", "en"),
                    "authority": _authority_for(username, followers),
                    "type": "x",
                    "tweet_id": tid,
                })
                raw_posts.append({
                    "tweet_id": tid,
                    "kol_username": username,
                    "kol_display_name": user.get("name", username),
                    "kol_followers_count": followers,
                    "kol_verified": bool(user.get("verified", False)),
                    "kol_profile_url": f"https://x.com/{username}",
                    "tweet_title": title,
                    "tweet_body": text,
                    "tweet_url": tweet_url,
                    "tweet_lang": tw.get("lang", "en"),
                    "like_count": metrics.get("like_count", 0),
                    "retweet_count": metrics.get("retweet_count", 0),
                    "reply_count": metrics.get("reply_count", 0),
                    "quote_count": metrics.get("quote_count", 0),
                    "impression_count": metrics.get("impression_count", 0),
                    "published_at": tw.get("created_at", ""),
                })
                group_kept += 1
                stats["kept"] += 1

            next_token = (data.get("meta") or {}).get("next_token")
            if not next_token:
                break

        stats["by_group"][group_id] = {"raw": group_raw, "kept": group_kept}
        time.sleep(SLEEP_BETWEEN_QUERIES)

    # 成本硬顶：按互动量降序只保留前 MAX_ITEMS_PER_RUN 条，其余在这一步丢弃、
    # 不会进入下游 LLM 结构化（也就不产生任何 token 费用）。同步裁剪 raw_posts，
    # 保证两个列表的 tweet_id 集合一致。
    stats["drop_cost_cap"] = max(0, len(news_items) - MAX_ITEMS_PER_RUN)
    if stats["drop_cost_cap"]:
        news_items.sort(
            key=lambda i: next(
                (p["like_count"] + p["retweet_count"] + p["reply_count"] + p["quote_count"]
                 for p in raw_posts if p["tweet_id"] == i["tweet_id"]), 0
            ),
            reverse=True,
        )
        news_items = news_items[:MAX_ITEMS_PER_RUN]
        kept_ids = {i["tweet_id"] for i in news_items}
        raw_posts = [p for p in raw_posts if p["tweet_id"] in kept_ids]
        stats["kept"] = len(news_items)

    stats["requests"] = budget.used
    dropped = stats["raw"] - stats["kept"]
    pct = (dropped / stats["raw"] * 100) if stats["raw"] else 0.0
    logger.info(
        f"X search: {budget.used} requests / {len(queries)} queries, "
        f"{stats['raw']} raw -> {stats['kept']} kept (filtered {dropped}, {pct:.0f}%) | "
        f"short={stats['drop_short']} tagspam={stats['drop_tagspam']} "
        f"spam={stats['drop_spam']} eng={stats['drop_engagement']} "
        f"fol={stats['drop_followers']} noauthor={stats['drop_no_author']} "
        f"promo={stats['drop_promo_account']} authorcap={stats['drop_author_cap']} "
        f"dupid={stats['drop_dup_id']} duptext={stats['drop_dup_text']} "
        f"costcap={stats['drop_cost_cap']} rate_limited={budget.rate_limited}"
    )
    return news_items, raw_posts


# ── dry-run：调阈值时直接跑这个文件，不碰 DB 也不碰 LLM ────────────────
if __name__ == "__main__":
    import sys
    from pathlib import Path

    env_file = Path(__file__).resolve().parent.parent / "config" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        stream=sys.stdout)
    st: dict = {}
    items, posts = fetch_x_search(collect_stats=st)
    print("\n--- per-group raw/kept ---")
    for gid, g in st["by_group"].items():
        print(f"  {gid:16s} raw={g['raw']:4d} kept={g['kept']:3d}")
    print(f"\n--- {len(items)} items ---")
    for it in items[:30]:
        print(f"  [{it['authority']}] {it['source']:24s} {it['title'][:110]}")
