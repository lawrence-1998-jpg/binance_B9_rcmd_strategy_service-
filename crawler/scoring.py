"""
Macro Insight v1 打分。

    Score = 0.35·M + 0.20·T + 0.15·H + 0.15·A + 0.15·Q     （纯加权，无硬门）

因子口径见 docs/skill-macro-news-recommendation-v1.md 第二章。本模块只负责把 LLM
给出的原始分与管线算出的信号合成为最终分，不做召回或过滤。
"""
import json
import logging
import math
import re
from datetime import datetime, timezone

from . import verification
from .dedup import parse_dt
from .timeutil import now_local

logger = logging.getLogger(__name__)

# 权重（合计 1.0）
#
# 2026-07-29 从五因子扩到七因子（PRD-03 / ADR-001）。M 从 0.35 让出空间给
# 两个新因子；H 和 A 各降 0.05，因为 I（冲击力）的"权威共振"子项已经吸收了
# 一部分"多家权威媒体同时报道"的信号，不降就是重复计分。
#
# Lawrence 明确"排不对也没关系，都放到策略实验室里我自己调"，所以这组数字
# 是**起点不是结论**，真正的调参在 04/05 tab 上做。
W_IMPACT, W_BREADTH, W_TIME, W_PUNCH, W_HOT, W_AUTH, W_QUAL = (
    0.26, 0.16, 0.16, 0.14, 0.10, 0.10, 0.08)

# ── 打分版本号 ───────────────────────────────────────────────────────
#
# **改因子集合或改权重，必须同时把这个数 +1。**
#
# 为什么需要它：`importance_score` 是**持久化的派生值**——由本模块从其它列
# 算出来后写回库，之后再没人验证过它。2026-07-29 查出来的后果是：全库 3174
# 行里只有 402 行（13%）的分是按当时的现行公式算的，1865 行还停在五因子时代，
# 907 行是某个中间版本。前端按这个字段排序，等于把三个公式算出来的分放在同一
# 个列表里比大小。
#
# 最难受的地方在于**这个故障在构造上就是隐形的**：错的分仍然是 [0,1] 的浮点
# 数，仍然能排序，页面照常渲染，不报错不告警。它不像陈旧新闻那样人眼一看就
# 知道不对，只有计算才看得见。而且当时库里没有任何字段能回答"这行是哪个版本
# 算的"，只能靠反算比对去猜——这个版本号就是为了让它变成一次 WHERE 查询。
#
# 配套的护栏在 scripts/qa_suite.py：一条断言把全库的存量分与"按当前公式重算"
# 逐行比对，对不上直接红。改公式时那条用例会立刻亮红，逼着做数据迁移——
# 加列走 migration、改公式只改代码，是这次事故的直接成因，两者是同一个变更
# 的两半。重算脚本见 scripts/rescore_factors.py。
SCORING_VERSION = 6   # v1=五因子；v2=七因子(+B/+I)；v3=CNBC硬覆盖(已废)；v4=去CNBC特例+共振排除社交源；v5=冲击力误读词表补漏；v6=冲击力幅度改 opt-in 口径（必须有价格变动指示词，实测修正 54% 的误读，2026-08-02）

# event_tier 对应的 M 值区间，用于约束 LLM 可能越界的打分
TIER_BOUNDS = {
    "S": (0.85, 1.00),
    "A": (0.60, 0.84),
    "B": (0.35, 0.59),
    "C": (0.15, 0.34),
    "D": (0.00, 0.14),
}

TIMELINESS_HALFLIFE_HOURS = 24   # 文档 2.2：T = e^(-λΔt)，λ = ln2/24
HOTNESS_SOURCE_CAP = 8           # 文档 2.3：独立信源数 8 家以上封顶
SOCIAL_BASELINE_FLOOR = 500      # 社交基准下限，防止冷启动时少量互动就被归一成满分


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


# ── M：影响面 ────────────────────────────────────────────────────────

def compute_impact(event: dict) -> float:
    """LLM 给出的 score_market_impact，按 event_tier 区间夹紧。

    夹紧是必要的：LLM 偶尔会给 D 级事件打 0.6 的影响分（典型如被"黑客""崩盘"
    等戏剧性词汇诱导），tier 区间是它自己判的，用作自洽性约束。
    """
    raw = float(event.get("score_market_impact", 0.5) or 0.0)
    lo, hi = TIER_BOUNDS.get(event.get("event_tier", "C"), (0.0, 1.0))
    return _clamp(raw, lo, hi)


# ── T：时效 ──────────────────────────────────────────────────────────

def compute_timeliness(event: dict, now: datetime | None = None) -> float:
    """按事件真实发布时间做 24h 半衰期指数衰减。

    时间解析失败时给 0.5 中性分，而不是 0——解析失败是我们的数据问题，
    不该让内容白白背锅沉底。
    """
    published = parse_dt(event.get("published_at"))
    if published is None:
        return 0.5
    now = now or now_local()
    hours_ago = max(0.0, (now - published).total_seconds() / 3600)
    return _clamp(math.exp(-hours_ago * math.log(2) / TIMELINESS_HALFLIFE_HOURS))


# ── H：热度 ──────────────────────────────────────────────────────────

def social_baseline(events: list[dict]) -> float:
    """本轮社交互动量的 P95，作为 log 归一化的分母基准。

    用批内 P95 而非固定常数，是为了让热度随大盘活跃度自适应：淡季几百互动就算热，
    旺季同样的数字只是平均水平。下限 SOCIAL_BASELINE_FLOOR 防止某轮 X 拉取失败
    （互动全 0 或极小）时，任何一点互动都被归一化成高分。
    """
    values = [e.get("social_interactions", 0) or 0 for e in events]
    values = [v for v in values if v > 0]
    if not values:
        return float(SOCIAL_BASELINE_FLOOR)
    values.sort()
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))]
    return float(max(p95, SOCIAL_BASELINE_FLOOR))


def compute_hotness(event: dict, baseline: float) -> float:
    """H = 0.6·log归一(社交互动) + 0.4·min(独立信源数 / 8, 1)

    此前的实现只有信源数那一半，X KOL 的赞/转/评/引数据明明已经落在 x_raw_posts
    表里却完全没接进来——这正是文档给社交互动 0.6 权重要解决的信号。
    """
    social = max(0, int(event.get("social_interactions", 0) or 0))
    social_part = math.log10(1 + social) / math.log10(1 + baseline)

    sources = max(1, int(event.get("source_count", 1) or 1))
    source_part = min(sources / HOTNESS_SOURCE_CAP, 1.0)

    return _clamp(0.6 * _clamp(social_part) + 0.4 * source_part)


# ── A：权威 ──────────────────────────────────────────────────────────

def compute_authority(event: dict) -> float:
    """信源权威分，谣言打 7 折（文档 2.4），再按真实性校验结论降权。

    两道折扣叠加是有意的，它们防的是不同东西：`is_rumor` 是 LLM 从**文本措辞**
    判断的（"据传"/"消息人士"），而 verification 看的是**客观信号**（几家独立
    机构报道、信源可信度分层、有无矛盾报道）。一条写得像板上钉钉、但只有一个
    陌生账号说的消息，LLM 不会标 rumor，只有校验层能压住它。

    v4（2026-07-31）：**移除 v3 的 CNBC 硬覆盖**（覆盖即抬到 1.0 + 总分 +0.05）。
    那是对"prompt 媒体名单与声明权威表不同步"的补丁——Benzinga 等大产量源
    不在 prompt 名单里被 LLM 按 aggregator 打分，才需要给 CNBC 开后门。根治
    方案是 crawler/authority_table.py 单一事实源 + prompt 名单动态渲染（LLM
    现在能正确认出全部信源），补丁随病根一起拆掉。Lawrence 裁决原话："把
    CNBC 的硬覆盖去除""赶紧全面修一下这套体系"。
    """
    authority = _clamp(float(event.get("score_authority", 0.5) or 0.0))
    if event.get("is_rumor"):
        authority *= 0.7
    return _clamp(authority * verification.authority_multiplier(event))


# ── Q：质量 ──────────────────────────────────────────────────────────

def compute_quality(event: dict) -> float:
    """LLM 给出的信噪质量分（标题党/软文/低信息密度扣分）。"""
    return _clamp(float(event.get("score_quality", 0.5) or 0.0))


# ── B：广度（2026-07-29 新增，PRD-03 R2）─────────────────────────────
#
# 「影响一个指数」和「影响一只股票」是完全不同的量级，而此前系统里没有任何
# 字段区分这件事——这正是我们的内容质感与 CNBC 差异的根源：他们首屏是
# "Dow rallies 600 points"（指数级），我们是"分析师比较联合太平洋与诺福克南方"
# （个股级），两者在旧的五因子下可能拿到相近的分。
#
# 值由 LLM 的 breadth_level 映射而来，不让模型直接给 0-1 分——枚举比连续分
# 稳定得多，模型在"这是板块级还是多标的级"上比在"这该给 0.55 还是 0.6"上
# 可靠。缺失时给 single_asset 的值：拿不准就当窄的，避免把噪音抬上来。
BREADTH_VALUES = {
    "cross_market": 1.00,   # 跨市场/跨资产类别：美联储决议、全球债市抛售、战争扰动油路
    "market_index": 0.80,   # 单一市场大盘：日经跌4%、KOSPI熔断、道指涨600点
    "sector":       0.60,   # 板块级：芯片股集体重挫、DeFi 普跌
    "multi_asset":  0.35,   # 2-5 个具名标的：AMD/美光/英伟达同步下跌
    "single_asset": 0.15,   # 单一公司/代币
}
BREADTH_DEFAULT = BREADTH_VALUES["single_asset"]


def compute_breadth(event: dict) -> float:
    return BREADTH_VALUES.get(event.get("breadth_level"), BREADTH_DEFAULT)


# ── I：冲击力（2026-07-29 新增，PRD-03 R3）───────────────────────────
#
# Lawrence 的原始描述包含三个成分，逐一对照现有因子后**只保留两个**：
#   · 数值幅度（跌18%/涨600点）—— 现有因子完全没捕获，✅ 真新增，是本因子核心
#   · 多家权威媒体报道 —— H 因子里有 min(信源数/8,1) 但被社交互动稀释，
#     A 因子只看单一最高权威，⚠️ 部分覆盖，用"权威共振"子项补强
#   · 对社会经济重大影响 —— ❌ 已被 M（影响面）+ B（广度）覆盖两遍，
#     再单列就是三重计分，**刻意不做**
#
# 全部纯计算，0 次 LLM 调用。
W_PUNCH_MAGNITUDE, W_PUNCH_RESONANCE = 0.65, 0.35

# 幅度提取。只做**百分比**，金额/点数放后续——百分比覆盖了绝大多数有冲击力的
# 标题，且量纲统一、误判风险最低（金额要处理亿/万/M/B 多种量纲，点数要知道
# 指数基数才有意义）。
#
# 排除项是踩过的坑的产物：不能匹配到"2026年""第57期""涨幅超过"这种，
# 所以要求百分号紧跟数字，且数字前不能是年份特征。
_PCT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")

# "这个百分数不是涨跌幅"的语境词。2026-07-29 实测踩到的：
# 「美参议院推进俄伊制裁法案」正文里"对继续购买俄罗斯油气的国家征收 **100%**
# 二级关税"——那是**税率**，被当成了 100% 的价格波动，直接把冲击力顶满，
# 这条因此排到首屏第 5。税率/利率/持股比例/概率这些都是"百分数但不是波动"，
# 语义上和"跌 8%"完全是两回事。
#
# 前后都要看：实测这类修饰语前置后置都常见——后置如"100%关税""25%的股权"，
# 前置如"降息概率60%""持股比例升至25%"。窗口刻意取得窄（前 5 后 6 个字符），
# 再宽会误伤"受关税影响纳指跌3%"这种"提到关税、但百分数是真跌幅"的正常句子
# （实测这句里"关税"距数字 7 个字符，窄窗口正好放过）。
#
# 一开始还加了条"涨跌动词紧贴数字则优先判为波动"的兜底规则，测出来是**多余
# 且有害**的："降息概率60%"里的"降"、"持股比例升至25%"里的"升"都会命中动词，
# 反而把本该排除的放行了。先判非波动、不做动词覆盖，9 条用例全过。
_PCT_NOT_MOVE_RE = re.compile(
    r"关税|税率|征税|利率|占比|比例|份额|股权|持股|概率|胜率|收益率|准备金率|"
    # 2026-07-30 追加：同比/环比与持仓变动类。触发案例："全球央行二季度购金增
    # 62%（同比）"被读成 62% 的行情波动，单源快讯冲到首屏 #4。冲击力因子要的
    # 是"市场现在动了多少"（日内/短线剧烈波动），同比/环比的年度累计变化和
    # 央行购金量这类**数量**变化都不是它——即使真是价格的同比涨幅（"比特币
    # 同比涨120%"），那也是叙事回顾而非冲击，排除同样正确。
    r"同比|环比|购金|增持|减持|持仓|净买入|净卖出|净流入|净流出|受访|通胀|"
    # 2026-07-31 全面检修抽样(5/5误读)追加。四条命中原因全是词表漏词——不是
    # 窗口宽度：①「审废加密税」pct=20，黑名单只收了"关税/税率/征税"这几个固
    # 定复合词，裸字"税"不在表里，"个税/房产税/加密税"这类任意复合词全漏网，
    # 故直接加裸字"税"（5 字符窄窗下无需担心误伤真实跌幅，见下方英文同款教训）；
    # ②「关税重启覆盖99%进口」，"覆盖/覆盖率"本身没进表；③④「EPS/营收超预
    # 期30.67%」「目标价上调5.1%」，超预期/不及预期是财报与分析师预期的比较
    # 值、目标价是分析师给的估值锚，都不是股价——注意不能反向加"营收/EPS"整
    # 词，那会把"营收不及预期股价跌12%"这种**真跌幅**也错杀，只排除"比较动
    # 作"本身的词。「沙特赤字收窄75%」同族追加"收窄"。
    r"税|覆盖|超预期|不及预期|高于预期|低于预期|目标价|锁仓|持有率|收窄|"
    # 2026-08-02 全平台测试时**出现在首屏可见位置**的漏网词。只补这几个是
    # 有意的：继续无限扩表是收益递减（见本文件 opt-in 那段说明），但这几个
    # 是用户打开就能看到的，属于"人眼一看就能发现"的底线范畴。
    #   · 市占率/占率  —— "比特币市占率升破58%" 排到首屏 #5
    #   · 最大涨幅/最大跌幅/平均回报 —— "8月季节性回报" 拿历史极值 65.32% 排 #3
    r"市占率|占率|市占|最大涨幅|最大跌幅|平均回报|回报率|季节性|历史均值|中位数|"
    # 英文侧同族词。教训：中文标题排除了，title_en 的 "gold buying jumps 62%"
    # 又把 62 放了进来——extract 扫的是 title_zh+title_en+短摘要拼接文本，
    # 排除表必须双语对齐，只堵一种语言等于没堵。target 单独加会跟 Target
    # Corp(零售商)真实涨跌撞车，所以用 "target price" 整词组。
    r"tariff|tax|stake|odds|probability|yoy|y/y|qoq|"
    r"buying|purchas|holding|accumulat|inflow|outflow|year[- ]on[- ]year|"
    r"inflation|cpi|beat|miss(?:es|ed)?\s+estimate|target price|narrow|"
    # 2026-08-02 英文侧补齐。中文补完后首屏那两条**照样没修好**，因为
    # extract 扫的是 title_zh + title_en + 摘要拼接文本，英文标题
    # "Bitcoin dominance rises above 58%" / "Upbit share rises to 67.4%"
    # 从英文侧绕了过去——本文件几行之上就写着"排除表必须双语对齐，只堵
    # 一种语言等于没堵"，还是又犯了一次。
    # 注意 "share" 只能以词组形式加（market share / share rises），裸词会撞
    # "Tesla shares surge 12%" 这类真实涨跌。
    r"dominance|market share|share (?:rises|falls|climbs|drops)|"
    r"seasonal|seasonality|median return|average return|"
    r"all[- ]time (?:high|low)|share of",
    re.IGNORECASE,
)
# 2026-07-31 5→8：生产实测「机构加密交易占比升至创纪录的72%」漏判——"占比"
# 早在黑名单里，但"占比升至创纪录的"6 个字的修饰语把它推出 5 字符窗口。8 是
# 双重约束下精确算出的边界，不是拍脑袋放宽：既要覆盖上面这个真实案例（"占比"
# 在数字前 8 字符内），又不能碰到本文件另一条硬约束——"关税威胁下比特币暴跌
# 8%"这个反例要求"关税"必须留在窗口外（真实下跌不能被误伤），"关税"在该句
# 数字前第 10 字符，窗口取 8 时两个约束同时满足（验证脚本见 WORKLOG #89）。
_PCT_WINDOW_BEFORE, _PCT_WINDOW_AFTER = 8, 6

# ── 价格变动指示词（2026-08-02，口径反转）────────────────────────────
#
# 此前的思路是"**默认**这个百分数就是涨跌幅，除非它附近命中排除词"。
# 实测证明这个方向本身就错了：百分比在财经文本里能表示的东西是一个**无穷集合**
# ——支持率、占比、覆盖率、税率、波动率、整合率、市值占GDP比、门票处理量……
# 排除表永远追不完，今天已经连补三轮还在漏（"满额信号100%"排到了首屏第一）。
#
# 反过来，"表达价格变动"的说法是一个**小而稳定的集合**。所以改为 opt-in：
# 数字附近必须出现价格变动指示词，才认定它是涨跌幅。
#
# 实测（近 7 天 2582 条有 pct 的条目）：
#   · 改后仍判为涨跌幅 1169 条（45%），抽样全部是真涨跌
#     （AVAX 涨 8.24%、BANK 涨 13%、加密货币跌幅 29-47%…）
#   · 被排除 1413 条（54%），抽样全部不是涨跌
#     （售油 180 亿、市值占 GDP 137%、全面战争、DRAM 概念股…）
# 也就是说改之前，**这个占权重最高（23.5%）的因子有一半以上的幅度信号是错的**。
#
# 注意与历史教训的区别：代码里曾记录"加动词覆盖规则是多余且有害的"——那次是把
# 动词当作**凌驾于排除表之上的覆盖**（命中动词就强行判为波动），所以"降息概率
# 60%"里的"降"会把已被正确排除的放行。这次动词是**前置必要条件**，排除表仍在
# 后面把关，两道是与的关系不是或的关系，方向完全不同。
_PRICE_MOVE_RE = re.compile(
    r"涨|跌|升|降|飙|挫|崩|泻|反弹|回调|走高|走低|翻倍|腰斩|重挫|大涨|大跌|"
    r"surge|plunge|jump|drop|fall|rise|gain|lose|rally|slump|soar|sink|"
    r"climb|tumble|spike|crash|dip|advance|decline|up|down",
    re.IGNORECASE)
# 指示词的搜索窗口比排除词宽：涨跌动词与数字之间常隔着标的名
# （"比特币24小时涨8.24%"、"AVAX突破6.50美元，24小时涨8.24%"）。
# 12 是实测值——8 会漏掉"24小时涨"这类常见句式。
_MOVE_WINDOW = 12

# 无数字但本身就意味着剧烈波动的词。命中直接给满分——"熔断""崩盘"不需要
# 再看百分比，它们的语义就是极端。
_EXTREME_WORDS_RE = re.compile(
    r"熔断|崩盘|暴跌|暴涨|涨停|跌停|重挫|狂飙|闪崩|清零|归零|"
    r"circuit breaker|crash|plunge|plummet|soar|surge|collapse|rout",
    re.IGNORECASE)


def extract_magnitude_pct(text: str) -> float | None:
    """从标题/摘要里抽最大的百分比幅度。返回 None 表示没抽到。"""
    if not text:
        return None
    vals = []
    for m in _PCT_RE.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        # >100% 的多半是"上涨800倍""市值占GDP137%"这类非涨跌幅语境，
        # 不参与冲击力判定，避免把统计数字当成暴涨暴跌。
        if not (0 < v <= 100):
            continue
        # 数字前后紧邻"关税/税率/持股/概率"这类词时，这个百分数是**税率/比例**
        # 而不是涨跌幅，跳过（见 _PCT_NOT_MOVE_RE 的说明）。
        # opt-in 前置闸：附近没有价格变动指示词，就不认它是涨跌幅。
        # 放在所有排除规则**之前**——先问"这看起来像涨跌吗"，再问"有没有反证"。
        move_window = text[max(0, m.start() - _MOVE_WINDOW):m.end() + _MOVE_WINDOW]
        if not _PRICE_MOVE_RE.search(move_window):
            continue

        head = text[max(0, m.start() - _PCT_WINDOW_BEFORE):m.start()]
        tail = text[m.end():m.end() + _PCT_WINDOW_AFTER]
        # 英文窗口按**词**取，不按字符（2026-07-30）："gold buying jumps 62%"
        # 里 buying 距百分号 12 个字符，5 字符窗口永远够不着；而把字符窗口放宽
        # 到 20 会让中文误杀（"关税威胁下比特币暴跌8%"的 8% 会命中 16 字外的
        # 关税）。所以中文保持 5 字符窄窗，英文另取紧邻的前后各 3 个单词。
        head_words = " ".join(re.findall(r"[A-Za-z][A-Za-z'\-/]*",
                                         text[max(0, m.start() - 40):m.start()])[-3:])
        tail_words = " ".join(re.findall(r"[A-Za-z][A-Za-z'\-/]*",
                                         text[m.end():m.end() + 40])[:3])
        if (_PCT_NOT_MOVE_RE.search(head) or _PCT_NOT_MOVE_RE.search(tail)
                or _PCT_NOT_MOVE_RE.search(head_words)
                or _PCT_NOT_MOVE_RE.search(tail_words)):
            continue
        # 四位年份锚定的百分数（"塞地2025年升值约41%"）是**年度尺度**的回顾
        # 叙事，不是冲击力要的短线波动——日期在句首时（"2026年7月30日，比特币
        # 暴跌8%"）年份距百分号远超 9 字符，不会误伤。
        if re.search(r"\d{4}年", text[max(0, m.start() - 9):m.start()]):
            continue
        vals.append(v)
    return max(vals) if vals else None


def _magnitude_score(pct: float | None, text: str) -> float:
    if _EXTREME_WORDS_RE.search(text or ""):
        return 1.0
    if pct is None:
        return 0.10
    if pct >= 15:
        return 1.00
    if pct >= 8:
        return 0.75
    if pct >= 4:
        return 0.55
    if pct >= 2:
        return 0.35
    return 0.10


def _resonance_score(event: dict) -> float:
    """权威共振：几家 authority≥4 的独立机构在报同一件事。

    与 H 因子里的信源数不同：H 数的是**所有**信源（含匿名 X 账号），
    这里只数**权威机构**，且不被社交互动稀释——"三家一线财经媒体同时报"
    本身就是"这是件大事"的强信号。
    """
    sources = event.get("sources") or []
    authoritative = 0
    top_tier = False
    # v4（2026-07-31）：只数**机构媒体/通讯社/一手 API**，社交与聚合/行情
    # 信号源一律不计。此前一个 5 分的 X KOL（cz_binance）和 CNBC 在这里
    # 完全等价——Lawrence 裁决"不合理"。个人影响力 ≠ 机构编辑权威：转推
    # 一条消息的 KOL 再多，也不构成"多家独立编辑室分别核实过"这个信号。
    _NON_MEDIA_TYPES = ("social", "web_search", "market_signal", "calendar")
    for s in sources:
        if (s.get("type") or "") in _NON_MEDIA_TYPES:
            continue
        try:
            a = int(s.get("authority") or 0)
        except (TypeError, ValueError):
            a = 0
        if a >= 4:
            authoritative += 1
        if a >= 5:
            top_tier = True
    if authoritative >= 3:
        return 1.00
    if authoritative == 2:
        return 0.65
    if top_tier:
        return 0.45
    return 0.15


def compute_punch(event: dict) -> dict:
    """返回 {"score": 0-1, "magnitude_pct": float|None}。

    取标题 + 短摘要做幅度提取——长摘要里常有历史对比数字（"较2020年涨40%"），
    会把冲击力判高。标题和短摘要说的是"现在发生了什么"。
    """
    title = " ".join(filter(None, [
        event.get("title_zh") or event.get("title") or "",
        event.get("title_en") or "",
    ]))
    text = " ".join(filter(None, [title, event.get("description_short_zh") or ""]))

    # 标题优先，且**标题里出现百分比却被判非涨跌时，整条不再取正文的**。
    #
    # 2026-08-02 首屏实测："韩国CEX低迷中Upbit份额升至67.4%" 标题里的 67.4 被
    # 正确拦下了（"份额"在窗口内），可正文里还有一句"份额由62.3%升至67.4%"——
    # 那里的"份额"距数字 8 字符以外，逃出了排除窗口，于是 extract 取全文最大值
    # 时又把它捡了回来，冲击力照样满分、照样排到首屏第二。
    #
    # 标题是这条新闻"在讲什么"的权威概括：它里面的百分比既然不是涨跌幅，
    # 正文里同一个数字更不会是。所以标题一旦给出否定答案，就不必再问正文。
    # 这不是又一个排除词，是换了个提问顺序——正文回落只在"标题压根没提百分比"
    # 时才发生（那种情况下正文的数字确实可能是主要信息）。
    if _PCT_RE.search(title):
        pct = extract_magnitude_pct(title)
    else:
        pct = extract_magnitude_pct(text)
    score = (W_PUNCH_MAGNITUDE * _magnitude_score(pct, text)
             + W_PUNCH_RESONANCE * _resonance_score(event))
    return {"score": _clamp(score), "magnitude_pct": pct}


# ── 合成 ─────────────────────────────────────────────────────────────

def compute_macro_score(event: dict, baseline: float,
                        now: datetime | None = None) -> dict:
    """算出七因子分与加权总分，返回可直接写库的字段字典。

    注意这里算的是 **BaseScore**——情绪同向/反转两个加分项**不在这里应用**，
    它们只在查询/展示时作为外层倍率生效（ADR-001 D2）。理由：加分项依赖
    `mood_score` 这个每天都在变的全局量，写进库会让跨天的分数不可比，
    而 importance_score 是策略实验室、去重、历史分析共同依赖的口径。
    """
    M = compute_impact(event)
    B = compute_breadth(event)
    T = compute_timeliness(event, now)
    punch = compute_punch(event)
    I = punch["score"]
    H = compute_hotness(event, baseline)
    A = compute_authority(event)
    Q = compute_quality(event)

    # v4：纯加权和，无任何信源特例（CNBC +0.05 已随硬覆盖一并移除，理由见
    # compute_authority 的 v4 注释）。改这条公式必须同步四处：本函数、
    # scripts/rescore_factors.py、scripts/qa_suite.py 的 SQL 镜像、
    # api/lab_tools.rank_pool——历史上每一处漏改都变成过真实事故。
    score = (W_IMPACT * M + W_BREADTH * B + W_TIME * T + W_PUNCH * I
             + W_HOT * H + W_AUTH * A + W_QUAL * Q)

    return {
        "score_market_impact": round(M, 4),
        "score_breadth":       round(B, 4),
        "score_timeliness":    round(T, 4),
        "score_punch":         round(I, 4),
        "score_hotness":       round(H, 4),
        "score_authority":     round(A, 4),
        "score_quality":       round(Q, 4),
        "punch_magnitude_pct": punch["magnitude_pct"],
        "importance_score":    round(score, 4),
        # 打分公式产出的分必须带上"是哪个版本产出的"，否则版本号只会覆盖手工
        # 重算的存量，新写入的行又会失去标记——两条路径都要标，缺一样等于没有。
        "scoring_version":     SCORING_VERSION,
    }


def score_events(events: list[dict], now: datetime | None = None) -> list[dict]:
    """给整批事件打分（批内共享同一个社交基准）。"""
    baseline = social_baseline(events)
    now = now or now_local()
    for event in events:
        event["scores"] = compute_macro_score(event, baseline, now)
    logger.info(f"Scored {len(events)} events (social baseline P95={baseline:.0f})")
    return events
