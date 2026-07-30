# -*- coding: utf-8 -*-
"""信源权威度单一事实源 —— crawler/authority_table.py（2026-07-31，PRD-05）

## 为什么有这个文件

此前权威度存在**两份互不同步的表**：sources.py 里的声明分、pipeline.py prompt
里的自然语言媒体名单。后果实测：Benzinga 声明 5 分但不在 prompt 名单里，LLM
按 aggregator 给 0.401（5 天 3408 条均值）；CNBC 靠硬覆盖补丁抬到 0.955。
Lawrence 裁决：去掉 CNBC 硬覆盖、全面重校准、"权威性看的是真权威，不是产量，
一定要像编辑一样好好地判断"。

从本文件起：**所有消费方（sources.py 声明分、LLM prompt 名单、权威共振因子、
QA 断言、对外文档）都从这一份数据出**。改权威分只改这里；QA 有断言钉住
sources.py / prompt 与本表一致，改了别处不改这里会直接红。

## 判分标尺（编辑视角，与产量无关）

  5  一手权威：监管/交易所官方公告渠道；全球一线通讯社与旗舰财经媒体
     （有独立采编、署名记者、更正制度、市场公认的定价能力）；
     加密垂类中具备同等编辑体制的头部（CoinDesk/TheBlock/吴说/BlockBeats）
  4  成熟二线：有真实编辑部与署名，但满足其一——零售化风格明显 / 垂类深度
     有限 / 品牌影响力不及一线（Benzinga、Forbes、SCMP、金色财经…）
  3  可用长尾：独立采编存在但深度浅，或聚合/转载占比高（Yahoo Finance、
     Followin、Investing.com、CryptoBriefing…）
  2  边缘：编辑质量勉强及格，仅作补充召回（NewsBTC）
  1/黑名单  内容农场：不打分，直接整条丢弃（见 web_search._BLOCKED_DOMAINS）

  X/社交账号单列：**媒体号与个人 KOL 一律 ≤4**——个人影响力 ≠ 机构编辑权威
  （cz_binance 再大也没有编辑部和更正制度）。仅"官方一手渠道"可到 5：监管
  机构官号、交易所官方公告号、安全公司事件通报号——它们不是媒体，是事件
  当事方/一手侦测方。配套：权威共振因子只统计机构媒体源，社交源一律不计
  （见 scoring._resonance_score），从公式层面保证 KOL ≠ CNBC。

每项带 note（定级依据）。**改分必须同时改 note**——三个月后没人记得为什么。
"""

# ── RSS / HTML / API 频道 ──────────────────────────────────────────────
# name → (authority, brand, note)
# brand 用于 prompt 渲染时按品牌去重（CNBC 四个频道渲染成一个 "CNBC"）。
CHANNELS = {
    # ---- 5 · 一线旗舰 ----
    "CNBC-TopNews":        (5, "CNBC",        "全球一线财经电视网，独立采编+署名+更正制度"),
    "CNBC-Economy":        (5, "CNBC",        "同上"),
    "CNBC-Investing":      (5, "CNBC",        "同上"),
    "CNBC-Finance":        (5, "CNBC",        "同上"),
    "Bloomberg-Markets":   (5, "Bloomberg",   "全球一线通讯社，终端级市场定价能力"),
    "Bloomberg-Economics": (5, "Bloomberg",   "同上"),
    "Bloomberg-Technology":(5, "Bloomberg",   "同上"),
    "Bloomberg-Politics":  (5, "Bloomberg",   "编辑权威=Bloomberg 整体；此前 4 分混淆了'频道相关性'与'编辑权威'，本次纠正"),
    "WSJ-Markets":         (5, "WSJ",         "道琼斯旗舰，一线"),
    "FT-Home":             (5, "FT",          "全球一线财经报"),
    "MarketWatch":         (5, "MarketWatch", "道琼斯旗下，独立编辑部"),
    "NikkeiAsia":          (5, "Nikkei Asia", "日经英文版，亚洲市场一线"),
    "CoinDesk":            (5, "CoinDesk",    "加密垂类事实上的通讯社，编辑体制完整"),
    "CoinDesk-Policy":     (5, "CoinDesk",    "同上"),
    "TheBlock":            (5, "TheBlock",    "加密垂类头部，调查报道能力强"),
    "吴说区块链":           (5, "WuBlockchain(吴说)", "中文加密一手爆料+核实体制，多次抢先且更正记录良好"),
    "BlockBeats快讯":       (5, "BlockBeats", "中文加密快讯头部，有编辑室（Hang Shang 同标定）"),
    "BlockBeats文章":       (4, "BlockBeats", "深度稿沉淀线，时效与快讯线分开计"),
    # ---- API 直连出版方 ----
    "dxFeed-MTNewswires":  (5, "MT Newswires(dxFeed)", "机构级新闻通讯社，经 dxFeed 分发，一手时间戳"),
    "Benzinga":            (4, "Benzinga",    "真实编辑部+署名记者+比CNBC快约2分钟，但零售财经风格/部分AI辅助成稿→4 不到 5（Lawrence 2026-07-31 裁决，此前 5 分导致 3408 条快讯整体上浮）"),
    # ---- 4 · 成熟二线 ----
    "Forbes-Business":     (4, "Forbes",      "老牌商业媒体，撰稿人体制质量波动"),
    "SCMP-Business":       (4, "SCMP",        "港区一线英文报，全球影响力二线"),
    "SCMP-GlobalEcon":     (4, "SCMP",        "同上"),
    "Cointelegraph":       (4, "Cointelegraph", "加密二线头部，标题党倾向扣一档"),
    "Decrypt":             (4, "Decrypt",     "加密二线，编辑质量稳定"),
    "Blockworks":          (4, "Blockworks",  "加密二线，机构向研究有深度"),
    "TheDefiant":          (4, "TheDefiant",  "DeFi 垂类头部，面窄"),
    "TechFlow深潮":         (4, "TechFlow",    "中文加密二线，编译+原创混合"),
    "金色财经":             (4, "金色财经",     "中文老牌，有编辑部但软文/通稿占比高→4 封顶；S/A 产出高是产量效应，权威性不看产量（Lawrence 2026-07-31 裁决）"),
    "ChainCatcher":        (4, "ChainCatcher", "中文加密二线，原创比例尚可"),
    "PANews":              (4, "PANews",      "中文加密二线，有编辑室（Hang Shang 同标定）"),
    # ---- 3 · 可用长尾 ----
    "YahooFinance":        (3, "Yahoo Finance", "以聚合分发 Reuters/AP/IBD 稿为主，原创少→由 4 下调（真权威口径：聚合平台≠出版方）"),
    "Followin快讯":         (3, "Followin",    "聚合转载为主→由 4 下调"),
    "KoreaHerald":         (3, "Korea Herald", "韩国英文报，市场报道深度有限"),
    "Investing-Crypto":    (3, "Investing.com", "行情站新闻线，编译为主"),
    "Investing-Econ":      (3, "Investing.com", "同上"),
    "CryptoBriefing":      (3, "CryptoBriefing", "独立小编辑部，深度浅；S/A 多为产量效应"),
    "BeInCrypto":          (3, "BeInCrypto",  "量产型，质量波动大"),
    "Bitcoin.com":         (3, "Bitcoin.com", "自带立场（BCH 系公司媒体），需交叉验证"),
    "CryptoSlate":         (3, "CryptoSlate", "量产型长尾"),
    "AMBCrypto":           (3, "AMBCrypto",   "量产型长尾，SEO 倾向"),
    "U.Today":             (3, "U.Today",     "量产型长尾，标题党倾向"),
    "CoinJournal":         (3, "CoinJournal", "长尾"),
    "Protos":              (3, "Protos",      "有调查报道亮点但体量小"),
    # ---- 2 · 边缘 ----
    "NewsBTC":             (2, "NewsBTC",     "2026-07-26 裁决自黑名单移出：11 条实测 7 条 VERIFIED 零谣言，但独立采编深度有限"),
}

# ── X 账号 ────────────────────────────────────────────────────────────
# handle → (authority, category, note)
# 上限规则见文件头：官方一手渠道（regulator/exchange官号/安全通报）可 5，
# 媒体号与个人 KOL 一律 ≤4。
X_ACCOUNTS = {
    # ---- 5 · 官方一手 ----
    "SECGov":         (5, "regulator", "监管机构官号=一手公告，不是媒体"),
    "binance":        (5, "exchange",  "交易所官方公告渠道，第一方事实"),
    "binancezh":      (5, "exchange",  "同上（中文）"),
    "peckshield":     (5, "security",  "安全事件一手侦测方，历史准确率高"),
    "SlowMist_Team":  (5, "security",  "同上"),
    # ---- 4 · 媒体号 / 头部个人（2026-07-31 起个人与媒体号封顶 4）----
    "cz_binance":     (4, "kol",       "个人影响力≠机构编辑权威，由 5 下调（Lawrence 裁决：与 CNBC 等价'不合理'）"),
    "heyibinance":    (4, "kol",       "同上，由 5 下调"),
    "WuBlockchain":   (4, "media",     "吴说英文镜像号；主品牌权威计在 RSS 主渠道，镜像号降一档，由 5 下调"),
    "bwenews":        (4, "media",     "快讯搬运为主，由 5 下调"),
    "lookonchain":    (4, "onchain",   "链上分析号，非编辑机构，由 5 下调"),
    "wublockchain12": (4, "media",     "吴说中文镜像"),
    "BlockBeatsAsia": (4, "media",     "BlockBeats 镜像"),
    "PANewsCN":       (4, "media",     "PANews 镜像"),
    "Tree_of_Alpha":  (4, "media",     "快讯速报，命中率好但无编辑体制"),
    "WatcherGuru":    (4, "media",     "快讯号，偶有夸大"),
    "solidintel_x":   (4, "media",     "情报聚合"),
    "OdailyChina":    (4, "media",     "星球日报官号"),
    "Foresight_News": (4, "media",     "Foresight 官号"),
    "CoinDesk":       (4, "media",     "CoinDesk 镜像号（主品牌计在 RSS）"),
    "spotonchain":    (4, "onchain",   "链上追踪"),
    "EmberCN":        (4, "onchain",   "链上追踪（中文）"),
    "glassnode":      (4, "onchain",   "链上数据商"),
    "whale_alert":    (4, "onchain",   "大额转账播报，机械可靠"),
    "DefiLlama":      (4, "onchain",   "TVL 数据事实源"),
    "ai_9684xtpa":    (4, "onchain",   "链上追踪（中文）"),
    "MessariCrypto":  (4, "research",  "研究机构官号"),
    "CertiKAlert":    (4, "security",  "安全通报，误报率高于慢雾/派盾故 4"),
    "KobeissiLetter": (4, "macro",     "宏观评论号，观点性强"),
    "BinanceResearch":(4, "exchange",  "研究线（公告线才是 5）"),
    # ---- 3 ----
    "santimentfeed":  (3, "research",  "情绪数据商"),
    "OnchainLens":    (3, "onchain",   "长尾链上号"),
    "unusual_whales": (3, "macro",     "美股期权流向号，噱头浓"),
}

# ── Binance Square 媒体号 ─────────────────────────────────────────────
# 现状：BinanceSquare 抓取整体停用（无发布时间，曾是陈旧新闻事故源头，见
# crawler/staging.DISABLED_SOURCES）。若未来恢复，按下列默认策略执行：
SQUARE_POLICY = {
    "default_authority": 3,      # 平台号≤3：转载为主，无独立编辑体制
    "cap": 4,                    # 个别有独立采编的头部媒体入驻号最高 4
    "time_trust": "aggregator",  # 平台分发时间≠原文发布时间，走聚合器闸
}


def channel_authority(name: str, default: int = 2) -> int:
    ent = CHANNELS.get(name)
    return ent[0] if ent else default


def x_weight(handle: str, default: int = 3) -> int:
    ent = X_ACCOUNTS.get(handle)
    return ent[0] if ent else default


def render_prompt_guidance() -> str:
    """把分级表渲染成 prompt 里 score_authority 的判分指引。

    这行字符串会拼进 SYSTEM_PROMPT（见 crawler/pipeline.py），QA 有断言
    verify 渲染结果确实在 prompt 里——保证 LLM 看到的名单永远等于本表。
    按 brand 去重（CNBC 四频道→一个词），控制 token。

    ⚠️ 改本表会改变 prompt hash → enrich 桥缓存整体失效，下一轮起由桥用
    公司额度重新预热。所以：批量改、低频改，不要一天调多次。
    """
    # 每个品牌只在其**最高档**出现一次：BlockBeats 快讯 5 / 文章 4，若按档
    # 各自去重会在两档都出现，LLM 无所适从。
    best = {}
    for name, (a, brand, _) in CHANNELS.items():
        if a > best.get(brand, 0):
            best[brand] = a

    def brands(auth):
        seen, out = set(), []
        for name, (a, brand, _) in CHANNELS.items():
            if best.get(brand) != auth or brand in seen:
                continue
            seen.add(brand)
            out.append(brand)
        return out

    crypto_kw = ("Coin", "Block", "吴说", "TechFlow", "金色", "PANews", "Chain",
                 "Defiant", "Decrypt", "Crypto", "Bitcoin", "BTC", "U.Today",
                 "AMB", "BeIn", "Protos", "Followin")
    t5 = brands(5)
    t5_main = [b for b in t5 if b not in
               {"CoinDesk", "TheBlock", "WuBlockchain(吴说)", "BlockBeats"}]
    t5_crypto = [b for b in t5 if b in
                 {"CoinDesk", "TheBlock", "WuBlockchain(吴说)", "BlockBeats"}]
    t4 = brands(4)
    t3 = brands(3)
    return (
        "- score_authority: official announcement / regulator / exchange notice = 0.9+; "
        f"top wire & flagship media ({'/'.join(t5_main)}; crypto: {'/'.join(t5_crypto)}) = 0.75-0.89; "
        f"established second-tier ({'/'.join(t4)}-tier) = 0.50-0.74; "
        f"syndication-heavy or long-tail ({'/'.join(t3)}-tier) = 0.35-0.55; "
        "aggregator/search-only = 0.30-0.49; anonymous/unknown ≤ 0.30; rumors ×0.7"
    )
