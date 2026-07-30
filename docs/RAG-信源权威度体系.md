> ⚠️ **本文档已被取代（2026-07-31）**：权威分级表与判分逻辑见 `docs/信源权威分级表.md`（由单一事实源 `crawler/authority_table.py` 自动生成）；架构决策沉淀进 `docs/prd/PRD-05-信源权威度统一.md`。本文仅留作问题发现过程的记录。

# B9 信源权威度体系 · 交接文档（RAG）

**受众**：算法研发同事（把服务做到线上）
**日期**：2026-07-30　**对应代码版本**：`scoring_version = 3`
**问题背景**：Hang Shang 问「信息来源的权威分怎么定的」「square 媒体号 / X 媒体号 / Benzinga 是不是都要有账号维度的等级配置 file」

---

## 0. 一句话结论

权威度**不是一个分数，是四层机制**；目前系统里存在**两份互不同步的权威度表**，这是接下来要先解决的问题。账号维度配置文件的方向是对的，但**不应该做成 RAG（向量检索），应该做成单一事实源的精确查表**。

---

## 1. 现状：权威度实际是四层，不是一个分数

很多人以为「信源权威分」就是一个数字。实际链路是四层，每层的输入、口径、失效方式都不同：

```
① 声明层        每个信源/账号一个 1-5 整数（人工维护）
   ↓            用途：去重选主 / 冲击力的"权威共振"子因子 / 处理队列优先级
② LLM 判分层     LLM 输出 score_authority ∈ [0,1]
   ↓            依据：prompt 里另一份硬编码的自然语言媒体名单 ⚠️
③ 折扣层        × 谣言0.7 × 真实性校验(0.5~1.0)，CNBC 覆盖则先抬底到 1.0
   ↓
④ 时间可信度层   与①②③正交的另一条轴：内容权威 ≠ 时间戳可信
```

**最终进排序公式的是 ③ 的产物**（`news_events.score_authority`），占七因子权重的 8%~16%（可配置）。

### ①声明层：`crawler/sources.py` 等

| authority | 信源（RSS/HTML/API） |
|---|---|
| **5** | CNBC×4频道、Bloomberg×3、WSJ-Markets、FT-Home、MarketWatch、NikkeiAsia、Reuters、CoinDesk、CoinDesk-Policy、TheBlock、吴说区块链、dxFeed(MT Newswires)、Benzinga |
| **4** | Forbes-Business、Bloomberg-Politics、SCMP×2、YahooFinance、Cointelegraph、Decrypt、Blockworks、TheDefiant、TechFlow深潮、ChainCatcher、PANews |
| **3** | KoreaHerald、Investing×2、CryptoBriefing、BeInCrypto、Bitcoin.com、AMBCrypto、CryptoSlate、U.Today、Protos、CoinJournal |
| **2** | NewsBTC |

X 账号 32 个，独立维护 `(handle, 权重, 类型)`：

| 权重 | 类型 | 账号 |
|---|---|---|
| 5 | security / regulator / onchain / media / kol / exchange | peckshield, SlowMist_Team, SECGov, lookonchain, WuBlockchain, bwenews, cz_binance, heyibinance, binance, binancezh |
| 4 | media / onchain / research / macro | wublockchain12, BlockBeatsAsia, PANewsCN, Tree_of_Alpha, WatcherGuru, OdailyChina, Foresight_News, CoinDesk, solidintel_x, spotonchain, EmberCN, glassnode, whale_alert, DefiLlama, ai_9684xtpa, MessariCrypto, CertiKAlert, KobeissiLetter, BinanceResearch |
| 3 | research / onchain / macro | santimentfeed, OnchainLens, unusual_whales |

搜索召回域名分级 52 个白名单（`crawler/web_search.py` 的 `_TIER_5/4/3`），未命中 `AUTHORITY_DEFAULT = 2`，另有 **10 个内容农场黑名单硬过滤**（coinpedia / cryptopolitan / coingape / bitcoinist 等，命中即整条丢弃，不是打低分）。

### ②LLM 判分层：`crawler/pipeline.py` 的 SYSTEM_PROMPT

```
score_authority: official announcement=0.9+,
  top media (crypto: CoinDesk/TheBlock/吴说/BlockBeats;
             mainstream: Reuters/Bloomberg/CNBC/WSJ/FT/Nikkei Asia/MarketWatch)=0.75-0.89,
  mid media (SCMP/Korea Herald/Cointelegraph-tier)=0.50-0.74,
  aggregator/search=0.30-0.49, anonymous≤0.30; rumors ×0.7
```

### ③折扣层：`crawler/scoring.py:compute_authority`

```python
A = LLM 的 score_authority
if CNBC 覆盖:  A = 1.0          # v3 新增，"上了 CNBC"本身就是编辑背书
if is_rumor:   A *= 0.7
A *= {VERIFIED:1.00, PROBABLE:0.95, UNVERIFIED:0.75, DISPUTED:0.50}[校验状态]
```
另外 v3 起，CNBC 覆盖的事件在七因子加权和之后额外 **+0.05**（封顶 1.0）。

### ④时间可信度层：`crawler/source_trust.py`

**这一层是一次线上事故的产物，必须单独理解**：一条 6/27 的旧闻以「A 档、日期 7/28」进库展示，差整整一个月。根因是财联社经 Google News 分发，聚合器给的 `published_at` 是**它重新分发的时间**；而防伪造日期的兜底闸依赖 LLM 从正文读真实日期，聚合器恰恰**不给正文**——防线在结构上失效。

> **结论：内容权威度和时间戳可信度是两个正交维度。** 财联社是正规财经媒体（内容权威），但经聚合器这一跳后我们拿到的时间戳不可信。把两者混为一谈正是那次事故的认知根源。
>
> 任何新的权威度配置，**必须有独立的 `time_trust` 字段**，否则会重造这个 bug。

---

## 2. ⚠️ 已发现的核心问题：两份表不同步

**①声明层的表和②LLM prompt 里的名单是两份完全独立的硬编码，没有任何同步机制。**

实测证据（近 5 天生产数据）：

| 信源 | 声明 authority | 事件数 | **最终 A 均值** | 平均总分 | S/A 档数 |
|---|---|---|---|---|---|
| CNBC-TopNews | 5 | 121 | **0.955** | 0.531 | 14 |
| Bloomberg-Economics | 5 | 78 | 0.790 | 0.568 | 13 |
| FT-Home | 5 | 55 | 0.759 | 0.510 | 8 |
| 吴说区块链 | 5 | 340 | 0.684 | 0.479 | 41 |
| dxFeed (MT Newswires) | 5 | 134 | 0.543 | 0.445 | 7 |
| **Benzinga** | **5** | **3408** | **0.401** ⚠️ | 0.337 | 76 |
| 金色财经 | 4 | 475 | 0.603 | 0.506 | 80 |
| YahooFinance | 4 | 1343 | **0.469** ⚠️ | 0.304 | 20 |
| CryptoBriefing | 3 | 995 | 0.500 | 0.440 | 97 |

**Benzinga 声明 5 分，实际拿到 0.401**——因为它**根本不在 prompt 的名单里**，LLM 按「aggregator/search = 0.30-0.49」给分。核查确认：Benzinga、金色财经、Followin、CryptoBriefing、YahooFinance 在 `pipeline.py`（含 prompt）里出现 **0 次**。这几个恰恰是产量最大的几个源（Benzinga 一家占近 5 天全库事件的约一半）。

CNBC 的 0.955 则是因为 v3 里做了硬覆盖（抬底到 1.0 再走校验折扣），**绕过了②层**——这说明我们已经在用打补丁的方式对抗这个不同步，而不是修它。

> **给算法同事的第一优先级：不要在这两份表之外再加第三份。** 账号维度配置文件必须做成**单一事实源**，同时驱动：去重选主、权威共振子因子、LLM prompt（动态注入）、处理队列优先级。

---

## 3. 对提案的确认与修正

### ✅ 同意：账号维度配置文件

「其实头部媒体就那么点。命中了加分，没命中就是一个基础分」——**完全正确**，而且这正是系统现在的做法（未命中 `AUTHORITY_DEFAULT = 2`）。两点补充：

- **默认分要偏低而非取中**。未知来源的先验应该是「不可信」，不是「中等」。现在取 2/5 是对的。
- **黑名单必须是硬过滤，不是低分**。内容农场给 1 分仍会在长尾里冒头；我们的做法是命中即整条丢弃，且丢弃发生在 LLM 之前（省钱）。

### ✅ 同意：不做「搜索查询鉴别权威度 skill」

Lawrence 已自行否掉（延迟不友好 + 长尾不值得细分）。**补一个更致命的理由**：这类在线判定是**不确定的**——同一个源两次跑可能给出不同分，会破坏
① A/B 对照实验（分数变化分不清来自策略还是来自抖动）
② 打分版本一致性（我们有 QA 断言逐行核对「存量分 == 当前公式(因子列)」，非确定性输入会让它永久红）。

### ❌ 修正一：不要做成 RAG

权威度查询的本质是 **精确键 → 值 的 O(1) 查表**（域名 / 账号 handle / 频道名），**不是语义检索**。上向量检索会引入四个纯负面效果：

| | RAG（向量检索） | 静态配置表（推荐） |
|---|---|---|
| 匹配语义 | 近似——「CNBC」可能召回「CNBC Indonesia」并套用同一档位 | 精确匹配，不匹配就是不匹配 |
| 延迟 | 每条事件一次检索 | 内存字典，~0 |
| 可复现 | 索引更新/模型换代→同一输入不同输出 | 完全确定 |
| 可审计 | 「为什么这条给了 4 分」要复现检索过程 | 一次 SELECT / 一行 diff |

如果「做成 RAG」的本意只是**「一份模型能读的、可热更新的配置文件」**，那方向没问题——但**不要用向量库实现，也不要叫它 RAG**，否则后来接手的人会照着 RAG 的方式去改。

**推荐形态**：DB 表（带版本号，可回滚）或 YAML/JSON（进 git，走 code review），服务启动加载进内存 + 支持热加载。

### ❌ 修正二：Benzinga 不是聚合站

群里说的「这个 benziga 是个聚合站」需要更正，这个定性会直接把设计带偏：

- **Benzinga 是出版方**：有自己的编辑部和署名记者（实测样本作者：shivdeep dhaliwal、radhika anilkumar nadig），24 小时产出 **1,436 条**，**91% 带完整正文**，覆盖 931 个不同 ticker。
- **Massive 才是聚合/转售平台**（我们买的是 Massive 的 API，它转售 Benzinga 的内容）。
- **实测时效**：7/29 美联储利率决议，Benzinga 发布 18:08:54 UTC，CNBC 头条 18:11:00 UTC——**Benzinga 快约 2 分钟**。

**为什么这个定性关键**：如果按「聚合站」建模，就会给它套上「时间戳不可信」的规则（第④层），但它的时间戳恰恰是**一手且更快**的。反过来，它的**编辑质量**确实不如 CNBC/Bloomberg（零售财经风格、「Why It's Moving」快讯居多），所以给 authority 5 但内容偏 C/D 档——数据也印证：3408 条里只有 76 条 S/A（2.2%），而 CNBC 是 121 条里 14 条（11.6%）。

> 正确的建模是：**Benzinga = 一手信源（time_trust=primary）+ 中高编辑权威（authority 4~5）+ 低 S/A 密度**。三个维度独立，不要用一个「是不是聚合站」的标签概括。

---

## 4. 落地建议（给算法同事）

### 4.1 单一配置表 schema

```sql
CREATE TABLE source_authority (
  entity_key    VARCHAR(128) NOT NULL,   -- 域名 / X handle / RSS频道名 / square账号id
  entity_type   ENUM('rss_channel','x_account','square_account',
                     'api_publisher','web_domain') NOT NULL,
  display_name  VARCHAR(128) NOT NULL,
  authority     TINYINT NOT NULL,        -- 1-5，内容编辑权威度
  time_trust    ENUM('primary','aggregator') NOT NULL,  -- 与 authority 正交，见 §1④
  status        ENUM('active','blocked') NOT NULL DEFAULT 'active', -- blocked=硬过滤
  category      VARCHAR(32) NULL,        -- media/exchange/onchain/security/regulator/macro
  note          VARCHAR(255) NULL,       -- 定级依据，必填理由
  version       INT NOT NULL,
  updated_at    DATETIME NOT NULL,
  PRIMARY KEY (entity_key, entity_type)
);
```

**必须带 `version` 和 `note`**：我们踩过「改了打分公式但没改版本号 → 全库 87% 的分是旧公式算的、而且完全看不出来」的坑。定级依据不写下来，三个月后没人敢改。

### 4.2 消费方（必须全部接同一张表）

| 消费点 | 现状 | 改造后 |
|---|---|---|
| 去重选主 | `sources.py` 声明分 | 查表 |
| 冲击力·权威共振（数 authority≥4 的独立机构） | `sources.py` 声明分 | 查表 |
| 处理队列优先级 | 硬编码白名单 `_AUTHORITATIVE_MACRO_SOURCES` | 查表（authority≥5 → P0） |
| **LLM `score_authority` 判分** | **prompt 里另一份硬编码名单** ⚠️ | **从表动态渲染注入 prompt** |
| 时间可信度硬闸 | `source_trust.py` 的 `AGGREGATOR_TYPES` | 查表的 `time_trust` |
| 内容农场过滤 | `web_search.py` 的 `_BLOCKED_DOMAINS` | 查表的 `status='blocked'` |

**动态注入 prompt 的注意点**：只注入 top N（按 authority 降序 + 近期产量降序），控制 token；改动名单会让 prompt hash 变化、预处理缓存全部失效，所以要**批量改、低频改**，不要一天调好几次。

### 4.3 命中/未命中策略

```
命中配置表 → 直接用配置的 authority（不让 LLM 覆盖，保证确定性）
未命中     → LLM 自由判断，但夹在 [0, 0.5]（未知来源不给高分）
status=blocked → LLM 之前整条丢弃（省钱 + 防污染）
```

### 4.4 验收红线（建议进 CI）

1. 配置表任一行改动 → `version` 必须 +1（否则拒绝写入）
2. 全库抽样：`score_authority` 与「配置表 + 折扣层」重算结果一致（我们有同类断言，抓到过真实回归）
3. 命中率监控：近 7 天事件中命中配置表的比例，跌破阈值告警（说明有新的大产量源没进表）
4. 两份表同步性断言：prompt 注入的名单 == 配置表 top N 的渲染结果

---

## 5. 需要 Lawrence / 产品侧拍板的开放问题

1. **Benzinga 的 authority 到底给几分**？今天从 3 → 4 → 5 调过两次（Lawrence 定的 5，理由是「本来我们就是要美股为主」）。但它 S/A 密度只有 2.2%、平均总分 0.337 是所有 5 分源里最低的。**给 5 分会让 3408 条零售财经快讯整体上浮**——这是想要的吗，还是应该 authority=4 + 单独提高美股市场倍率？
2. **X 账号和 Square 媒体号要不要和 RSS 用同一个 1-5 标尺**？一个 5 分的 X KOL（cz_binance）和一个 5 分的 CNBC，在「权威共振」子因子里现在是等价的——合理吗？
3. **金色财经/CryptoBriefing 这类高产中档源**（各 475/995 条，S/A 密度反而高于 CNBC）**是否值得单独一档**？

---

## 附：相关代码位置速查

| 内容 | 文件 |
|---|---|
| RSS/HTML 信源声明表、X KOL 表 | `crawler/sources.py` |
| 搜索域名分级 + 内容农场黑名单 | `crawler/web_search.py` |
| LLM 判分 prompt（含媒体名单） | `crawler/pipeline.py` SYSTEM_PROMPT |
| 折扣层 + CNBC 覆盖规则 | `crawler/scoring.py:compute_authority` / `cnbc_covered` |
| 真实性校验乘数 | `crawler/verification.py:authority_multiplier` |
| 时间可信度硬闸（第④层） | `crawler/source_trust.py` |
| 权威共振子因子 | `crawler/scoring.py:_resonance_score` |
| 排序参数配置化 + 版本管理 | `api/strategy_config.py`、`config/migrations/016,017` |
