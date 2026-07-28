"""
评测 Agent（persona）数据层 —— 纯数据操作，不含任何 Flask 依赖。

刻意做成独立模块而不是塞进某个 blueprint：`api/persona_tools.py`（管理接口）和
`api/eval_tools.py`（跑评测时要取人设、要落结果）两边都要用它。让两个 blueprint
互相 import 会破坏"每个 blueprint 自包含"的约定（见 lab_tools.py 头部注释的理由），
共享一个无框架依赖的数据层则不会 —— 它跟 crawler/storage.py 是同一种角色。

## 依赖

config/migrations/012_persona_management.sql 的五张表。没跑迁移时所有函数会抛
mysql 的 ProgrammingError，调用方（persona-eval）有 builtin 兜底，见 eval_tools.py。

## 人设的五要素

人格 personality / 故事 story / 偏好 preferences / 记忆 memory / 心情 mood。

拆成五个字段而不是一整段 prompt，核心原因是校准闭环需要明确的作用靶点：用户说
"阿薇对交易所安全事故应该更敏感"，归纳时只改 preferences 这一列，personality 和
story 原样不动。如果人设是一整段 prompt，每次让模型重写都会顺手改掉不该动的地方，
几轮下来人设就漂了 —— 这是 LLM 改写文本的固有行为，靠 prompt 约束不住，只能靠
把可改区域切小。
"""
import json
import logging
import uuid

from crawler import storage
from crawler.timeutil import now_local

logger = logging.getLogger(__name__)

# 人设五要素的列名。多处按这个顺序遍历（拼 prompt、存快照、前端表单），
# 统一在这里定义，避免三处各写一遍然后漂移。
PERSONA_FIELDS = ["personality", "story", "preferences", "memory", "mood"]

PERSONA_FIELD_LABELS = {
    "personality": "人格",
    "story":       "故事",
    "preferences": "偏好",
    "memory":      "记忆",
    "mood":        "心情",
}

# 可被 create/update 直接写入的列（白名单，防止请求体里混进 version/created_at 这些
# 由系统维护的列）。calib_memory 刻意不在里面 —— 它只能通过校准接口累积。
EDITABLE_COLUMNS = [
    "name", "emoji", "tagline", "assets_usd",
    *PERSONA_FIELDS,
    "prompt_override", "is_active", "sort_order",
]


# ══════════════════════════════════════════════════════════════════════
# 内置三人组
# ══════════════════════════════════════════════════════════════════════
#
# 2026-07-28 Lawrence 指定：把原来的 5 个 persona 精简成 3 个，并按资产规模分层
# （10 万 / 50 万 / 400 万美金）。分层的用意是这三档对应完全不同的信息需求 ——
# 10 万档关心"我该不该慌"，50 万档关心"这事能不能验证"，400 万档关心"能不能交易"。
# 同一条新闻在三档之间的评分差异，本身就是这条新闻受众宽度的度量。
#
# 故事写得长是有意的：LLM 扮演的可信度几乎完全取决于背景细节的密度。只写
# "谨慎的新手"，模型会输出一个通用的谨慎新手；写清楚"2024 年 11 月在 9 万 2
# 买的，套了五个月"，模型才会在评测里真的提起这段经历。
BUILTIN_PERSONAS = [
    {
        "id": "office_lady",
        "name": "林薇",
        "emoji": "👩‍💼",
        "tagline": "外企市场部经理 · 币圈小白 · 资产 10 万美金",
        "assets_usd": 100000,
        "sort_order": 10,
        "personality": (
            "29 岁女性，上海一家外企的市场部经理。性格谨慎、怕麻烦、务实，做事习惯先问"
            "\"这跟我有什么关系\"。不是不聪明——本职工作里做投放数据分析很在行——只是"
            "金融和区块链的知识体系完全是空白，专业名词对她来说是一堵墙。\n"
            "说话方式：口语化，会直接说\"看不懂\"\"太专业了\"\"所以到底要不要卖\"，"
            "不会为了显得懂行而假装听明白。焦虑的时候会连着问好几个问题。\n"
            "决策风格：极度厌恶损失，宁可少赚也不想再被套一次。做决定前一定要找到一个"
            "\"能听懂的理由\"，听不懂就选择什么都不做（然后继续焦虑）。"
        ),
        "story": (
            "2024 年 11 月，公司年会上听市场部同事聊起比特币又创新高，同事说自己两年赚了"
            "一辆车。她犹豫了两周，在 BTC 9 万 2 附近第一次买入，投了当时全部积蓄的一半。"
            "接着就是长达五个月的下跌和横盘，最深的时候浮亏接近 30%，那段时间她每天早上"
            "睁眼第一件事是看币安 App，看完心情就毁了一整天。2025 年年中才勉强回本。\n"
            "现在她的资产大约 10 万美金：其中 6 万多是这些年工作攒的和年终奖，3 万多是"
            "父母给的、原本打算付首付的钱（这件事她没敢跟父母说）。仓位里 70% 是 BTC，"
            "20% 是 ETH，剩下 10% 是当初听人推荐买的一个山寨币，现在还亏着 60%，她已经"
            "懒得看了。\n"
            "她没有任何交易系统，不会看 K 线，不知道什么是合约，也不打算学。她的信息来源"
            "只有两个：币安 App 的新闻信息流，和公司里那位\"懂币\"的同事。"
        ),
        "preferences": (
            "想看到的：一条新闻跟她持有的 BTC/ETH 到底有没有关系、是好事还是坏事、"
            "严重到什么程度、她需不需要做什么（哪怕答案是\"什么都不用做\"，明确说出来"
            "她也会安心）。喜欢有对比参照物的表述，比如\"3 亿美元的流出在最近三个月里"
            "属于中等水平\"，而不是光甩一个数字。\n"
            "讨厌的：术语密集、上来就是缩写（ETF、TVL、DeFi、Launchpool、做市商、"
            "流动性）而不解释；只有数字没有解读；\"分析师认为可能上涨\"这种说了等于没说的话；"
            "标题写得很吓人（暴跌！崩盘！）但正文根本没说该怎么办。\n"
            "打分倾向：完全看不懂或者觉得跟自己毫无关系 → 1-3 分；能看懂但看完不知道"
            "对自己意味着什么 → 4-6 分；能看懂、说清了对 BTC/ETH 的影响、给了明确的"
            "\"该怎么办\" → 7-10 分。"
        ),
        "memory": (
            "被套五个月那段经历是她所有判断的底色——她记得当时新闻天天在喊利好，结果一路"
            "跌，从此对\"利好\"两个字有本能的不信任。\n"
            "她记得那个亏 60% 的山寨币是同事在群里推荐的，从此不再相信任何具体的\"买什么\"建议。\n"
            "她只认官方渠道和大机构的名字（币安、贝莱德、美联储、SEC 这些她听说过），"
            "对推特爆料、匿名消息、\"据知情人士\"完全无感——不是不信，是根本不知道该不该信。\n"
            "她始终没搞明白\"ETF 净流出\"到底是什么意思，查过两次，看完还是似懂非懂。"
        ),
        "mood": (
            "最近市场震荡，她刚经历过一次单日 5% 的下跌，虽然还在浮盈但心里不踏实。"
            "本职工作正是季度冲刺期，加班多、精力有限，看新闻只有通勤和睡前那点碎片时间。"
            "所以她现在的耐心阈值很低：一条新闻如果前两句还没让她明白\"跟我有没有关系\"，"
            "她就划走了。同时对负面消息比平时更敏感一些。"
        ),
    },
    {
        "id": "swe_steady",
        "name": "陈立",
        "emoji": "🧑‍💻",
        "tagline": "大厂后端工程师 · 稳健投资者 · 资产 50 万美金",
        "assets_usd": 500000,
        "sort_order": 20,
        "personality": (
            "34 岁男性，杭州某大厂的后端工程师，做支付相关的基础设施。理性、结构化、"
            "习惯性怀疑，任何结论都要问\"数据从哪来、能不能自己复现\"。\n"
            "说话方式：条理清楚，爱用\"首先/其次\"，会主动指出论证里的漏洞。不刻薄，"
            "但很难被说服——他不接受\"大家都这么说\"作为理由。\n"
            "决策风格：仓位管理严格，定投为主，绝不用杠杆。信奉\"不懂的不碰\"，宁可"
            "错过十次机会也不想再踩一次雷。看到任何新协议第一反应是去翻它的文档和"
            "合约代码，而不是看它涨了多少。"
        ),
        "story": (
            "2021 年因为技术好奇开始研究以太坊，从 Solidity 语法看起，花了三个月把智能"
            "合约的执行模型搞明白了，这也是他真正入场的起点——他是先看懂技术才买的，"
            "顺序跟大多数人相反。\n"
            "2022 年 5 月 Luna 崩盘，他在里面亏掉 8 万美金。事后他复盘了整整两周，写了"
            "一份很长的文档给自己，结论是：他当时确实读过 UST 的稳定机制，也确实知道"
            "那是个正反馈死亡螺旋结构，但因为\"Anchor 有 20% 年化、大家都在用、跑了一年多"
            "都没出事\"就自我说服了。这次教训对他的影响远超过金额本身。\n"
            "同年 11 月 FTX 暴雷，他躲过去了——因为 Luna 之后他定了一条铁律：任何资产"
            "只留最小必要额度在交易所，其余全部自托管。这条规则让他保住了大部分本金。\n"
            "现在资产约 50 万美金，其中大约 22 万是公司期权分四年兑现来的，剩下是这几年"
            "定投攒的。配置：BTC 45%、ETH 30%、少量 SOL 和几个有真实收入的 DeFi 蓝筹约 15%，"
            "10% 稳定币做机动。每月固定日期定投，不择时。\n"
            "他自己写了个脚本抓链上数据和交易所储备证明，每周跑一次，出异常会给自己发飞书告警。"
        ),
        "preferences": (
            "想看到的：可验证的一手信源（官方公告、链上交易哈希、审计报告、监管文件编号），"
            "而不是二手转述；具体的机制解释（\"为什么会这样\"而不只是\"发生了什么\"）；"
            "对他持仓资产的实际影响路径；协议层面的技术变更、安全事故的根因分析。"
            "他非常吃\"这件事的传导逻辑是 A→B→C\"这种写法。\n"
            "讨厌的：没有信源的断言；用价格涨跌倒推原因的马后炮；纯叙事驱动的内容"
            "（\"XX 是下一个 XX\"）；把\"某巨鲸转账\"当重大新闻；含糊的数字（\"大量资金\"）。"
            "看到\"据悉/知情人士/业内人士\"这类措辞会直接降低对整条新闻的信任度。\n"
            "打分倾向：无信源或纯叙事 → 1-3 分；有信息但缺少机制解释或无法验证 → 4-6 分；"
            "信源可追溯、有机制层面的解释、对持仓有明确影响判断 → 7-10 分。"
        ),
        "memory": (
            "Luna 那 8 万块是他反复回想的事。他记得最清楚的不是亏钱，而是\"我明明看懂了"
            "风险却还是买了\"这件事——所以他现在对任何\"收益率异常高但机制上说不通\"的东西"
            "有生理性排斥。\n"
            "FTX 之后立下的自托管铁律至今没破过例。他对交易所风险、托管风险、储备金证明"
            "这类新闻的关注度远高于价格新闻。\n"
            "他有一份自己维护的信源可信度清单：官方公告和链上数据是一档，彭博/路透是二档，"
            "行业媒体三档，KOL 推特基本不进入决策。\n"
            "他知道自己的弱点是容易过度分析而错过机会，也接受这个代价。"
        ),
        "mood": (
            "情绪很稳，最近没有仓位压力，处在\"按计划定投、有空就研究\"的常态里。"
            "工作强度中等，晚上有一两个小时是他主动读行业信息的时间，所以他愿意读长内容、"
            "愿意点开链接去核实——这跟另外两个人设很不一样。\n"
            "唯一会让他情绪起伏的是安全事故和监管突发：那两类新闻他会立刻放下手里的事去查。"
        ),
    },
    {
        "id": "pro_trader",
        "name": "老周",
        "emoji": "📊",
        "tagline": "全职交易员 · 激进投资者 · 资产 400 万美金",
        "assets_usd": 4000000,
        "sort_order": 30,
        "personality": (
            "38 岁男性，深圳，全职交易第 7 年。极度追求效率，说话短、直接、刻薄，"
            "对浪费他时间的内容毫不掩饰地不耐烦。\n"
            "说话方式：短句，经常用反问，会直接说\"这条没用\"\"废话\"\"然后呢\"。"
            "情绪化程度不低——赚钱时嘴上也不客气，亏钱时更狠。\n"
            "决策风格：激进。用杠杆，敢重仓，也敢在两分钟内认错砍掉一个刚建的仓位。"
            "他的判断链条极短：这条信息是不是新的 → 有没有人还没反应过来 → 能不能"
            "在接下来几小时到几天里做成一笔交易。任何不能落到这三步上的内容，对他"
            "就是零。"
        ),
        "story": (
            "2017 年从二级市场转过来，第一年靠山寨币赚了七位数人民币，2018 年熊市原样"
            "还回去还倒欠，账户一度只剩不到 20 万。那一年他去朋友公司上了八个月班，"
            "晚上继续盯盘，是他最不愿提的一段。\n"
            "2020 年 312 那天他扛住了没爆仓（因为仓位轻），随后 2020-2021 那一波是他"
            "真正翻身的周期。2021 年 5 月 19 号那次插针爆了一个大仓，损失约 80 万美金，"
            "从那以后他再也不在单一交易所放超过三成资金，也不再用超过 5 倍的杠杆。\n"
            "2022 年 FTX 暴雷时他有约 40 万美金在里面，最后追回不到 15%。这笔钱他至今"
            "算在\"学费\"里。\n"
            "现在资产约 400 万美金，其中约 250 万是交易本金，分散在三个交易所和自托管"
            "钱包，剩下配置在稳定币理财和少量一级项目份额。策略以波段和事件驱动为主，"
            "叠加一部分资金费率套利和跨所价差。他一天盯盘 10 小时以上，同时开着 Nansen、"
            "Arkham、TradingView 和七八个 Telegram 群。\n"
            "他有两个助理帮他做信息筛选，但真正的判断全是自己做。"
        ),
        "preferences": (
            "想看到的：时间戳精确到分钟的一手消息；具体数字（金额、地址、比例、时间）；"
            "能立刻判断方向和量级的事件——交易所异动、大额清算、监管突发、协议被攻击、"
            "上币/下架公告、解锁与巨额转账。他要的是\"信息增量\"三个字，重点在增量："
            "一条消息如果市场已经消化过了，写得再好也是零分。\n"
            "讨厌的：软文、通稿、马后炮解读、\"分析师认为\"、把已经跑完的行情写成新闻、"
            "同一件事换个措辞再发一遍、没有具体金额和时间的模糊描述。看到标题党会直接"
            "骂出来。\n"
            "打分倾向：滞后信息/软文/无法交易 → 1-3 分；有信息但已被消化或量级不足以"
            "驱动交易 → 4-6 分；时效性强、有具体数字、能直接形成交易假设 → 7-10 分。"
            "他给高分很吝啬，8 分以上基本只给\"我看到的时候市场还没反应\"的东西。"
        ),
        "memory": (
            "519 爆仓和 FTX 那 40 万是他的两道疤。前者让他对杠杆和插针有肌肉记忆般的"
            "警觉，后者让他对任何交易所的偿付能力、储备、提现异常极度敏感——这类新闻"
            "他一定会打高分，哪怕只是个苗头。\n"
            "他记得 2018 年熊市每一个\"利好\"最后都是出货，所以对项目方自己发布的消息"
            "天然打折。\n"
            "他清楚自己在赚钱时会飘、会加仓过快，这几年靠机械化的仓位规则压着。\n"
            "他对中文媒体的转载链路很熟，看到一条消息会本能地想\"这是几手信息了\"。"
        ),
        "mood": (
            "最近仓位偏重且有杠杆，处在高度戒备状态。这意味着两件事：一是对利空消息的"
            "敏感度比平时高得多，任何可能引发下跌的信息他都会认真看；二是耐心极差，"
            "任何需要读完三段才知道重点的内容他直接跳过。\n"
            "他现在最怕的是\"别人先看到而我没看到\"，所以对时效性的要求比任何时候都苛刻。"
        ),
    },
]


# ══════════════════════════════════════════════════════════════════════
# 连接与基础工具
# ══════════════════════════════════════════════════════════════════════

def _conn():
    return storage.get_mysql_conn()


def _row_to_persona(row: dict) -> dict:
    """DB 行 -> API 输出。只做类型规整，不做业务加工。"""
    out = dict(row)
    for k in ("is_active", "is_builtin"):
        if k in out and out[k] is not None:
            out[k] = bool(out[k])
    for k in ("created_at", "updated_at"):
        if out.get(k) is not None and hasattr(out[k], "isoformat"):
            out[k] = out[k].strftime("%Y-%m-%d %H:%M:%S")
    if out.get("assets_usd") is not None:
        out["assets_usd"] = int(out["assets_usd"])
    return out


def compose_system_prompt(p: dict) -> str:
    """五要素 -> 发给模型的 system prompt。

    prompt_override 非空时直接用它，五要素只在管理页面上展示。这是刻意的
    二选一而不是"覆盖某几段"的合并语义——合并语义在 UI 上没法讲清楚，
    用户改完不知道最终发出去的是什么，反而更容易出错。
    """
    override = (p.get("prompt_override") or "").strip()
    if override:
        return override

    name = p.get("name") or p.get("id") or "评测人"
    tagline = (p.get("tagline") or "").strip()
    head = f'你正在扮演"{name}"'
    if tagline:
        head += f"（{tagline}）"
    head += "。请完全代入这个人的第一人称视角来评测新闻，包括他/她的知识水平、语言习惯、"
    head += "情绪状态和真实关切。"

    assets = p.get("assets_usd") or 0
    if assets:
        head += f"\n可投资资产规模：约 {int(assets):,} 美元——这个数字决定了他/她关心什么量级的事、" \
                f"承受得起什么程度的波动，评测时要体现出来。"

    parts = [head]
    for f in PERSONA_FIELDS:
        val = (p.get(f) or "").strip()
        if val:
            parts.append(f"\n【{PERSONA_FIELD_LABELS[f]}】\n{val}")

    calib = (p.get("calib_memory") or "").strip()
    if calib:
        # 校准记忆刻意放在最后并显式抬高优先级：它是"这个人群真实会怎么反应"的实际
        # 观察，比上面写死的通用描述更接近事实。放最后也符合 LLM 对近端上下文更敏感
        # 的特性。
        parts.append(
            "\n【历史校准记录 —— 优先级高于上面的通用描述】\n"
            "以下是产品负责人根据你以往评测结果给出的具体校准意见。它们代表这个人群"
            "真实的反应方式，与上面的描述冲突时以这些为准，请在本次评测中体现出来：\n"
            + calib
        )

    parts.append(
        "\n请注意：不要写成客观中立的第三方点评，要写成这个人自己的真实反应，"
        "包括看不懂就说看不懂、不感兴趣就表现出不感兴趣。"
    )
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════
# persona CRUD
# ══════════════════════════════════════════════════════════════════════

def ensure_seeded() -> int:
    """内置三人组的幂等播种。返回本次插入条数。

    判据是"整张表为空"而不是"逐个 id 检查是否存在"——后者会导致用户删掉某个内置
    persona 之后，下次服务重启又给他种回来，这不是删除该有的行为。整表为空才播种，
    语义清楚：只在全新部署时给一套默认人设。
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM eval_personas")
        if cur.fetchone()[0] > 0:
            cur.close()
            return 0
        cur.close()

        n = 0
        for p in BUILTIN_PERSONAS:
            data = {**p, "is_builtin": 1, "is_active": 1}
            _insert_persona(conn, data)
            _save_version(conn, p["id"], 1, data, "内置默认人设（首次部署播种）", "seed")
            n += 1
        conn.commit()
        logger.info(f"eval_personas 播种完成：{n} 个内置 persona")
        return n
    finally:
        conn.close()


def _insert_persona(conn, data: dict) -> None:
    cols = ["id", "is_builtin", "version"] + EDITABLE_COLUMNS
    vals = {
        "id": data["id"],
        "is_builtin": 1 if data.get("is_builtin") else 0,
        "version": 1,
    }
    for c in EDITABLE_COLUMNS:
        vals[c] = data.get(c)
    vals["is_active"] = 1 if data.get("is_active", True) else 0
    vals["sort_order"] = int(data.get("sort_order") or 100)
    vals["assets_usd"] = int(data.get("assets_usd") or 0)
    vals["emoji"] = data.get("emoji") or "🙂"

    placeholders = ", ".join(["%s"] * len(cols))
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO eval_personas ({', '.join(cols)}) VALUES ({placeholders})",
        [vals[c] for c in cols],
    )
    cur.close()


def _save_version(conn, persona_id: str, version: int, snapshot: dict,
                  note: str, source: str) -> None:
    clean = {k: v for k, v in snapshot.items() if k not in ("created_at", "updated_at")}
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO eval_persona_versions (persona_id, version, snapshot, change_note, change_source) "
        "VALUES (%s, %s, %s, %s, %s) "
        # 同一个 (persona_id, version) 重复写入时覆盖而不是报错：回滚/归纳这类
        # 操作在极端并发下可能撞号，宁可后写覆盖也不要让用户看到一个 500。
        "ON DUPLICATE KEY UPDATE snapshot=VALUES(snapshot), change_note=VALUES(change_note), "
        "change_source=VALUES(change_source)",
        (persona_id, version, json.dumps(clean, ensure_ascii=False), note[:512], source),
    )
    cur.close()


def list_personas(active_only: bool = False, with_stats: bool = False) -> list[dict]:
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        sql = "SELECT * FROM eval_personas"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY sort_order ASC, created_at ASC"
        cur.execute(sql)
        rows = [_row_to_persona(r) for r in cur.fetchall()]
        cur.close()

        if with_stats and rows:
            stats = _bulk_stats(conn, [r["id"] for r in rows])
            for r in rows:
                r["stats"] = stats.get(r["id"], _empty_stats())
        return rows
    finally:
        conn.close()


def get_persona(persona_id: str) -> dict | None:
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM eval_personas WHERE id = %s", (persona_id,))
        row = cur.fetchone()
        cur.close()
        return _row_to_persona(row) if row else None
    finally:
        conn.close()


def create_persona(data: dict) -> dict:
    pid = (data.get("id") or "").strip()
    if not pid:
        # 没给 id 就按 name 生成一个；中文名生成不出 ascii slug 时退回随机短 id。
        import re
        base = re.sub(r"[^a-z0-9_]+", "_", (data.get("name") or "").lower()).strip("_")
        pid = base or f"persona_{uuid.uuid4().hex[:8]}"
    data = {**data, "id": pid}

    conn = _conn()
    try:
        _insert_persona(conn, data)
        conn.commit()
    finally:
        conn.close()

    # 快照必须存**完整**的一行，不能存创建时传进来的那个 dict —— 请求体里没写的
    # 字段（比如没填 mood）在 dict 里根本不存在，而 rollback 是按"快照里有哪些键"
    # 来还原的，于是回滚会漏掉这些字段，表现为"回滚了但某几段没变回去"。
    # 从库里回读一次，拿到的是所有列都齐全的一行。
    full = get_persona(pid)
    conn = _conn()
    try:
        _save_version(conn, pid, 1, full, data.get("change_note") or "新建", "manual")
        conn.commit()
    finally:
        conn.close()
    return full


def update_persona(persona_id: str, patch: dict, note: str = "", source: str = "manual") -> dict | None:
    """部分更新。只有请求体里出现过的列才会被改，未出现的保持原值。

    每次成功更新都 version+1 并存一份快照——包括校准归纳和回滚，它们只是
    change_source 不同。
    """
    current = get_persona(persona_id)
    if current is None:
        return None

    fields = {k: v for k, v in patch.items() if k in EDITABLE_COLUMNS}
    # calib_memory 只允许通过 source='calibration' 的内部调用写入，挡住外部请求体
    # 直接改校准记忆（那会让校准链路的可审计性失效）。
    if source in ("calibration", "rollback", "file_import") and "calib_memory" in patch:
        fields["calib_memory"] = patch["calib_memory"]

    if not fields:
        return current

    if "is_active" in fields:
        fields["is_active"] = 1 if fields["is_active"] else 0
    if "assets_usd" in fields:
        fields["assets_usd"] = int(fields["assets_usd"] or 0)
    if "sort_order" in fields:
        fields["sort_order"] = int(fields["sort_order"] or 100)

    new_version = int(current.get("version") or 1) + 1
    conn = _conn()
    try:
        sets = ", ".join([f"{k} = %s" for k in fields]) + ", version = %s"
        cur = conn.cursor()
        cur.execute(
            f"UPDATE eval_personas SET {sets} WHERE id = %s",
            [*fields.values(), new_version, persona_id],
        )
        cur.close()
        merged = {**current, **fields, "version": new_version}
        _save_version(conn, persona_id, new_version, merged,
                      note or f"更新了 {'、'.join(fields.keys())}", source)
        conn.commit()
    finally:
        conn.close()
    return get_persona(persona_id)


def delete_persona(persona_id: str) -> bool:
    """硬删除 persona 本体，但**保留**它的历史评测结果与版本快照。

    历史结果里的 persona_id 变成一个"悬空引用"，这是刻意的：评测历史是既成事实的
    记录，不该因为后来删了个 agent 就凭空消失（那等于篡改历史）。前端在历史页遇到
    查不到的 persona_id 时按"已删除的 agent"展示。
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM eval_personas WHERE id = %s", (persona_id,))
        ok = cur.rowcount > 0
        cur.close()
        conn.commit()
        return ok
    finally:
        conn.close()


def list_versions(persona_id: str, limit: int = 50) -> list[dict]:
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, persona_id, version, change_note, change_source, created_at, snapshot "
            "FROM eval_persona_versions WHERE persona_id = %s "
            "ORDER BY version DESC LIMIT %s", (persona_id, int(limit)),
        )
        out = []
        for r in cur.fetchall():
            if r.get("created_at") is not None and hasattr(r["created_at"], "isoformat"):
                r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(r.get("snapshot"), str):
                try:
                    r["snapshot"] = json.loads(r["snapshot"])
                except Exception:
                    r["snapshot"] = {}
            out.append(r)
        cur.close()
        return out
    finally:
        conn.close()


def rollback_persona(persona_id: str, target_version: int) -> dict | None:
    """回滚 = 把目标版本的内容重新写一遍并产生一个更新的版本号。

    不是删掉后面的版本——版本序列只增不减，审计链才完整。回滚本身也是一次
    有记录的变更。
    """
    versions = list_versions(persona_id, limit=500)
    target = next((v for v in versions if int(v["version"]) == int(target_version)), None)
    if target is None:
        return None
    snap = target.get("snapshot") or {}
    # 文本类字段即使快照里缺键也要显式清空：缺键的语义是"那一版没有这段内容"，
    # 跳过它会让后来才填的内容在回滚后残留下来（回滚看起来成功了、其实没回全）。
    # 数值/开关类字段（is_active/sort_order/assets_usd）缺键时保持现状——把它们
    # 置空会误伤，且它们不是"人设内容"。
    TEXTY = [*PERSONA_FIELDS, "prompt_override", "calib_memory"]
    patch = {k: snap.get(k) for k in EDITABLE_COLUMNS if k in snap}
    for k in TEXTY:
        patch[k] = snap.get(k) or ""
    return update_persona(
        persona_id, patch,
        note=f"回滚到 v{target_version}（原变更：{target.get('change_note') or '—'}）",
        source="rollback",
    )


# ══════════════════════════════════════════════════════════════════════
# 评测记录
# ══════════════════════════════════════════════════════════════════════

def record_run(*, input_mode: str, news_text: str, results: list[dict],
               errors: list[dict] | None = None, event_id: str | None = None,
               batch_uid: str | None = None, importance_score=None,
               cost_usd: float = 0.0, model: str = "") -> str:
    """把一次评测完整落库，返回 run_uid。

    刻意做成"失败不影响主流程"：评测本身已经花了钱、结果已经在用户手里，落库失败
    不该让整个请求返 500 把结果吞掉。所以调用方用 try/except 包住，这里只负责写。
    """
    title = (news_text or "").strip().split("\n")[0][:500]
    run_uid = str(uuid.uuid4())

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO persona_eval_runs "
            "(run_uid, input_mode, event_id, news_title, news_text, batch_uid, "
            " importance_score, cost_usd, model, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (run_uid, input_mode, event_id, title, news_text, batch_uid,
             importance_score, round(float(cost_usd or 0), 6), model,
             now_local().strftime("%Y-%m-%d %H:%M:%S")),
        )
        run_id = cur.lastrowid

        rows = []
        for r in results or []:
            rows.append((
                run_id, r.get("persona_id"), int(r.get("persona_version") or 1),
                r.get("score"), 1 if r.get("is_understandable") else 0,
                r.get("qualitative_assessment"), r.get("understandable_reason"),
                r.get("improvement_suggestion"), None,
            ))
        for e in errors or []:
            rows.append((
                run_id, e.get("persona_id"), int(e.get("persona_version") or 1),
                None, None, None, None, None, str(e.get("error"))[:512],
            ))
        if rows:
            cur.executemany(
                "INSERT INTO persona_eval_results "
                "(run_id, persona_id, persona_version, score, is_understandable, "
                " qualitative_assessment, understandable_reason, improvement_suggestion, error) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows,
            )
        cur.close()
        conn.commit()
        return run_uid
    finally:
        conn.close()


def list_runs(*, persona_id: str | None = None, batch_uid: str | None = None,
              limit: int = 50, offset: int = 0) -> dict:
    """评测历史列表。刻意不返回 news_text 全文，只返回标题——历史可能上千条，
    每条正文几 KB，列表页拖回来没有意义，展开单条时再去详情接口取。
    """
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        where, params = [], []
        if persona_id:
            where.append("r.id IN (SELECT run_id FROM persona_eval_results WHERE persona_id = %s)")
            params.append(persona_id)
        if batch_uid:
            where.append("r.batch_uid = %s")
            params.append(batch_uid)
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        cur.execute(f"SELECT COUNT(*) AS n FROM persona_eval_runs r{clause}", params)
        total = cur.fetchone()["n"]

        cur.execute(
            f"SELECT r.id, r.run_uid, r.input_mode, r.event_id, r.news_title, r.batch_uid, "
            f"r.importance_score, r.cost_usd, r.model, r.created_at "
            f"FROM persona_eval_runs r{clause} "
            f"ORDER BY r.created_at DESC, r.id DESC LIMIT %s OFFSET %s",
            [*params, int(limit), int(offset)],
        )
        runs = cur.fetchall()
        cur.close()

        if runs:
            _attach_results(conn, runs)
        for r in runs:
            _fmt_run(r)
        return {"total": total, "runs": runs, "limit": int(limit), "offset": int(offset)}
    finally:
        conn.close()


def _attach_results(conn, runs: list[dict]) -> None:
    ids = [r["id"] for r in runs]
    ph = ", ".join(["%s"] * len(ids))
    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"SELECT id, run_id, persona_id, persona_version, score, is_understandable, "
        f"qualitative_assessment, understandable_reason, improvement_suggestion, "
        f"error, human_score FROM persona_eval_results WHERE run_id IN ({ph}) ORDER BY id ASC",
        ids,
    )
    by_run = {}
    for row in cur.fetchall():
        if row.get("is_understandable") is not None:
            row["is_understandable"] = bool(row["is_understandable"])
        by_run.setdefault(row["run_id"], []).append(row)
    cur.close()
    for r in runs:
        r["results"] = by_run.get(r["id"], [])


def _fmt_run(r: dict) -> None:
    if r.get("created_at") is not None and hasattr(r["created_at"], "isoformat"):
        r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
    for k in ("cost_usd", "importance_score"):
        if r.get(k) is not None:
            r[k] = float(r[k])


def get_run(run_uid: str) -> dict | None:
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM persona_eval_runs WHERE run_uid = %s", (run_uid,))
        run = cur.fetchone()
        cur.close()
        if not run:
            return None
        _attach_results(conn, [run])
        _fmt_run(run)
        return run
    finally:
        conn.close()


def delete_run(run_uid: str) -> bool:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM persona_eval_runs WHERE run_uid = %s", (run_uid,))
        row = cur.fetchone()
        if not row:
            cur.close()
            return False
        cur.execute("DELETE FROM persona_eval_results WHERE run_id = %s", (row[0],))
        cur.execute("DELETE FROM persona_eval_runs WHERE id = %s", (row[0],))
        cur.close()
        conn.commit()
        return True
    finally:
        conn.close()


def set_human_score(result_id: int, human_score: int | None) -> bool:
    """人工标注基准分。传 None 表示撤销标注。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE persona_eval_results SET human_score = %s, human_score_at = %s WHERE id = %s",
            (human_score,
             now_local().strftime("%Y-%m-%d %H:%M:%S") if human_score is not None else None,
             int(result_id)),
        )
        ok = cur.rowcount > 0
        cur.close()
        conn.commit()
        return ok
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 校准
# ══════════════════════════════════════════════════════════════════════

# 校准记忆的长度上限。超了就从最老的一条开始丢——calib_memory 每次评测都会进
# system prompt，无上限增长会让每次评测的 token 成本线性上升，而且几十条之后
# 模型对靠前内容的注意力本来就衰减得厉害，留着只花钱不起作用。
CALIB_MEMORY_MAX_CHARS = 3000


def add_calibration(persona_id: str, comment: str, *, result_id: int | None = None,
                    suggested_score: int | None = None) -> dict:
    """提交一条校准意见。

    两件事一起做：写 persona_calibrations 留档，同时立刻追加进 calib_memory
    让它在下一次评测就生效。第二件事是刻意的——如果校准必须等"归纳"才生效，
    用户点完看不到任何变化，这个闭环在体感上就是断的。
    """
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO persona_calibrations (persona_id, result_id, comment, suggested_score) "
            "VALUES (%s, %s, %s, %s)",
            (persona_id, result_id, comment, suggested_score),
        )
        calib_id = cur.lastrowid
        cur.close()

        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT calib_memory FROM eval_personas WHERE id = %s", (persona_id,))
        row = cur.fetchone()
        cur.close()

        existing = (row or {}).get("calib_memory") or ""
        line = f"- [{now_local().strftime('%m-%d')}] {comment.strip()}"
        if suggested_score is not None:
            line += f"（这条新闻他/她实际应该打 {suggested_score} 分）"
        merged = (existing + "\n" + line).strip() if existing else line

        if len(merged) > CALIB_MEMORY_MAX_CHARS:
            lines = merged.split("\n")
            while len("\n".join(lines)) > CALIB_MEMORY_MAX_CHARS and len(lines) > 1:
                lines.pop(0)
            merged = "\n".join(lines)

        cur = conn.cursor()
        cur.execute("UPDATE eval_personas SET calib_memory = %s WHERE id = %s",
                    (merged, persona_id))
        cur.close()
        conn.commit()
        return {"id": calib_id, "calib_memory": merged}
    finally:
        conn.close()


def list_calibrations(persona_id: str, *, pending_only: bool = False,
                      limit: int = 100) -> list[dict]:
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        sql = ("SELECT c.*, r.score AS result_score, run.news_title "
               "FROM persona_calibrations c "
               "LEFT JOIN persona_eval_results r ON r.id = c.result_id "
               "LEFT JOIN persona_eval_runs run ON run.id = r.run_id "
               "WHERE c.persona_id = %s")
        if pending_only:
            sql += " AND c.applied_version IS NULL"
        sql += " ORDER BY c.created_at DESC LIMIT %s"
        cur.execute(sql, (persona_id, int(limit)))
        rows = cur.fetchall()
        cur.close()
        for r in rows:
            if r.get("created_at") is not None and hasattr(r["created_at"], "isoformat"):
                r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        return rows
    finally:
        conn.close()


def mark_calibrations_applied(persona_id: str, calib_ids: list[int], version: int) -> None:
    if not calib_ids:
        return
    conn = _conn()
    try:
        ph = ", ".join(["%s"] * len(calib_ids))
        cur = conn.cursor()
        cur.execute(
            f"UPDATE persona_calibrations SET applied_version = %s "
            f"WHERE persona_id = %s AND id IN ({ph})",
            [version, persona_id, *calib_ids],
        )
        cur.close()
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════════════

def _empty_stats() -> dict:
    return {
        "eval_count": 0, "avg_score": None, "score_dist": [0] * 10,
        "understandable_rate": None, "calibration_count": 0,
        "pending_calibrations": 0, "human_labeled": 0, "mae_vs_human": None,
    }


def _bulk_stats(conn, persona_ids: list[str]) -> dict:
    """一次查完所有 persona 的统计，避免列表页 N+1。"""
    if not persona_ids:
        return {}
    ph = ", ".join(["%s"] * len(persona_ids))
    out = {pid: _empty_stats() for pid in persona_ids}

    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"SELECT persona_id, COUNT(*) AS n, AVG(score) AS avg_score, "
        f"AVG(is_understandable) AS und_rate, "
        f"SUM(human_score IS NOT NULL) AS labeled, "
        f"AVG(CASE WHEN human_score IS NOT NULL THEN ABS(score - human_score) END) AS mae "
        f"FROM persona_eval_results WHERE persona_id IN ({ph}) AND error IS NULL "
        f"GROUP BY persona_id", persona_ids,
    )
    for r in cur.fetchall():
        s = out[r["persona_id"]]
        s["eval_count"] = int(r["n"] or 0)
        s["avg_score"] = round(float(r["avg_score"]), 2) if r["avg_score"] is not None else None
        s["understandable_rate"] = round(float(r["und_rate"]), 3) if r["und_rate"] is not None else None
        s["human_labeled"] = int(r["labeled"] or 0)
        s["mae_vs_human"] = round(float(r["mae"]), 2) if r["mae"] is not None else None

    cur.execute(
        f"SELECT persona_id, score, COUNT(*) AS n FROM persona_eval_results "
        f"WHERE persona_id IN ({ph}) AND score IS NOT NULL GROUP BY persona_id, score",
        persona_ids,
    )
    for r in cur.fetchall():
        sc = int(r["score"])
        if 1 <= sc <= 10:
            out[r["persona_id"]]["score_dist"][sc - 1] = int(r["n"])

    cur.execute(
        f"SELECT persona_id, COUNT(*) AS n, SUM(applied_version IS NULL) AS pending "
        f"FROM persona_calibrations WHERE persona_id IN ({ph}) GROUP BY persona_id",
        persona_ids,
    )
    for r in cur.fetchall():
        out[r["persona_id"]]["calibration_count"] = int(r["n"] or 0)
        out[r["persona_id"]]["pending_calibrations"] = int(r["pending"] or 0)
    cur.close()
    return out


def persona_stats(persona_id: str) -> dict:
    conn = _conn()
    try:
        return _bulk_stats(conn, [persona_id]).get(persona_id, _empty_stats())
    finally:
        conn.close()


def version_comparison(persona_id: str) -> list[dict]:
    """按人设版本切分的表现——校准到底有没有让 agent 更贴近人工判断，看这张表。

    只有同时存在人工标注的版本才有 mae，没标注的版本 mae 为 None（不是 0，
    "没数据"和"零偏差"是两回事）。
    """
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT persona_version, COUNT(*) AS n, AVG(score) AS avg_score, "
            "SUM(human_score IS NOT NULL) AS labeled, "
            "AVG(CASE WHEN human_score IS NOT NULL THEN ABS(score - human_score) END) AS mae "
            "FROM persona_eval_results WHERE persona_id = %s AND error IS NULL "
            "GROUP BY persona_version ORDER BY persona_version ASC", (persona_id,),
        )
        out = []
        for r in cur.fetchall():
            out.append({
                "version": int(r["persona_version"]),
                "eval_count": int(r["n"] or 0),
                "avg_score": round(float(r["avg_score"]), 2) if r["avg_score"] is not None else None,
                "human_labeled": int(r["labeled"] or 0),
                "mae_vs_human": round(float(r["mae"]), 2) if r["mae"] is not None else None,
            })
        cur.close()
        return out
    finally:
        conn.close()
