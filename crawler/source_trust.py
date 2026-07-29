"""信源时间可信度分级 —— crawler/source_trust.py

## 为什么需要这个模块（2026-07-29 线上事故）

一条 6 月 27 日的旧闻（"特朗普威胁就数字税征 100% 关税"）以 **A 档、日期
2026-07-28** 的身份进了事件库并在前端展示，整整差一个月。倒查链路：

  1. 条目来自 Google News RSS（`type='web_search'`），聚合器给的
     `published_at` 是 **2026-07-28T12:54:11**——那是它重新分发这条旧文的
     时间，不是原文发布时间。原文实测是 6/26-27（新华网/21财经/东方财富
     三家独立信源的 URL 里都带 `20260627`）。
  2. `filter_by_freshness`（LLM 前）读的就是这个 published_at，顺利放行。
  3. `filter_by_event_date`（LLM 后）本来是专门为"信源时间戳骗人"设计的
     兜底闸——它查 LLM 从正文里读出的真实 `event_date`。但这条的 summary
     是 **"特朗普威胁：若欧洲国家征收数字服务税，将对其输美商品征收100%关税
     &nbsp;&nbsp;财联社"**，即标题重复一遍加个来源名，**一个字的正文都没有**。
     LLM 无从提取真实日期，`event_date` 只能回落成 published_at。

**关键结论：为防聚合器撒谎而建的那道闸，对聚合器条目结构上就永远失效**——
它需要正文，而聚合器恰恰不给正文。这不是参数没调好，是防线建错了层。

实测普遍性（近 3 天 staging）：2870 条 web_search 条目里 **2640 条（92%）
摘要≈标题、无正文**；平均摘要长度 90 字符，而直连 RSS 是 193 字符。

## 分级口径

  · PRIMARY（时间可信）：直连发行方自己的 RSS/HTML/API。published_at 是
    发行方在自己的 feed 里声明的发布时间，没有中间商改写的动机和机会。
  · AGGREGATOR（时间不可信）：Google News RSS、ddgs 等搜索聚合。它们给的
    时间是"我什么时候索引/分发的"，与原文发布时间可以差任意久。

注意分级的是**时间可信度**，不是**内容质量**。财联社经 Google News 分发
仍然是 AGGREGATOR——财联社本身是正规财经媒体，但经过聚合器这一跳之后，
我们拿到的时间戳就不是财联社声明的那个了。把"媒体权威度"和"时间可信度"
混为一谈正是这次事故能发生的认知原因。
"""
import os

# staging.type / sources[].type 里代表"经过聚合器中转"的取值。
# 与 crawler/web_search.py 的产出保持一致。
AGGREGATOR_TYPES = frozenset({"web_search"})

# 摘要比标题多出的字符数低于这个阈值，就认为"没有正文"——LLM 拿不到任何
# 可供提取真实事件日期的材料。
# 25 这个数字来自实测：Google News 的 summary 格式恒为
# "{标题}&nbsp;&nbsp;{来源名}"，去掉标题后残留的就是几个字的来源名；
# 而直连 RSS 的 summary 普遍是 100+ 字符的真实导语。
MIN_BODY_CHARS = int(os.environ.get("B9_MIN_BODY_CHARS", "25"))

# 展示层新鲜度硬闸。2026-07-29 从 7 天收紧到 5 天（Lawrence 明确要求
# "发布时间不是近5天的内容做强制去除"）。
MAX_AGE_DAYS = int(os.environ.get("B9_MAX_AGE_DAYS", "5"))


def _norm(text: str) -> str:
    """归一化用于比长度：去掉 HTML 实体空格和普通空白。"""
    if not text:
        return ""
    return (text.replace("&nbsp;", "")
                .replace(" ", "")
                .replace(" ", "")
                .replace("\n", "")
                .strip())


def has_body(item: dict) -> bool:
    """这条原始条目是否带了**真实正文/导语**（而不只是标题的复读）。

    判据是"摘要去掉标题之后还剩多少字"，不是"摘要有多长"——Google News 的
    摘要长度看起来不短（它把整条标题塞进去了），但信息量为零。
    """
    title = _norm(item.get("title", ""))
    summary = _norm(item.get("summary", ""))
    if not summary:
        return False
    # 摘要里通常整段包含标题，去掉后看残留
    residue = summary.replace(title, "")
    return len(residue) >= MIN_BODY_CHARS


def is_aggregator(item_or_source: dict) -> bool:
    """这条来源是否经由搜索聚合器中转（→ 时间戳不可信）。"""
    return (item_or_source.get("type") or "") in AGGREGATOR_TYPES


def date_is_verifiable(item: dict) -> bool:
    """我们**有没有办法**确认这条内容的真实发布时间。

    两条路，有一条通就算可验证：
      · 直连发行方 → published_at 本身可信
      · 有正文 → LLM 能从正文里读出真实事件日期（filter_by_event_date 兜底）

    两条都不通（聚合器 + 无正文）时，我们对这条新闻的时间**一无所知**，
    而且没有任何下游环节能补救——这正是数字税那条旧闻的处境。
    """
    return (not is_aggregator(item)) or has_body(item)


def event_sources_all_aggregated(sources: list) -> bool:
    """事件级判断：它的**全部**信源是否都来自聚合器。

    只要有一个直连发行方的信源，跨轮归并就把可信时间带进来了，这条事件的
    日期就有据可依——所以是 all 而不是 any。
    """
    if not sources:
        return False
    return all(is_aggregator(s) for s in sources)


def should_drop_untrusted(item: dict) -> bool:
    """LLM **之前**的丢弃判定：聚合器来源 + 无正文 + 无法验证时间。

    为什么可以在 LLM 之前就丢（而不是先花钱结构化再判）：这个判定只看
    type 和 summary 两个字段，纯字符串操作，不需要模型的任何理解。早丢
    早省钱——实测这类条目占 web_search 的 92%，是 LLM 成本的大头之一。

    为什么单条丢掉是安全的、不会漏掉真正的大新闻：真正重大的事件必然被
    多家直连媒体报道，我们的 RSS 列表会从**发行方自己的 feed** 拿到同一
    条内容，那一份带着可信时间戳。丢掉的是"只有搜索聚合器转载过一次、
    没有任何一手信源背书"的孤证——这种孤证本来也不该以 A 档出现在首屏。
    """
    return is_aggregator(item) and not has_body(item)
