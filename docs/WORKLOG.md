# B9 项目工作台账

> 记录 Lawrence 提出的全部需求及其跟进状态。最后更新：2026-07-26（晚间批次收尾）
> 图例：✅ 已完成并验证 ｜ 🔄 进行中 ｜ ⏸️ 阻塞（等确认/等额度）

配合阅读：`docs/PROJECT_PLAN.md`（做什么/为什么）、`docs/REQUIREMENTS_LOG.md`
（原始需求原文）、`docs/OPEN_QUESTIONS.md`（**待你 review 的决策点，务必看一眼**）。

---

## 一、晚间批次五项需求（睡前一次性提的）

| # | 需求 | 状态 |
|---|---|---|
| 1 | 保障稳定全面的召回源，去重入库落表 | ✅ 覆盖率交叉验证（真实数字 29.9%，见 §4 F5）+ 12个新RSS源接入 + 抓取/处理频率解耦（`crawler/staging.py`，免费源2h/次高频存档，LLM处理仍12h/次） |
| 2 | 内容理解打标签：实体/情绪/币种/板块相关度 + 市值标签 | ✅ `crawler/market_cap.py`（市值+BTC倍数+档位，含ticker消歧五道闸）+ `sector_tags`（真相关才打，强制锚点）/`entities`/`sentiment`/`impact_horizon`。实测过度打标 14→6 板块（-57%），成本 +30%（见 OPEN_QUESTIONS #1） |
| 3 | 重要性打分排序 | ✅ 已实现，原始方案文档（用户提供）确认打分公式一致 |
| 4 | 生产化 API | ✅ 已上线；已知限制见 OPEN_QUESTIONS #2（无HTTPS/单token） |
| 5 | 前端网站（5 tab，浅色设计） | 🔄 4/5 完成：生成流程+数据展示+API接入（`web/index.html`）、策略实验室（`web/lab.html`）已部署验证；评测工具（`web/eval.html`）后端已交付注册，前端页面待完成 |

## 二、当晚追加的四项需求

| # | 需求 | 状态 |
|---|---|---|
| 6 | X API 成本控制（"钱烧得很快"） | ✅ 查明真实成本大头是下游LLM结构化非X本身；`x_search.py` 加 `MAX_ITEMS_PER_RUN=200` 硬顶 |
| 7 | 抓取频率与召回稳定性的折中方案 | ✅ 免费源改高频抓取存档（2h/次）+ LLM低频批量处理（12h/次不变），X维持原节奏不提速 |
| 8 | 前端补充完善 + 加导航栏 | ⚠️→✅ 当时做成**顶部横排 tab**，用户要的是**侧边导航栏**，2026-07-26 下午返工重做（见文末复盘） |
| 9 | 所有X来源要有具体字段 + 数据展示要有X原贴信息 | ✅ `attach_x_posts()` 内嵌完整原贴（正文/互动量/链接）进事件响应，前端详情展开渲染 |

---

## 三、已完成清单（含关键实测证据，按完成顺序）

| # | 事项 | 证据 |
|---|---|---|
| 连接GitHub+建start文件 | | commit `f911506` |
| 装Claude Code CLI | | v2.1.220 |
| 连接VM | | SSH密钥+别名`manus-vm`+ControlMaster连接复用 |
| 深读背景+MySQL导出Excel | | 841事件×8sheet |
| 事件ID稳定指纹 | | `sha256(subject\|action\|date)`，`crawler/dedup.py` |
| 聚合层真embedding | | `text-embedding-3-small`256维替换TF-IDF |
| 跨轮归并 | | 实测349事件中267条并入既有行 |
| H因子接入社交互动 | | `H=0.6×log(互动)+0.4×min(信源/8,1)` |
| 修日期异常 | | 7天窗口，单轮拦79条陈年内容 |
| 代码结构优化 | | pipeline.py拆成dedup/scoring/storage/pipeline |
| 存量416行重复清理 | | 确认后执行，944→508行 |
| OpenAI用量监控 | | `crawler/usage_tracker.py`+`scripts/usage_monitor.py`（曾有Lock死锁bug已修） |
| 补14个已验证RSS源 | | 实测12个新源部署，226条/轮增量 |
| 数据源采购调研 | | BWEnews websocket免费实测通过；多个"个人使用"套餐陷阱 |
| X搜索质量调优 | | 账号层面限流（单账号≤3条/轮）+ 付费推广号bio识别 |
| 非技术版API文档 | | 支持`?token=`URL参数鉴权 |
| 召回覆盖率交叉验证 | | 见 §4 F5 |
| 真实性校验 | | `crawler/verification.py`，508条实测VERIFIED86/PROBABLE240/UNVERIFIED182，人工误判率3.3% |
| 数据抓取Skill文档 | | `docs/skill-data-source-strategy.md` |
| web_search扩query | | 协议治理+桥被盗类query |
| Triple-A事件排查 | | 确认是RSS滚屏丢失非bug，催生了staging.py解耦方案 |
| 内容理解+市值标签 | | 见上表#2 |
| 频率解耦 | | 见上表#7 |
| X原贴嵌入 | | 见上表#9 |
| 评测工具Tab | | 后端`api/eval_tools.py`已注册，前端待交付 |
| 策略实验室Tab | | `web/lab.html`+`api/lab_tools.py`，实测3组权重配置+2组A/B对比 |
| sources/source_names同步bug | | 跨轮归并时补齐并集，`crawler/storage.py` |
| x_raw_posts关联回填 | | 121/151历史数据已关联 |
| server.py部署import修复 | | sys.path/blueprint注册问题，见memory `flask-blueprint-syspath-gotcha` |

---

## 四、关键发现（F1-F5）

### F1：欠召的根因不是信源不够，是信号类型缺失（早期粗测）
对照6个平台粗测91.9%覆盖率（**后被F5推翻，见下**），但行情异动类事件只占3.9%、
宏观美股类只占4.7%——因为没有媒体会把"BTC跌5%"写成新闻，这类信号必须从行情
API直接生成事件。

### F2：去重实现与文档严重不符，实测48.7%冗余
944行里416行重复。三个叠加根因：ID用LLM改写标题做hash、聚合用TF-IDF冒充
embedding、只在单轮内去重不管跨轮。已全部修复，清理到508行。

### F3：文档写的语义阈值0.65是错的，实测应取0.82
在855条真实事件、28万配对上分档标定：cosine 0.65会把不同事件误判成同一事件。
13组人工标注配对确认0.82是干净分界点。已更新skill文档。

### F4：X API有大量闲置额度
search/recent端点450请求/15分钟，此前完全没用过。已用`x_search.py`接入，
成本敏感点是下游LLM结构化不是X本身，已加200条/轮硬顶。

### F5：严谨复测推翻F1的91.9%——真实覆盖率是29.9%（重要，方法论教训）
用更大样本（386条真实事件）+ 公平时间窗口 + LLM逐条判定（而非纯关键词/纯
cosine）重测：**事件级覆盖率29.9%**（85/284）。原91.9%高估两个原因：关键词
重合会把同主题不同事件算成命中；测试时库里还有大量重复行让匹配更容易命中。

**但分层看更有价值**：3家以上媒体报道的事件100%没漏，问题是"长尾密度不够"
不是"漏大事"。归因：77.4%是信源没接（已用12个新RSS源部分缓解），0%是过滤器
误杀（不用动新鲜度过滤和粗去重）。方法论详见`docs/skill-data-source-strategy.md`
§5，报告全文见`docs/coverage-test-report-20260726.md`。

---

## 五、踩过的坑（避免重蹈，编号沿用之前）

| 编号 | 问题 | 根因与处理 |
|---|---|---|
| P1 | 并行4个agent同时SSH，22端口refused 25分钟 | sshd的MaxStartups被打满，非封IP非OOM。已配ControlMaster连接复用 |
| P2 | API曾500约30分钟 | schema加`embedding`BLOB列，旧`SELECT *`无法序列化。教训：改schema必须同时重启服务 |
| P3 | 币安API在VM上451 | 美国IP地域封锁。现货用`data-api.binance.vision`，合约用OKX为主Hyperliquid兜底 |
| P4 | Google News RSS返回陈年旧闻 | 默认按相关性排序，必须加`when:`时间算子 |
| P5 | 降低运行频率会连带掉召回 | RSS取数上限/X回看窗口都要跟着频率调整 |
| P6 | RSS高频源12小时间隔会滚屏丢失 | Triple-A被盗事件实锤：服务端窗口固定约30-50条。解法是频率解耦（staging.py），不是继续加大取数上限 |
| P7 | UsageTracker.snapshot()自死锁 | 用了不可重入的Lock，持锁期间调用同样要加锁的方法。改RLock修复。**修复前所有pipeline_runs的token数据都是0，是假象** |
| P8 | server.py多agent交付的blueprint模块ModuleNotFoundError | `python3 api/server.py`直接跑时sys.path不含项目根。加`sys.path.insert`修复，已存入跨项目memory |
| P9 | sources与source_names长期不同步 | 跨轮归并时source_names走并集但sources直接覆盖，59/508行不一致。已修复 |

---

## 六、未开发/待办能力

- **Sector Insight v5.1 相关性算法仍是0行代码**——策略实验室里的"相关性"因子
  是简化版二元判断（板块命中=1.0），已在页面标注，见OPEN_QUESTIONS #4
- **评测工具前端页面**（`web/eval.html`）待交付
- **X API定向查询重构**——用户已确认"还好，后面看用量再调节"，不紧急
- **API的HTTPS/分级权限**——生产化程度是否够，需用户判断实际暴露面，见OPEN_QUESTIONS #2
- **前端三个页面共享CSS抽取**——等eval.html定稿后统一做

---

# 复盘：漏做需求事故（2026-07-26 下午）

> Lawrence 发现「侧边导航栏」没做，要求 1）补做 2）复盘原因，避免再犯。
> 查证后发现实际上是**两起**，第二起比第一起严重得多。

## 事故一：导航栏做成了顶部横排，不是侧边栏

**原话**（`REQUIREMENTS_LOG.md` 有留痕）："记得加一个导航栏。"

**发生了什么**：需求被记录了，也在本文档标了 ✅（"5-tab导航栏已实现"），
但实现成的是**顶部横排 tab**。Lawrence 心里想的是**左侧侧边栏**。

**归因**：原话只说"导航栏"，没说"侧边"——单看文字，顶部 tab 条也算导航栏，
不能算完全曲解。但真正的问题是**我当时正好在做 tab 切换，就顺手把这个需求
折叠进了"我本来就在做的事"里，然后直接标了完成，全程没让 Lawrence 看过一眼
成品**。需求本身是模糊的，而我用"对我最省事的那个解释"消解了模糊性，且没有
把这个解释暴露出来验证。

## 事故二（更严重）：策略实验室子tab需求整条丢失

**原话**："策略实验室 也是改成tab的模式 不要一拉到底" + 追问"子tab"

**发生了什么**：这条需求
- ❌ 没有记进 `REQUIREMENTS_LOG.md`
- ❌ 没有落进 TODO 表
- ❌ 没有做（`lab.html` 里两个工具一直是竖着堆叠的）
- ❌ 更糟的是：2026-07-26 我自己写 `docs/design-brief-for-visual-polish.md`
  时，还把 lab.html 描述成"子 tab：单版本权重调节 / 两版本权重对比"，
  **把没做的事描述成了已完成状态**，等于给未来的自己和设计工具都埋了错误信息

**归因（这条是真正要改的）**：Lawrence 早就定过工作原则——"所有任务都要落
todo表""所有原始prompt要按原样留痕"。我对**大段的、一次给五六项的批量需求**
严格执行了这个纪律，但对**穿插在对话里的一两句短需求**没有执行：短句被我当成
了"对话上下文"而不是"需求条目"，处理完当前手头的事就过去了。这条需求恰好出现
在我正忙着回答 pipeline 耗时/成本问题的时候，注意力在别处，就彻底蒸发了。

## 改进措施（已落实，不只是写在这里）

1. **短需求和长需求一视同仁**：不管是一大段还是一句话，只要是"要我做某件事"
   的表述，先落 TODO 条目 + 记进 `REQUIREMENTS_LOG.md`，再开始做。判断标准不
   是"这句话有多长/多正式"，而是"这是不是在要求一个结果"。
2. **UI 类需求不靠文字自证完成**：涉及视觉/交互形态的需求（导航、布局、tab
   形态），完成后必须给出截图或明确描述形态（"做成了顶部横排"而不是含糊的
   "导航栏已实现"），让形态差异当场暴露，而不是等几天后被发现。
3. **模糊需求要么问、要么把解释写出来**：像"加个导航栏"这种一词多义的要求，
   要么直接问一句，要么在交付说明里写清"我理解成 X 了"，不能默默选一个最省
   事的解释就标完成。
4. **写文档时不许把"计划中"写成"已完成"**：`design-brief` 那次错误的根因是
   我照着"应该是什么样"而不是"实际是什么样"写文档。涉及现状描述的文档，写之
   前先看代码/页面确认。

## 本次返工实际做了什么

- `web/index.html`、`web/lab.html` 双页改为**左侧固定侧边导航栏**：
  一级导航 6 项 + 二级子导航（评测工具 3 个子工具 / 策略实验室 2 个子tab），
  当前项金色高亮 + 左侧金条，子项圆点标记，双向联动
- 窄屏（≤1080px）自动降级为汉堡抽屉 + 遮罩，Esc 可关，点导航项自动收起
- `web/lab.html` 的两个工具**从竖排堆叠改成同页子 tab**（补上事故二的需求），
  支持 `/lab#sub2` 直达第二个子 tab
- 实现方式刻意保守：侧边栏里的按钮**沿用原来那批 `.tab[role=tab]` 的
  id/aria 属性**，所以 `showTab()`、键盘 1-5 快捷键、hash 路由一行没改就继续工作
- 顺手修掉 lab.html 导航里指向已删除页面的 `/eval` 死链，改为 `/#tab4`
- 验证：HTML 结构解析零错误；VM 部署后双页 200；浏览器实测一级/二级导航切换、
  子tab联动、控制台无报错

---

# 七、Fable max 批次（2026-07-26 下午）

| # | 事项 | 状态与证据 |
|---|---|---|
| 38 | enrich bridge：本地 Claude 预处理替代 OpenAI 计费 | ✅ 全链路真实验证：真实条目提交缓存→pipeline 命中→0 次 OpenAI 调用→normalize/指纹/元数据全部正确。三层兜底（miss→OpenAI / 缓存读取异常→全miss / 单条不合法→该条miss）。launchd 每 30min 调度已装好。**遗留一项待 Lawrence 解锁：Mac 上 `claude` CLI 的钥匙串授权（一条命令，见 memory）** |
| 39 | 全量代码 review（5 区域并行 + 对抗验证） | ✅ 15 agent / 48 条发现 / 10 条对抗验证（9实1虚）。当场修复 8 项（含 4 个 HIGH：staging 先标记后处理丢数据、LLM 全军覆没静默成功、行情信号 URL 被存档层永久吞、lab A 因子二次折扣），全部部署验证。其余带判断记入 OPEN_QUESTIONS §7 |
| 40 | 项目复盘 playbook | ✅ `docs/PROJECT_RETROSPECTIVE.md` + 长期 memory（用户指定后续所有项目参考） |
| 41 | push GitHub | ✅ 本批次全部材料已提交推送 |

enrich bridge 架构一句话：Mac（工作机，不保证在线）闲时经 `/api/enrich/pending`
拉 staging 待处理条目，本地 `claude -p` 按 VM 下发的同一 prompt（prompt_hash
闸门保证口径）结构化，回传 `llm_enrich_cache`；pipeline Step 4 命中即免费，
未命中走 OpenAI 原路径。Mac 离线的唯一后果是"这轮没省到钱"。

# 八、设计改版上线后的收尾（2026-07-26 深夜 ～ 2026-07-27）

设计改版（顶部分组 tab + Organic 设计系统）落地后，Lawrence 逐项验收，
本批次是验收过程中冒出来的修复与新需求，按时间顺序：

| # | 事项 | 状态与证据 |
|---|---|---|
| 44 | 观测时间筛选改单选（按生产轮次） | ✅ 新增 `GET /api/run-nodes`：按 08:00/20:00 两个调度节点分桶；`/api/news` 加 `run_at` 半开区间参数 `[run_at, run_at+12h)`。QA 新增 4 条断言，其中「各轮 total 相加==全量」是分桶正确性的硬校验 |
| 45 | Dev Bill 去掉 ×2、改回实测原始值 | ✅ 单轮 $14.17/天 $28.33/月 $850；同时纠正 Claude 一项按实际 Max 顶配 $250/月计（此前错按 $20/月订阅算，差一个量级） |
| 46 | 全站隐私处理（demo 站不可反推雇主/个人） | ✅ 标题/meta/页脚去人名公司名 + `noindex`；页面自身 token 换成不含人名的 `b9-web-*`；仓库卡片一度改成纯展示（见 #52 又改回） |
| 47 | App 模拟器去掉 Sector Insight 页签、流程轴并入耗时 | ✅ 板块过滤已在上方筛选器生效，两套口径并存会打架，故只留 Macro；耗时改由 `/api/runs.stage_timings` 实时算，不再写死 |
| 48 | **故障排查**：换 web token 后 lab/eval/history/sector/enrich 五个 blueprint 全 401 | ✅ 根因：这五个 blueprint 各自复制一份鉴权表（技术债，README 有记），新 token 只加进了 `server.py`。五处补齐 |
| 49 | **故障排查**：7/26 20:00 那轮在前端"消失" | ✅ 根因：那轮真的跑成功了（20:13 写完 418 条），但 `time_get_data` 仍用 `datetime.now(timezone.utc)` 盖戳，且 mysqld 到 20:38 才重启、之前 `CURRENT_TIMESTAMP` 也是 UTC——"改成 UTC+8"上一轮只切了系统/cron/MySQL，代码写入口径漏了。新增 `crawler/timeutil.py` 做唯一时间基准，全仓 30 处 `now()` 改点；migration 011 按边界（mysqld 重启时刻）平移存量数据，执行前已 mysqldump 备份 |
| 50 | 补齐设计稿差异 1–4（用户明确"1-4要，5-8不要管"） | ✅ (1) 流程图 26 处硬编码色映射到 token；(2) 流程轴改深色步骤胶囊+删节点级耗时小字；(3) tab01 新增"最近调度监控横条"；(4) 01/02/03/06 四个长 tab 补吸顶锚点条（IntersectionObserver 高亮）。过程中我自己引入一个 bug（`initAnchorBars` 误用了另一脚本块的 `$all`，把 `showTab` 整个打断），浏览器实测揪出并修复 |
| 51 | 新增「信源统计」子 tab | ✅ 新端点 `/api/source-catalog`：`sources.py` 注册表 + `verification.resolve_source` 真实校验口径（不另起判断）+ 库内产出量三方合一，380 个信源（注册64+长尾316），5 维筛选。刻意保留 35 个零产出注册源——"配了没用上"本身是信号 |
| 52 | 布局回归：指标卡被空锚点挤到第二行、宽屏留白过大 | ✅ 根因是 #50 加锚点条时误往 `#statRow`（4列grid）插了个空 `<span>` 占位；`.wrap` 限宽 1320 在 1900 屏上两侧空 285px 没跟着"内容全宽"放开。改锚点直接指向容器本身；`.wrap` 分两档放宽到 1500/1680 |
| 53 | 首屏改版：标题改单行 + 新增"业务价值"三条 + 联系人具名 + GitHub 链接恢复 | ✅ 标题单行靠独立 class 去掉 `max-width:19ch` 限制，字号按 1280/1900 两档实测留白定；业务价值三条圆角栏（对比 baseline 评估召回率/首发率、补召链路生产 API、运营监控）；`the maintainer`→`lawrence zhu`；仓库卡片改回可点链接（#46 一度改的纯展示撤回） |

本批次没有新增"漏做需求"事故——但 #48/#49/#50(引入的bug)/#52 都是**改动引入的回归**，
共同点：动一处共享状态（鉴权表、时间戳写入口径、grid 结构、全局辅助函数名）时，
没有先扫一遍"还有谁依赖这个"。这条已写进 `PROJECT_RETROSPECTIVE.md` 的 checklist。

| 54 | 真实评测：我方事件库 vs 线上 Binance App「Macro Insight」实际展示内容 | ✅ 用户提供 20 张线上信息流截图，人工转录 82 条卡片（2026-07-25~27），与我方同期 1023 条事件用 `text-embedding-3-small`（256维，同去重管线口径）做相似度匹配，Claude 逐条人工复核（未再调用 OpenAI 做判断/成文）。核心结论：成熟窗口（07-25+07-26）真实新闻召回率 54.4%；同期 S/A/B 级事件 152 条中 133 条（87.5%）未出现在线上展示内容里，含 2 条 S 级、6 条构成完整立法追踪线的 CLARITY 法案 A 级事件、4 起超 $4400 万的安全事故。副产品发现：按信源拆分召回率显示 Bitcoinworld（未接入，占线上流 45.6%）与 BeInCrypto（已接入但召回仅 41.2%，低于 Cointelegraph 的 78.6%，值得跟进）两处信源缺口；另发现我方库内 2 处疑似跨轮归并遗漏的近重复事件（"Lazarus $138M Bybit 洗钱"3行、"KB Kookmin/JPMorgan Kinexys"2行）。产出 PDF 报告 `docs/eval_reports/B9_vs_线上Macro_Insight_评测报告_20260727.pdf` |
| 55 | 转发折叠：多个 KOL 单纯转发同一原文不再算独立信源 | ✅ Drew Zhu（Product）在评测追问时提出这个问题，Lawrence 明确"不算，只算非转载内容"。根因：`verification.analyze_sources()` 按账号名分机构（`resolve_source` 对陌生 KOL 返回 `x:{username}`），N 个不同账号转发/复制同一段原文时账号名互不相同，天然绕开了"按机构去重"，转发量能冒充信源广度、进而推高 `independent_source_count` 并可能把事件误判到 VERIFIED。修法：`verify_events()` 新增 `_load_tweet_texts()` 批量取本轮涉及推文的 `tweet_body`（复用 `attach_social_metrics` 的查询模式，零新增迁移——`tweet_body` 全文本来就存着），`analyze_sources()` 用 `x_search._normalized_key()`（复用其单次抓取内已有的"识别跨账号复制粘贴"逻辑）对同一事件内的 X 来源按正文聚类，每簇只保留权重最高的机构计入独立信源，其余记入新增的 `n_reposts_folded` 并打 `REPOST_FOLDED` flag。不传 `tweet_text_by_id` 时行为不变（老调用方零改动）。验证：4 个合成场景（纯转发折叠为1/全原创不折叠/不传参数保持老行为/混合场景选中最高权重机构）全部通过；扫描生产库确认转发现象真实存在（x_raw_posts 里有 7 条不同账号发布同一段正文的真实簇），仅因当前"单事件内≥2条X来源"的事件较少（67/1851）暂未在 news_events 里遇到会触发折叠的案例；用 5 条真实事件跑通完整 `verify_events()` 调用链无异常；QA 门禁 70/70 |
| 56 | 产品 demo 通过，产出正式研发交接 PRD | ✅ 两份文档：`docs/prd/PRD-01-数据抓取.md`（面向数据开发：8 类信源清单+各渠道原始字段规范+X 转发去重与 `is_repost`/`repost_type` 标记要求+URL 去重规则）、`docs/prd/PRD-02-聚类与理解.md`（不含排序：LLM 结构化字段表+语义聚类阈值 0.82 的标定提醒+跨轮归并"事件id不变、标签值持续变化、增量表逻辑记录快照时间"的更新规则详解，直接对应 Drew Zhu 评审时提的"同一事件持续 update 应归到一个事件热度里"+转发折叠的验收标准）。两份都基于现有原型代码的真实字段/常量核对写成（sources.py 信源计数、pipeline.py LLM schema、dedup.py 阈值、storage.py 的 ON DUPLICATE KEY UPDATE 更新语义），不是凭空写的模板 |
| 62 | 当天二次修正：去掉加密限制 + 情绪门槛改用 tier + 提频到每小时 + SCMP 频道纠错 | ✅ 见下方专节 |
| 61 | 美股/港股/日股/韩股/宏观新闻扩召回 + 情绪排序 + dxFeed 机构新闻源接入 | ✅ 见下方专节 |
| 60 | 本地 enrich worker 改用 LiteLLM 网关替代 claude CLI（Mac 挂 VPN 能连通） | ✅ 见下方专节 |
| 59 | 尝试切换生产环境到公司 LiteLLM 网关（阻塞：VM 连不通内网） | ⏸️ 见下方专节 |
| 58 | 评测工具完整化：Agent 管理页 + 校准闭环 + 评测历史 + 三项主动补的能力 | ✅ 见下方专节 |
| 57 | demo演示完毕，暂停 X API + 运行频率从每天2轮降为每2天1轮 | ✅ 新增 `X_FETCH_ENABLED` 环境变量开关（`crawler/main.py`，默认 `true`；VM `config/.env` 已设为 `false`），`fetch_x_sources()` 为 false 时直接跳过 KOL 时间线 + 全网搜索两条腿，返回空列表并记日志说明是"主动暂停"而非故障；`config/env.example` 补充说明注释。crontab 主流水线行从 `0 8,20 * * *` 改为 `0 8 */2 * *`（已备份老 crontab），免费源高频存档与周备份两行不变。验证：VM 上直接跑通 enabled=true/false 两种行为；策略产品工作台（04/05 tab 按需调用 OpenAI，不经过这个开关）逐项确认不受影响（systemctl active、首页 200、鉴权可达）；QA 门禁 70/70。**顺带修复**（未被要求但主动核查全站的连带影响）：`README.md` 调度表 + 首屏 kicker + 6 处散落在页面各处的"每天2轮/08:00·20:00"旧文案（流程图 SVG、调度横条、部署信息、pipeline 说明段、tab07 简介、API 文档字符串）；Dev Bill 成本表按新分摊基数重算（单轮 $14.17→$28.56、单日 $28.33→$14.28、单月 $850→$428.50，X 一项归零）。**故障排查**：部署后浏览器实测发现 `nextRunLabel()` 显示"下轮 7-29 20:00"——根因是最近一次记录的运行发生在 20:07（老排期切换前最后一次遗留记录），"+2天"计算把这个已不存在的 20:00 时段带进了新排期的展示；且中间一版修复仍经过 JS `Date` 对象的时区解析（`new Date(str+"+08:00")` 再 `.getUTCDate()`），在 UTC+8 凌晨时段（UTC 与 UTC+8 日期不同）有隐患。最终版改为直接从已是 UTC+8 挂钟字符串的 `run_at` 用正则摘出年月日数字做纯 `Date.UTC` 整数运算+2天，小时数在输出里硬编码为 `"08:00"`，不再从入参继承；`node -e` 单测 3 种场景（正常/凌晨边界/null）+ 浏览器实测确认显示"下轮 7-29 08:00"后部署 |

# 九、评测工具完整化（2026-07-28）—— WORKLOG #58 详节

Lawrence：「目标是搭建一个完整的评测工具」。原来的 LLM 评测室只是"一次性调用 +
看完就没了"：人设是 `api/eval_tools.py` 里的一段硬编码常量，改一次要改代码 + 重启
服务；评测结果除非手动点"保存"否则不落库；用户觉得某个 Agent 判得不对，这个判断
没有任何地方可以沉淀。本次把它补成一个有反馈回路的系统。

## 做了什么

**数据层**（`config/migrations/012_persona_management.sql` + `api/persona_store.py`）
五张表：`eval_personas`（人设主表，五要素分列存）、`eval_persona_versions`（每次
改动的完整快照）、`persona_eval_runs` / `persona_eval_results`（评测留档）、
`persona_calibrations`（校准意见）。`persona_store.py` 刻意做成**无 Flask 依赖**的
共享数据层，因为 `eval_tools.py`（跑评测）和 `persona_tools.py`（管理接口）两个
blueprint 都要用它——让两个 blueprint 互相 import 会破坏"每个 blueprint 自包含"
的约定，共享一个纯数据模块则不会。

**人设从 5 个精简到 3 个**，按资产规模分层（10 万 / 50 万 / 400 万美金）：林薇
（外企市场部经理，币圈小白）、陈立（大厂后端工程师，稳健投资者）、老周（全职
交易员，激进投资者）。分层的用意是这三档对应完全不同的信息需求——10 万档关心
"我该不该慌"，50 万档关心"这事能不能验证"，400 万档关心"能不能交易"；同一条新闻
在三档之间的评分差异本身就是这条新闻**受众宽度**的度量。故事写得长是有意的：
LLM 扮演的可信度几乎完全取决于背景细节密度，只写"谨慎的新手"模型就输出一个通用
谨慎新手，写清楚"2024 年 11 月在 9 万 2 买的、套了五个月"模型才会在评测里真的
提起这段。三人五要素合计 1304 / 1403 / 1358 字。

**人设为什么拆成五个字段而不是一整段 prompt**：校准闭环需要明确的作用靶点。用户说
"她对交易所安全事故应该更敏感"，归纳时只改 `preferences` 一列，`story` 和 `memory`
原样不动。如果人设是一整段 prompt，每次让模型重写都会顺手改掉不该动的地方，几轮
下来人设必然漂移——这是 LLM 改写文本的固有行为，靠 prompt 约束不住，只能靠把可改
区域切小。同理，`apply-calibration` 只允许改 `personality`/`preferences` 两列：
`story`（故事）和 `memory`（记忆）是这个人的既成事实，不该因为"他这次判得不准"
就被改写。

**校准闭环做成两段式**（本次最关键的设计取舍）：
1. **提交即生效，零成本**——comment 立刻追加进 `calib_memory`，下一次评测的
   system prompt 自动带上。用户点完就能看到 Agent 变了，不用等、不花钱。
2. **攒够再归纳，一次 LLM 调用**——点「归纳进人格」时把所有未归纳的校准一起喂给
   模型，改写人格/偏好两列，产出新版本。
   刻意不做成"每提交一条就调一次 LLM 重写人设"：那样既贵，又会因为反复全量重写
   导致人设漂移。`calib_memory` 有 3000 字上限，超了从最老的丢——它每次评测都进
   prompt，无上限增长会让成本线性上升，而几十条之后模型对靠前内容的注意力本来
   就衰减，留着只花钱不起作用。

**主动补的三项能力**（用户原话"如果发现有需要加的feature也可以单独和我说。加上"）：
- **批量评测** `POST /api/tools/persona-eval-batch`：N 条新闻 × M Agent 矩阵，
  上限 30 条且必须显式带 `confirm_cost=true`（不给"手滑点一下烧掉几十刀"的机会）。
  串行跑新闻、每条内部并发跑 Agent——二维全并发 30×3=90 个请求会直接撞速率限制，
  拿回一堆 429 比慢一点糟糕得多。
- **人工标注基准 + MAE**：用户填的"实际应该打几分"同时写进 `human_score`，
  `|score - human_score|` 的均值就是这个 Agent 当前的偏差。按人设版本切开看
  （`/api/personas/<id>` 的 `version_comparison`），就知道校准到底有没有让它更准——
  **校准闭环必须有目标函数，否则是玄学**。
- **排序外部效度** `GET /api/eval-analysis/correlation`：Agent 主观评分与生产
  `importance_score` 的 Pearson r。r 高说明排序贴合该人群感受；某个 Agent 的 r
  明显偏低说明当前排序对这类用户不适配——这本身就是可汇报的产品结论。样本 < 5
  时**不给系数**、返回 null 并说明原因，不返回一个基于 3 个点算出来的唬人的 0.97。

**刻意的取舍**：
- 评测结果表冗余存 `persona_version`。没有它，人设改过之后历史结果会被误当成新
  人设的表现，"校准前 vs 校准后"永远说不清。
- 删除 Agent 时**保留**它的历史评测记录（历史是既成事实，不该因为后来删了个
  Agent 就凭空消失），前端遇到查不到的 id 显示为「已删除的 Agent」。
- 播种判据是"整张表为空"而不是逐个 id 检查：后者会导致用户删掉某个内置 Agent
  之后，下次服务重启又给他种回来——那不是删除该有的行为。
- `load_personas()` 在数据库读不到时回落到代码内置人设，但**必须**在响应里标注
  `persona_source="builtin_fallback"`，前端据此显示红色警告。用户刚改完人设、
  实际跑的却是内置默认值，这种静默降级必须让他看得见。

## 踩到的坑（三个都是浏览器实测才暴露的）

1. **子 tab 点了没反应、控制台不报错**。新子 tab 用 `data-onshow` 声明懒加载钩子，
   我写成 `window[hook]()` 去找函数——但整个 Tab04 脚本包在 IIFE 里（原 eval.html
   合并进来时刻意这么做的，避免变量名污染），函数从来不在 window 上。改成块内的
   `SUBTAB_HOOKS` 注册表。
2. **所有新接口稳定 401**。`toolUrl()` 无条件拼 `'?token='`，path 自带 query 时
   产出 `/api/personas?with_stats=1?token=xxx`，服务端把 `1?token=xxx` 当成
   with_stats 的值，token 参数根本不存在。**这是主脚本 `liveUrl()` 踩过的同一个坑
   的第二次复发**，这次修在 `toolUrl()` 内部按分隔符判断，不是在调用点绕开。
3. **回滚"成功了但没回全"**——新增的 QA 用例抓到的真 bug，不是用例写错。
   `create_persona` 存 v1 快照时存的是请求体那个 dict，请求里没写的字段（比如没填
   mood）在 dict 里根本不存在；而 rollback 是按"快照里有哪些键"还原的，于是后来
   才填的 mood 在回滚后残留。修法两处：建 persona 时从库里回读**完整一行**再存
   快照；rollback 对文本类字段缺键时显式清空（缺键的语义是"那一版没有这段内容"）。

## 验证

- VM 上真实跑通完整闭环：3 Agent 并发评测（$0.0217）→ 自动落库 → 提交校准（立刻
  进 prompt，实测 `preview-prompt` 含【历史校准记录】）→ 归纳进人格（$0.0141，
  产出 v2）→ 评测历史 → 版本对比 → 相关性分析 → CSV 导出 → 无 token 全部 401
- CRUD/上传/回滚：新建→更新→Markdown 分段导入（正确解析出人格/故事/偏好三段）→
  JSON 导入→版本历史→回滚→停用→删除，逐项通过
- 批量评测：VM 侧 2 条 ×3 Agent 通过；浏览器侧真跑 3 条 ×3 Agent（$0.06）矩阵
  正确渲染，成本刹车两条（缺 confirm_cost / 超 30 条）均正确拒绝
- 浏览器逐项实测 6 个子 tab：Persona 管理（3 张卡片、五要素编辑器、版本时间线、
  评分分布、Prompt 预览 2088 字）、批量评测（成本提示随条数/Agent 数实时变化）、
  评测历史（展开逐条、人设版本标记 v2/v1/v1、3 个校准框全部 wired、按 Agent 过滤
  出版本对比表）、评测室（自动展示最近一次真实评测而非过期样例）
- **校准闭环被实测证明有效**：林薇 v1 均分 3（MAE 5）→ 提交一条"应该打 8 分"的
  校准 → v2 均分 6。版本对比表如实反映了这个变化
- QA 门禁新增第 7 组共 23 条用例（全部零成本），总计 **93/93 通过**
- 验证完把测试数据全部清空并重新播种：校准记录里是我为跑通链路编的判断，不能留在
  产品里冒充产品负责人的意见；基于它归纳出的 v2 人设同样要回到干净的 v1 播种态

# 十、尝试切换到公司 LiteLLM 网关（2026-07-28）—— WORKLOG #59 详节，⏸️ 未生效已回退

Lawrence：「立刻把这个rec hub服务改造成 都用这个key来做，包括新闻的处理，都用
这个key来做，而不是用本地claude的credit了...直接用最好的gpt模型 或者opus4.8」，
并提供了公司 LiteLLM 网关的 key 与接入文档。

## 做了什么

1. **验证网关本身**：从本机（Mac）真实调用网关，确认可达、鉴权通过、模型清单
   与文档一致。用真实 `response_format: json_schema, strict:true` 请求逐个测试
   候选模型：`gpt-5.4`/`gpt-5.4-mini`/`gpt-5.6-luna`/`gpt-5.6-sol`/`gpt-5.6-terra`
   全部支持 strict schema；**`claude-opus-4-8`（文档里唯一非 bedrock 前缀的
   Claude，对应用户说的"opus4.8"）经 Bedrock 通道报错 `output_config.format:
   Extra inputs are not permitted`——不支持这套代码从 pipeline 结构化到评测工具
   全部依赖的 strict json_schema 模式**，排除。embeddings 端点验证
   `text-embedding-3-small` 支持 `dimensions=256` 参数且输出单位向量，与现有
   1300+ 条事件的向量空间兼容。
2. **确认全仓路由早已 env 化**：`crawler/pipeline.py`/`sector_relevance.py`、
   `api/eval_tools.py`/`persona_tools.py` 的 OpenAI client 构造统一读
   `OPENAI_API_KEY`/`OPENAI_API_BASE`，理论上只改 `config/.env` 两行、代码零改动
   即可切换（模型仍用 `gpt-5.4`，已在这套 schema 上验证过，5.6 三个变体连
   网关自己的文档都写"疑似同代不同调优分支，具体差异待确认"，产线不动未验证
   型号）。
3. **实际切换后端到网关**：`config/.env` 改 `OPENAI_API_KEY`/`OPENAI_API_BASE`
   指向网关，旧个人账号 key 注释保留做回滚；部署重启服务确认存活。

## 发现的阻塞（关键）

**从 VM 直接测试时，`litellm.devfdg.net` 直接 DNS 解析失败**（`Could not
resolve host`）。追查发现：这个域名在能访问它的网络（比如本机 Mac）解析到的是
`172.21.x.x` 一段私网 IP，背后是一个内部 ELB
（`internal-k8s-backend-litellmi-...`）——**这个网关是 Binance 内网专用服务，
根本不对公网开放**，不是防火墙拦截可以绕过的问题，是网络层面本来就连不通。
这台跑生产 pipeline 和 Flask API 的机器是 GCP 上的公网 VM，不在 Binance 内网/
VPN 里，永远连不上这个地址，除非：①网关方把服务开放给这台 VM 所在网段，或
②把 pipeline 挪到能连通内网的机器上跑（这两者都不是我能单方面决定或操作的，
需要 Lawrence 判断）。

**已立即回退**：发现问题后第一时间把 `config/.env` 改回旧个人 OpenAI 账号 key，
重启服务，用真实调用（`crawler/pipeline.py.enrich_one()` 跑一条测试新闻）+
全量 QA 门禁（94/94，含付费用例）确认服务完全恢复正常——策略产品工作台全程
没有对外呈现过故障状态。

**连带撤销了"暂停本地 Claude 预处理桥"**：用户要"不用本地 claude credit"的
前提是"改用公司网关"，既然网关切换没有生效、生产环境实际仍在用个人 OpenAI
账号出钱，继续暂停本地预处理桥（`launchctl unload
com.lawrence.b9-enrich-worker`）就只会让个人账号多花钱、没有任何对应好处——
前提不成立时不该保留这个动作的后果，已 `launchctl load` 恢复。

## 现状

- 生产环境（pipeline + Flask API 全部工具）：**仍是原来的个人 OpenAI 账号**，
  未受影响，一切如常
- 网关 key/base 已完整写入 `config/.env`（注释状态，含到期日期 2026-08-03、
  排障过程、回滚步骤），随时可在网络问题解决后一行切换启用
- 本地 Claude 预处理桥：已恢复正常调度

## 需要 Lawrence 决定的事

1. 网关只对内网开放这件事是否符合预期？如果预期就是"仅供内网机器使用"，那
   这台 GCP VM 上的生产服务大概率始终无法直接使用它，除非迁移运行环境或让
   网关方开白名单
2. `claude-opus-4-8` 即使网络问题解决，也需要先把本仓库里依赖 strict json
   schema 的调用点（pipeline 结构化 + 评测工具全部接口）改造成 tool-calling
   形式的结构化输出才能使用——这是一次单独的、有一定回归风险的工程改动，
   不在这次"立刻切换"的范围内
3. 网关的安全提示明确写"key 不要写进代码仓库或聊天记录明文留存"，但这个项目
   一直以来的约定是 `config/.env` 直接提交进私有仓库（README/`.gitignore`
   都有明确记录和理由）。这次沿用了项目既有约定，但这条冲突值得知会一声，
   由 Lawrence 判断是否要为这个 key 破例走不同的存储方式

# 十一、本地 enrich worker 改用 LiteLLM 网关（2026-07-28）—— WORKLOG #60 详节

Lawrence：「可以在本地调这个接口跑吗？如果可以的话我不想花claude的token了 而是
用这个接口。本地有公司VPN网关，估计可以调通」——针对 WORKLOG #59 网关切换受阻
（VM 连不通内网）之后的追问：VM 连不通，但 Mac 挂公司 VPN，理论上能连通同一个
网关。

## 验证 + 实现

1. 从 Mac 直接 curl 网关（VPN 已连），确认可达——这就是 WORKLOG #59 里发现的
   同一个内网地址，只是这次是从「在内网里的机器」发起，而不是从 GCP VM。
2. 改造 `scripts/local_enrich_worker.py`：把 `enrich_with_claude()`（subprocess
   调用本地 `claude -p` CLI，吃 Claude Max 订阅额度）替换成
   `enrich_with_gateway()`（`urllib` 直接调网关的 `/v1/chat/completions`，用
   VM 同一份 `response_format: json_schema strict:true`）。因为网关是 OpenAI
   协议兼容端点、支持 strict schema，返回的就是合法 JSON 字符串，不再需要
   claude CLI 那套"从自由文本里抠 JSON"的防御性解析（`extract_json()` 降级为
   兜底，不是主路径）。删掉了整个 `find_claude()` 查找逻辑和 `subprocess`/
   `shutil` 依赖。
3. 模型选 `gpt-5.4`——WORKLOG #59 已经用真实 schema 测过它在这个网关上工作正常；
   `claude-opus-4-8` 经 Bedrock 通道不支持这个模式，不在候选里。

## 踩到的坑：网关对这把 key 硬限 30 请求/分钟

第一次真实批量跑（76 条待处理条目，并发 6）几秒内就把 30 个请求打完，剩下的
全部收到 429（响应体里明确写"Current limit: 30"）。这不是瞬时抖动，是稳定
触发的硬顶——线程池不加约束地并发发请求，在网关这种强限流环境下必然撞上。

**修法**：加一个线程安全的滑动窗口限流器（`RateLimiter`，纯标准库
threading.Lock 实现），6 个 worker 线程发请求前统一先 `acquire()`，从源头把
这个进程自己的请求压到 `GATEWAY_RPM=25`/分钟（网关限 30，留 5 个余量）。
同时把"撞到 429 要不要重试"的逻辑简化：不在同一轮里重试（重试大概率还在同一
个限流窗口内，纯浪费时间），直接放弃这条，下一次唤醒（15 分钟后）自然会从
`/api/enrich/pending` 重新领到它——按 25/min 换算，理论吞吐上限是
25×15=375 条/次唤醒，远超 `BATCH_SIZE=100`，即使某次唤醒没处理完全部
也有充足冗余，不构成数据丢失（这条设计延续了本模块一贯的"miss 不影响正确性，
只是没省到钱/慢一点"的容错哲学）。

修完后干净重跑一次（46 条待处理，无外部干扰）：**46/46 全部成功，全程无 429**，
限流器在处理到第 26 条附近正确地暂停等待配额（日志里能看到明显的等待间隔），
证明这套节流是真实生效的，不是巧合。

## 现状

- `scripts/local_enrich_worker.py` 已改造完成并部署到实际运行位置
  （`~/.b9/local_enrich_worker.py`），launchd 调度不变（每 15 分钟）
- 累计已通过网关真实处理并写入 VM `llm_enrich_cache` 的条目：106 条
  （`model='litellm-gateway/gpt-5.4'`），全部是真实 staging 积压条目，非测试
  数据，无需清理
- 记账口径改了：以前是零边际成本（Claude Max 订阅固定费），现在这部分费用
  走网关的 1000 美元额度——仍然是"不吃个人 OpenAI 直连账号的钱"，但不再是
  完全免费，日志里的"省下的钱"措辞已相应改为"走网关额度而非 VM 直连账号"，
  不夸大实际收益
- 网关 key 到期日 2026-08-03 仍然适用——到期后这条链路会开始失败，届时会
  自动 miss 回落到 VM 的 OpenAI 直连账号（零功能损失），需要续期才能恢复
  这部分省钱效果

# 十一、全球市场扩召回 + 情绪排序 + dxFeed 接入（2026-07-28）—— WORKLOG #61 详节

老板经 Lawrence 转达：B9 只爬币圈新闻不够，美股/港股/日股/韩股/世界主要经济
新闻（对股市/资产/价格有直接影响、能调动情绪的）必须接，"用户买的是价格不是
价值"；明确排除 A 股；排序要做情绪对齐（大盘悲观时同向内容该更突出）；权威
主流财经媒体要加权；币圈和主流资本内容要混排成一个列表，服务同时关心大盘和
币价的真实用户（对标 Robinhood）；内容理解加一个市场归属的新标签维度。
导火索是 PM 群聊里的真实案例：日经跌超4%、KOSPI熔断当天，B9 相关页面完全没有
体现这个氛围。

## 根因诊断（这一步比想象中关键）

召回本身其实**已经**抓到了这类内容——币圈媒体（吴说/TechFlow深潮/BlockBeats）
本来就会报道"日经跌4%"这类大盘异动作为市场背景。真正的问题在
`crawler/pipeline.py` 的 GENERIC-TECH FIREWALL：这条规则专门把"没有清晰加密
传导路径的通用科技/大盘新闻"打成 D 档、`score_market_impact≤0.20`——这是老
系统"只服务加密用户"时代的合理设计，但现在产品要求把这类内容当**一等公民**
处理，同一条规则就变成了系统性压制。不是漏召，是召回了但被主动雪藏。

## 做了什么

**召回扩面**（`crawler/web_search.py` + `crawler/sources.py` + `crawler/main.py`）：
- `RSS_SOURCES_GLOBAL_MARKETS` 新增 7 个源：CNBC（TopNews/Economy/Investing 三个
  频道）、MarketWatch、Nikkei Asia、SCMP-Business、Korea Herald——全部实测
  HTTP 200 的真实 RSS，不是猜的 URL
- `GOOGLE_NEWS_QUERIES` 新增 20 条 `gm_*` 查询覆盖美股大盘/美联储/CPI、港股、
  日股、韩股、关税与全球宏观政策，中英各半
- 域名权威分级新增：cnbc.com/marketwatch.com/nikkei.com 升入最高档（对齐
  Reuters/Bloomberg），scmp.com/cnn.com 与 koreaherald.com 等区域媒体分别入档
- **修了一个新查询组会被误杀的坑**：`_dedup_and_filter` 原有的"主题相关性"
  过滤只认加密关键词，`gm_*` 这批查询词本来就不含加密词汇，会被判定
  offtopic 整批丢弃。新增 `_MARKET_KEYWORDS_RE`，按 `_category` 分流两套
  关键词判定，不是共用一套
- `crawler/main.py` 新增 `filter_a_share()`：标题命中沪指/上证综指/深证成指/
  创业板/A股等关键词直接丢弃，应用在全部信源合并之后、freshness 过滤之前
- **dxFeed News 接入**（`crawler/dxfeed_news.py`，独立小节见下）

**新增 market_scope 标签**（migration 013）：crypto/us_stock/hk_stock/
jp_stock/kr_stock/macro_policy/general，与已有的 `news_type`（事件性质）正交
——一条"美联储加息"新闻 news_type=macro、market_scope=us_stock，两者独立。
`crawler/pipeline.py` 的 LLM schema/prompt、`crawler/storage.py` 写入、
`api/server.py` 的 `EVENT_COLUMNS`/`market_scope` 筛选参数同步更新。

**system prompt 从"加密新闻分析师"扩成"全球市场分析师"**（这是本次风险最高
的改动）：
- 新增 MARKET SCOPE 分类章节，含"A股即使漏进来也不要打标"的兜底说明
- **GENERIC-TECH FIREWALL 明确限定"仅适用于 market_scope=crypto 的事件"**，
  这是修复 PM 那个 bug 的关键一行
- 新增一套独立的 S/A/B/C/D 分级标准给非加密市场事件用（大盘单日跌幅
  ≥4%=S、≥2%=A，等等），不与加密的分级标准混用
- `score_authority` 的"顶级媒体"举例加入 Reuters/Bloomberg/CNBC/WSJ/FT/
  Nikkei Asia/MarketWatch
- `sentiment`/`sentiment_score` 的口径从"对加密市场的方向性影响"扩展为
  "对相关市场自身的方向性影响"，并标注这个字段会喂给全站的大盘情绪聚合

**情绪排序**（`crawler/market_mood.py` + `api/server.py`，新模块）：
- 计算近 48 小时内 importance_score≥0.35 的事件（币圈+宏观混合）按重要性
  加权的情绪均值，产出"极度乐观/偏乐观/中性/偏悲观/极度悲观"标签
- **刻意不碰 `crawler/scoring.py` 的五因子公式**：情绪对齐加成只在
  `/api/news` 查询时对候选池做有界（≤15%）重排，不写回 `importance_score`
  ——那个字段是策略实验室/去重/历史分析全部依赖的口径，被"今天的情绪"污染
  会让不同天算出的分不可比
- 48 小时而非字面"今天"：主流水线现在每 2 天 1 轮，24 小时窗口会在两轮之间
  大概率查无数据，48 小时保证覆盖到最近一轮产出
- 新增 `GET /api/market-mood`，5 分钟进程内缓存
- `/api/news` 在 `sort=importance` 时改为：查一个比页面大的候选池
  （`min(500, offset+limit*5)`）、按情绪对齐乘上加成、应用层重排后再切页
  ——直接在 SQL LIMIT/OFFSET 上做会在翻页边界产生错误结果

**dxFeed News 机构新闻源接入**（`crawler/dxfeed_news.py`，新模块）：
Lawrence 转发了公司通过 Binance 账号采购的 dxFeed 试用凭据（同事 Drew Zhu
对接），连着一份 Benzinga（Massive 平台）的示例数据包一起发来问"是不是有
能用的 key"。核实结果：
- **Benzinga/Massive**：压缩包里只有示例响应 JSON 和字段文档，**没有真实
  key**，massive.com 文档页也没写 base URL 或申请方式，需要另外找账号负责人
- **dxFeed News**：**是真实可用的凭据**。实测 `https://news.dxfeed.com` 用
  HTTP Basic Auth（binance/密码）直接查通，聚合的是 MT Newswires 的机构级
  实时美股新闻（分钟级，真实调用返回"Nvidia $500B AI 基础设施合作"
  "Morgan Stanley 首次覆盖 Riot Platforms 予增持"这类高信号内容），比搜索
  引擎抓回来的内容权威、及时得多。已接入并配置 21 个精选 symbol（大盘指数+
  头部ETF+市值最大科技股+加密概念股）——**踩到一个真实的 API 限制**：
  symbol 参数一次最多传 10 个，超过直接 400（不是限流，是硬性数量上限，
  逐个测过每个 symbol 单独查都能通），改成按 10 个一批分批查询、按 id 去重
  合并结果解决
- **关于 opus-4-8**：用户这次追问"不差钱，能用最好的模型就用"，结论沿用
  之前的实测——网关上的 opus-4-8 经 Bedrock 通道不支持这套代码依赖的
  strict json schema，是技术硬限不是预算问题，产线继续用 gpt-5.4，如实
  回复用户不是揣着明白装糊涂地默认换掉

**前端**（`web/index.html`）：
- 筛选器新增"市场 Market"下拉（7 个选项，emoji 国旗区分）
- 表格/详情/App 模拟器三处都加了 market_scope 徽标（`marketBadge()`/
  `MARKET_BADGE` 映射，非 crypto 的几个市场配色区分度更高，一眼看出"这条
  不是币圈新闻"）
- 新增"大盘情绪横幅"，放在 tab02 最顶上、筛选器之前——"排序结果尤其是首
  几刷要有冲击力"，情绪判断本身就该是进这个 tab 第一眼看到的东西

## 真实验证（这步做得比较扎实，不是纸面自测）

没有跑全量 3485 条历史积压（成本不可控），而是从当天真实抓到的数据里挑了
一批有代表性的样本（17 条：KOSPI/日经崩盘的 8 条原始报道聚类、5 条
dxFeed 真实新闻、CNBC 一条"美韩科技股联动创新高"、MarketWatch 一条、2 条
普通加密新闻做混排对照），通过 monkeypatch `staging.fetch_staged_items`
让**未经改动的真实 `run_pipeline()`** 只消费这 17 条，其余全部走真代码
（结构化/去重聚合/跨轮归并/校验/打分/入库/存档标记）。结果：

- 17 条原始 → 11 条最终事件（8 条 KOSPI/日经系列被正确聚合成 2 条canonical
  事件，证明 embedding 去重在非加密领域一样生效）
- **"KOSPI跌超8%触发熔断"**：`market_scope=kr_stock`，**S 档 0.7131 分**，
  情绪 -0.91（强烈看跌），3 个信源合并（BlockBeats/TechFlow深潮/吴说）
- **"日经225跌4% 铠侠跌18%"**：`market_scope=jp_stock`，**S 档 0.6288 分**，
  情绪 -0.87
- 加密新闻（"Blockaid称上半年加密损失超10亿美元"，B档）与美股新闻
  （"科技股盘前走高"、"大摩首次覆盖Riot予增持"，均 C档）混在同一个按
  importance_score 排序的列表里——不是两个列表拼起来
- 浏览器实测：情绪横幅正确显示、驱动因素列表正确列出 KOSPI/日经两条并带
  国旗徽标；市场筛选器切到"韩股"正确过滤出 2 条；不筛选时的混排列表里
  "KOSPI跌超8%触发熔断"出现在第 3 位，前后紧邻 BTC/ETH ETF 新闻和 BitMine
  增持——这就是"混排"要的效果
- QA 门禁新增第 8 组共 4 条用例（含一条真实踩坑：普通 SQL `LIKE` 在
  `utf8mb4_unicode_ci` 排序规则下会把"Cathie Wood买入Meta股票"误判成命中
  "A股"关键词，改用 `BINARY` 精确匹配后确认库内 2026-07-28 起新入库事件
  零 A 股残留），**98/98 全部通过**

## 顺带发现，未处理（如实记录，不夸大成果）

- **SCMP-Business RSS 内容偏软**：拉回的更多是"香港女子体检故事""马来西亚
  F1 赛事"这类泛生活/时事新闻，不是密集的港股大盘动态。权威分级本身没错
  （SCMP 确实是可信媒体），只是这一路 RSS 单独接入不足以撑起"港股市场动态"
  这个诉求，后续如果 Lawrence 找到的可靠信源里有更聚焦港股的（比如 HKEX
  官方公告、经济日报），应该优先加那些
- **大盘情绪目前是 48 小时全窗口加权均值**，会被大量中性/常规内容稀释——
  实测这批验证数据插入后，全局 mood_score 只有 -0.009（约等于中性），
  尽管 KOSPI/日经崩盘被正确识别为"最大驱动因素"并列在横幅里。如果
  Lawrence 想要的是"只要今天有大新闻就应该整体大幅偏向"而不是"稀释在
  48 小时全部事件里的均值"，这里的窗口/权重需要重新调，现在的实现偏保守

# 十二、当天二次修正：去掉加密限制 + 提频到每小时（2026-07-28 晚）—— WORKLOG #62

Lawrence 看到线上结果后连提三点：①"不要再强限制加密新闻了！！！所有美股、日韩、
港股、世界经济的新闻都应该要放出来"；②贴 CNBC 首页截图问"这几条为啥咱们都没有
抓到"；③"用公司key扫描就不要2天1次了，改成1个小时1次"。另外追问了情绪横幅
"这样大跌还是中性的嘛，为啥？"。

## A. 情绪显示"中性"的根因（真 bug，不是阈值品味问题）

门槛用错了字段。原实现是 `importance_score >= 0.35`，实测 48 小时窗口里 **782 条
D 档事件的 importance_score 均值高达 0.317**，大量个体轻松越过 0.35——因为
importance_score 是五因子加权总分，M（影响面）虽被夹在 D 档区间 0-0.14，但
T/H/A/Q 四个因子不受 tier 约束，单独拉高照样把总分推过门槛。结果 460 条样本里
绝大多数是"分数蒙混过关的次要事件"，把两条真正的 S 档崩盘稀释成噪音，
mood_score 只有 -0.009 → 显示"中性"。

改成用 `event_tier IN ('S','A')` 做门槛（importance_score 继续用作样本内部权重，
但不再兼任"够不够格参与"的判据）。同一批数据：样本 460 → 18 条，
mood_score -0.009 → **-0.154，显示"偏悲观"**，驱动因素正确列出 KOSPI/日经/
美空袭伊朗三条。**教训：筛选门槛要用 LLM 对事件本身的判断（tier），不能用会被
时效/热度污染的复合分。**

## B. CNBC 那几条为什么没抓到——召回没问题，是管道积压

逐层排查后确认召回链路完全正常：直接调 `fetch_rss('https://www.cnbc.com/id/
100003114/...')` 当场拿到 30 条，**"AMD, Micron and Nvidia extend losses as chip
stocks get clobbered" 和 "Blurred front lines: Trump to meet Zelenskyy" 两条都在
结果里**，freshness 过滤 30 条一条没丢。

真实原因是两个叠加：
1. **管道积压 3468 条未消费**，而 pipeline 每 2 天才跑一轮——一条 CNBC 头条最长
   要等 48 小时才会变成前端可见的事件。用户看到的"没抓到"，实际是"抓到了但还
   排在队列里"。
2. **就算处理到了也会被压制**：旧 prompt 的 GENERIC-TECH FIREWALL 会把这类新闻
   打成 D 档。实测修复后同样两条：`AMD/Micron/Nvidia` → **us_stock B 档 M=0.48
   情绪 -0.52**、`Trump-Zelenskyy` → **macro_policy B 档 M=0.46**，此前是 D 档
   M≤0.20。

## C. 去掉对非加密内容的残留限制

1. `crawler/web_search.py`：主题相关性过滤原来按查询分类二选一（gm_* 判市场词、
   其余判加密词）。这仍是限制——一条从 "Fed crypto" 查询里捞回的纯美股报道，
   因标题没有加密词就被当 offtopic 丢掉（实测一轮丢 168 条，里面混着这类）。
   改成 **加密词 OR 市场词任一命中即放行**，这道闸退回它本该做的事：挡跟金融
   市场完全无关的水文，而不是给内容划范围。
2. `crawler/pipeline.py` SYSTEM_PROMPT：新增 **CLASSIFY FIRST, THEN SCORE** 章节，
   明确"先定 market_scope 再定 tier"，并写死"把芯片股/AI公司/关税/央行/财报/指数
   类新闻误判成 market_scope=crypto 再因缺加密角度扣分，是本系统最坏的失败模式"；
   原 GENERIC-TECH FIREWALL 拆成对所有 scope 生效的 **LOW-VALUE FILTER**
   （低信息量才降档，与属于哪个市场无关）+ 仅对 crypto scope 的残留规则；
   加密 D 档定义里删掉"generic tech/AI news without crypto path"。

## D. 提频到每小时（含两个必须先补的防护）

crontab：`0 8 */2 * *` → **`0 * * * *`**（主 pipeline 每小时整点）；stage_fetch
`每2小时` → **`30 * * * *`**（每小时 :30，纯抓取零成本；CNBC-TopNews 这类高频源
RSS 窗口只有 30 条约 2 小时的量，2 小时一次正好卡在滚屏丢失边缘）。

提频前补的两道防护（不补会真出事）：
- **单轮上限 400 条**（`staging.MAX_ITEMS_PER_RUN`，可用 `B9_PIPELINE_BATCH` 覆盖）。
  原来没有上限——两天一轮时"一次吃掉攒下的全部"正是想要的，改每小时后同一行为
  意味着 3468 条积压会在第一次触发时一口气进 LLM，单轮跑几小时、费用集中爆发，
  且期间下个整点照常触发。取满上限时 **显式 WARNING 打出剩余积压和预计追平时间**，
  不做静默截断。
- **flock 单实例锁**（`run_pipeline.py`）。两天一轮时一轮跑 20 分钟不可能撞上下
  一次；每小时之后只要某轮超 60 分钟就会叠跑，而 `consumed_at` 要到写库成功才
  标记（见 staging.py 的说明），两个进程会读到同一批未消费条目 → 同内容结构化
  两次 → 钱花两遍。拿不到锁直接退出，不排队不重试。

## E. 成本口径（必须说清楚，用户的前提是"不花自己钱"）

**VM 连不通公司 LiteLLM 网关**（内网专用，实测 `gateway:000` DNS 失败），所以
VM 上的 pipeline 走的是 **Lawrence 个人 OpenAI 直连账号**。直接提频到每小时
= 个人账号支出上升 24 倍，与"用公司key就不花自己钱"的前提直接冲突。

已确认的可行解（用户随后确认"我电脑不关"）：靠已有的 enrich bridge 架构——
Mac 挂公司 VPN 能连网关，`local_enrich_worker.py` 每 15 分钟拉 staging 待处理
条目、用**公司网关**结构化、回写 `llm_enrich_cache`；VM pipeline 命中缓存的
条目 **0 次 OpenAI 调用**。本次把 worker 的 `B9_BATCH` 从 100 提到 **300**
（限流器 25 req/min × 15 分钟理论上限 375，留 20% 余量），吞吐 1200 条/小时，
**刻意高于 pipeline 的 400 条/小时**——让免费那条腿始终跑在付费那条腿前面。
Mac 离线时自动回落个人账号（零功能损失，但要花钱），这是唯一的依赖。

## F. 顺带修掉的信源错误（自己上一轮埋的）

SCMP 接的是 `rss/91`，看 URL 以为是商业频道，**实际是综合新闻频道**——上线第一轮
就抓回大量"香港网红去世""山东夫妻坠井获救""补习中心负责人判囚"，全部要先付一遍
LLM 结构化的钱才被判成 D 档丢掉。实测确认各频道 ID 后换成 `rss/92`（Business）
+ `rss/12`（Global Economy），换完抓回的是"港交所外汇基金上半年收益降37%"
"中国反驳西方产能过剩论"这类真正对口的内容；已入库未消费的 50 条噪音直接删掉。
**教训：接 RSS 不能只看 URL 猜频道，必须打开 `<title>` 确认。**

## 验证

- 两条 CNBC 目标头条走真实 `enrich_one()` 分类正确（us_stock/macro_policy，均 B 档）
- `/api/market-mood` 返回 -0.154 偏悲观、18 条 S/A 样本、驱动因素正确
- 新 SCMP 两个频道实测各 50 条，内容对口
- QA 门禁 **97/97 全绿**
- crontab 已生效，单实例锁与 400 条上限已部署

---

# 2026-07-29 · PRD-03 排序因子扩展与监控看板（Phase 14）

对应 `docs/prd/PRD-03-热度氛围与排序因子扩展.md` 与 `docs/adr/ADR-001-排序因子扩展与处理优先级架构.md`。
交付报告见 `docs/DELIVERY-2026-07-29.md`。

## A. 两段式打分模型

打分从"五因子加权"改成 **BaseScore（七因子）× (1 + 同向加成 + 反转加成)**。

七个基础因子与权重：M 影响面 .26 / B 广度 .16 / T 时效 .16 / I 冲击力 .14 /
H 热度 .10 / A 权威 .10 / Q 质量 .08。新增的 B 与 I：

- **B（广度）** 由 LLM 输出五档枚举（cross_market 1.0 / market_index 0.8 /
  sector 0.6 / multi_asset 0.35 / single_asset 0.15）后映射成分值，不让模型
  直接打 0-1——枚举的判据可写清楚、可复核，连续分只会得到一堆 0.7。
- **I（冲击力）** = 0.65×数值幅度 + 0.35×权威共振，**纯计算零 LLM 调用**。
  Lawrence 原始描述里的"对社会经济重大影响"一项刻意没做——它已经被 M 和 B
  覆盖了两遍，再单列就是三重计分。

两个加分项（`crawler/market_mood.py`）是**查询时的外层倍率，绝不写回
importance_score**：它们依赖每天都在变的 mood_score，写进库会让跨天的分不可比。
反转加成带 **tier ∈ S/A 硬约束**——没有它，大盘单边时所有反向噪音都会被扶上来。

## B. 处理优先级队列

`raw_items_staging` 加 `priority`（P0 权威大盘媒体 → P4 dxFeed 个股），
消费改成 `ORDER BY priority ASC, fetched_at ASC`。CNBC 这类头部媒体的内容
不再排在 3000 条积压后面。批量从 400 提到 800/轮。

## C. 存量重算：87% 的分是旧公式算的

**这是本期最容易被漏掉、影响却最大的一件事。** 按当前公式给全库反算并比对，
结果是：新七因子吻合 402 行、旧五因子吻合 1865 行、两者都不吻合 907 行——
**3174 行里只有 402 行（13%）的排序分是按现行公式算的**。前端按
importance_score 排序，等于把三个不同公式算出来的分放在一个列表里比大小。

如果不先修这个，本期"排序变好了吗"的业务测试测出来的差异有很大一部分只是
"哪些行碰巧被新公式重算过"，结论没有意义。

`scripts/rescore_factors.py` 分三阶段修：LLM 回填 breadth_level（2776 条，唯一
花钱的一步，约 $6）→ 离线重算 score_punch（纯计算）→ 重算 importance_score。
**刻意不重算 T 和 H**：它们依赖"现在几点"和当时的社交基准，离线重算会把所有
历史事件的时效分刷成"很旧"，制造出本期改动之外的新变化，让对比失去干净的对照。

重算后：3168/3168 全部吻合当前公式，breadth 零缺口。

顺带修掉根因——`storage.py` 的跨轮归并 UPDATE 刷新了 `score_punch` 却漏了
`breadth_level`/`score_breadth`，导致 migration 014 之前入库的行被归并碰过之后
永远补不上广度，在策略实验室重算时走 `BREADTH_DEFAULT=0.15`（五档最低）。
改成 `COALESCE(旧值, 新值)`：只填空不覆盖，不违反"内容字段不覆盖"的既有约定。

## D. 新闻类型独立标签 + 筛选器

`market_scope` 对外正名为「新闻类型」，加 `social_signal`（要求有明确的市场
传导路径，明星八卦/体育赛果不收）。前端 chip 筛选条带实时计数，事件卡片上
"未标注"清零。

## E. 策略实验室两段式改造

- 滑杆分成**两组**：基础因子（归一化 100%）与加分项（外层倍率上限）。刻意
  没有复用同一个 Panel 组件——Panel 的核心行为是归一化，而加分项恰恰不归一化，
  混在一起会让"拖高同向 → 其它因子被稀释"这种完全错误的反馈出现在界面上。
- 点任意一行**展开正文 + 逐因子明细**（Lawrence 原话「现在不够好用」）。
  因子表给三列：原始分、权重、**加权贡献**——只给原始分用户还得自己心算乘权重，
  贡献值才直接回答"这条是被哪个因子推上去的"。条形按贡献占比画。
- 底部算式行显式写出 `基础分 × (1 + 同向 + 反转) = 最终分`。

## F. tab07 监控看板

24h 抓取量 / 待处理积压 / 处理速度 / 最老待处理年龄 / 失败率，已入库量与
S+A 有效量按**整体 / 加密 / 非加密**三档拆开，外加按优先级的积压表与最近轮次表。

## G. A 股排除：关键词黑名单靠不住，改成双闸

**一天之内这张关键词表漏了三次**，每次都是同一个错误：

1. 裸的 `上证` 漏网（表里只写了"上证综指/上证指数"全称）→「亚太股市重挫
   上证失守3800」排到策略实验室**第 1 名**；
2. `A股` 带 IGNORECASE **误杀美股**——任何以字母 a 结尾的公司名 + "股" 都命中，
   实测打掉了「Meta股价财报前跌近10%」「Cathie Wood买入Meta股票」「GE Vernova
   股价目标」。美股偏少恰恰是本期要解决的问题，属于自己给自己制造问题；
3. 裸的 `创业板` 漏网 →「创业板半日重挫5.37%」排到主站首屏**第 3 名**。

结论是**穷举措辞这条路走不通**。改成两道闸：
- 关键词表退回它擅长的位置：LLM **之前**的省钱粗筛（并补全简称、加
  `(?<![A-Za-z])` 前瞻断言修掉误杀）；
- 新增 `market_scope = cn_a_share` 枚举做**语义闸**，在 LLM **之后**整类丢弃。
  给 A 股一个正确的名字再丢掉，比把它从枚举里拿掉、逼模型塞进 general 更可靠。
  实测：「创业板半日重挫5.37%」「亚太股市重挫，上证失守3800点」→ cn_a_share；
  日经 → jp_stock；恒生 → hk_stock（港股不算大陆，没有被误伤）。

另外发现 `filter_a_share` 结构上就拦不住一类：它查的是**原始标题**，而 LLM 会
改写标题——「A股低开，长鑫跌7.7%」的原文（BlockBeats 关于长鑫存储的快讯）
一个"A股"都没有，是模型写出来的。所以 LLM 后必须有一道闸，这不是重复。

## H. BinanceSquare：关水龙头不等于清管道

QA 红线重新亮红，查出来是币安广场（无发布时间，陈旧新闻事故的源头）虽然在
`crawler/main.py` 关了抓取开关，但 staging 里还压着 119 条历史存货，流水线照常
把它们捞出来送进 LLM 并入库。`crawler/staging.py` 的消费查询加 `DISABLED_SOURCES`
黑名单，两头都堵。

（写 SQL 时踩到：`NOT IN %s` 直接传元组是 psycopg2 的行为，mysql-connector 会报
"Python type tuple cannot be converted"，必须按数量展开成 `%s, %s, ...`。冒烟
测试抓到的。）

## I. 前端过时文案

tab01 上还写着"每 2 天 1 次自动运行"（实际已是每小时）和"五因子重要性打分"
（实际是七因子 + 两加分项），共 10 处，全部改正。这类文案不是装饰——它是对外
讲方案时的依据。

## 验证

- QA 门禁 **100/100 全绿**（含新增/扩口径的 A 股与时效红线）
- 业务效果（`scripts/effect_test.py`，对照 `ranking_before_20260729` 真实快照）：
  非加密首屏占比 45% → 55%；S/A 档占比 80% → 90%；Top20 换手率 45%；
  广度因子首屏 0.705 vs 全库 0.416、冲击力 0.693 vs 全库 0.250（两个新因子
  都有明确区分力，不是白算的）
- 浏览器实测：情绪横幅 -0.25 偏悲观（驱动因素 KOSPI/日经/KOSDAQ）、9 个类型
  chip 带实时计数、首屏韩股/日股/美股/经济政策/社会信号真实混排、策略实验室
  八因子 + 两加分项滑杆与展开明细全部生效、全站无"未标注"无 A 股残留

---

# 2026-07-29 · 打分版本护栏 + 护栏当场抓到自己种的新 bug

Phase 14 交付后，把"87% 存量是旧公式"这件事沉淀成永久机制，而不只是写进文档。

## 加了什么

1. **`scoring_version` 列**（migration 015）：`news_events` 加一列标记"这行的
   `importance_score` 是按哪个打分公式版本算的"。`crawler/scoring.py` 加
   `SCORING_VERSION` 常量，改因子集合或权重必须同步 +1。之前这类问题只能靠
   反算比对去猜，现在是一条 `WHERE scoring_version < N` 就能查。
2. **QA 门禁两条新红线**：
   - 库内无 `scoring_version` 落后于当前值的行
   - 抽样 300 条核对标记版本与实际数值真的吻合（防止版本号被错误标高而没人发现）

## 护栏部署后，第一个生产轮次自己就撞上了一个新 bug

两条红线上线几分钟后，当天最新一轮生产 pipeline（run 21, 03:09）跑完，第二条
断言就报了 121 条不吻合——不是历史遗留，是**这次改造自己引入的新问题**。

根因：为了填平"145 行广度永久 NULL"的坑，`storage.py` 的 `ON DUPLICATE KEY
UPDATE` 把 `score_breadth`/`breadth_level` 从"不提"改成了 `COALESCE`（只填空、
不覆盖）。但 `importance_score` 依然是每次都刷新（`VALUES`），用的是**这一轮**
LLM 重新分类出来的新广度值。于是跨轮归并时：MySQL 端把 `score_breadth` 按
`COALESCE` 保留成老值，Python 端算 `importance_score` 时却用了这一轮的新值——
两者在同一行里对不上，`importance_score` 变成了"用一个被丢弃的输入算出来的数"。

`COALESCE` 当初的动机（"不覆盖已展示内容"）只对标题/正文这类主观措辞成立——
那是 2026-07-28 就定下的约定，"同一事件跨轮重复抓到时，LLM 每次改写措辞略有
不同，覆盖会让前端已展示的卡片文案无故抖动"。但数值型因子如果分类真的变了
（LLM 判断这次事件的广度不一样了），分数就应该跟着变，跟 `score_punch`/
`score_timeliness`/`score_hotness` 一个道理——这三个从一开始就是 `VALUES`。
`COALESCE` 用在了不该用的地方。

改回 `VALUES`（一次性回填已经把老的 145 行缺口填平，`COALESCE` 存在的理由
已经不成立），重跑 `rescore_factors.py` 修掉这 121 行，QA 回到 102/102。

## 这件事印证的道理

护栏抓到的不是"以前的错"，是"几小时前我自己犯的新错的变体"——同一个根因
（派生列刷新不同步）在同一天换了个形状又出现了一次。这说明：
- 这类 bug 不是"这次改完就没事了"，是**持续性风险**，会随便一次改动重新引入
- 靠人复查发现不了：这条数据仍然是合法浮点数，仍然能排序，页面照常渲染
- 唯一可靠的防线是**自动化断言**，且必须覆盖"新代码上线后的第一次真实写入"，
  不能只在改造当天跑一次就算完事——这也是为什么这两条红线要进 QA 门禁常驻，
  而不是写一次性脚本跑完就扔

---

# 2026-07-29 · 召回补源 + 反转加成生产环境未生效的修复 + 榜单标签/筛选器

对应用户当天连续四点指示：召回校验、信源覆盖审查、稳定运行、策略实验室可用性。

## A. 召回校验结论（CNBC/Forbes/Bloomberg/dxFeed）

- **CNBC**：覆盖充分。5 个专用频道（TopNews/Economy/Investing/Finance），近 2 天
  仅 TopNews 一个频道就有 23 条独立入库，P0 优先级下插队处理。
- **Forbes**：**此前压根没有专用信源**——库里唯二的 2 条 Forbes 记录来自
  web_search 搜索结果碰巧引用了该域名，不是真正的媒体订阅。逐个探测
  investing/markets/wealth/leadership/digital-assets/innovation 六个看起来
  对口的路径，只有 business 和 innovation 返回 200；innovation 抽样全是
  iOS 升级指南/电影流媒体/拼字游戏答案，零财经内容，没接；business 抽样
  8 条里 2 条是真市场新闻（Lucid Motors 涨 20%），其余是体育/娱乐挂着
  "Business"分类——如实评估：这是 Forbes 免费 RSS 能拿到的最干净选项，
  噪音比例明显偏高，仍然接入（噪音走既有 D 档过滤路径，不会露出到首页）。
- **Bloomberg**：同样此前没有专用信源。`feeds.bloomberg.com` 会 301 跳转，
  跟进后 4 个频道（markets/economics/technology/politics）全部 200、内容
  干净，直接接入。
- **dxFeed**：产能验证有效，15 条events落库（A/B/C/D 各档都有）。当前未消费
  积压 69 条全部是 priority=4（个股）——查过 matched_symbols 全是 AAPL/MSFT/
  TSLA 这类个股代码，没有 SPX/QQQ 等大盘代码，**这是当前这批新闻本身的内容
  分布，不是代码 bug**（resolve_priority 对大盘/ETF symbol 的判断逻辑本身
  是对的，实测过）。

顺带发现一处真实的信源覆盖测量方法坑：探测 FT 首页 RSS 时 `grep -c "<item>"`
报告"只有 1 条"，一度以为这个 feed 没用——后来发现 FT 的 RSS 是压缩成单行的
XML，`grep -c` 按行数而非匹配次数计数，单行 feed 天然只会数出 1。改用
`grep -o | wc -l` 重新量出 11 条真实财经新闻（"Chip stocks tumble as AI
sell-off deepens"等），才发现是测量方法错了，不是信源本身没用。

## B. 补充信源 + 优先级命名对齐

新增 7 个 RSS 源（`crawler/sources.py`）：Bloomberg×4（markets/economics/
technology/politics）、Forbes-Business、WSJ-Markets、FT-Home，全部实测
200 + 内容干净，直接进现有的 `RSS_SOURCES_GLOBAL_MARKETS` 抓取循环，零额外
接线。

部署前发现一个真实的命名不匹配：`crawler/staging.py` 的 P0 优先级白名单里
写的是 `"Bloomberg"`（旧的、来自 web_search 归因的名字），新接的 RSS 源却叫
`"Bloomberg-Markets"` 等——不改的话这批新源会静默落到默认 P3，跟"插队优先
处理"的需求正好相反。这是本项目这一周反复出现的同一类问题（新老命名对不上，
不报错，只是静默不生效），这次是部署前用 `resolve_priority()` 直接跑一遍
新源名字发现的，不是上线后才查出来。已把 7 个新源名字全部加进 P0 白名单。

信源质量优先级审查：BinanceSquare 已完全禁用+清空（不只是降到 P4）；P3
"其他"档是 web_search 的长尾归因名（BBC/Politico 等一次性出现，也有大量
地方小报/聚合站），这是搜索召回本身的性质——**不打算为每个偶然出现的域名
单独硬编码优先级**，真正想稳定拿到高权威内容的正确做法是接专用 RSS（如本次
新增的 5 家），不是猜测性地给搜索结果里的域名分层。

## C. 生产环境反转加成从未生效——只在策略实验室推演里生效过

审查代码时发现：`api/lab_tools.py`（策略实验室）早就用上了拆分后的
`market_mood.mood_multiplier()`（同向+反转两个独立因子），但**生产环境
真正给用户看的 `/api/news`（api/server.py）一直调的是更早的
`mood_alignment_multiplier()`——那是拆分之前的旧单一同向倍率，压根不包含
反转逻辑**。等于 PRD-03 的一个核心交付物（"反转信号boost因子，专门把与大盘
反向的重大事件顶上来，防止回音室"）从写完的那天起就只在实验室的推演里生效，
从未真正影响过用户在主站看到的排序。这也是"用户看不出哪条被反转命中"的根源
之一——主站 API 从来没算过、没吐出过这个信息，前端自然无从展示。

修复：`/api/news` 改调 `mood_multiplier()`，给每条事件附加 `bonus` 字段
（`sentiment_align`/`reversal`/`total_bonus`/`multiplier`）。按时间排序的
分支不重排（那种场景看的是"最新发生了什么"，加成没有意义），但字段形状仍
保持一致（补一个全零的 bonus），不让前端因为排序方式不同就要处理两种
schema。实测部署后前 100 条命中 14 条反转、全部落在 A/S 档，符合硬约束设计。

## D. 榜单标签 + 筛选器（web/index.html）

- **tab02（真实数据展示）**：表格视图标题行、App 模拟器卡片都加上
  ⚡反转/☾同向 标签（互斥，最多显示一个）；筛选面板新增"情绪加成 Bonus"
  下拉（不限/仅同向/仅反转/有加成不限类型）。这个筛选是**客户端过滤**，
  跟已有的"标题关键词"筛选同一个模式——`bonus` 字段已经随 `/api/news`
  响应一起拿到手了，不需要为了筛这一个维度再发一次请求。
- **tab05（策略实验室）**：把此前笼统的"加成 +X%"标签拆成两个具名标签
  （之前这个通用标签正是用户反馈的问题所在："我都不知道哪条是反转，得一条
  条肉眼看"）。

顺带修掉策略实验室公式展示区的另一处过时文案：Score 公式只写了 M/T/H/A/Q
五项（标签已经写着"七因子加权"，公式本身却没跟上），补上 B（广度）和
I（冲击力）两项。

## 验证

- QA 门禁全程保持 102/102（每一步改动后都重跑，没有攒到最后一起测）
- `/api/news` 实测返回 `bonus` 字段，前 100 条 14 条反转命中、全部 A/S 档
- 浏览器实测：tab02 选"仅反转"→9 条结果、每条都带 ⚡反转 标签；tab05 默认
  Top20 里 17 条带标签（1 反转 + 16 同向），因子公式展示区已更新为七项
- 新增 7 个信源全部实测 200 + 内容抽样确认相关、优先级解析为 P0

---

# 2026-07-29 · WSJ死源修复 + 放宽头部资产新闻定义 + 30分钟高优抓取 + M/A/Q刷新漏洞

## A. WSJ-Markets 是个死 feed——同一天第三次"验证方法不够"的教训

召回校验时把 `feeds.a.dj.com/rss/RSSMarketsMain.xml` 判定为"内容干净、值得接入"，
依据是"能打开、标题像真新闻"。部署后实测**这个 feed 从 2025-01-27 起没更新过**
（channel 级 `lastBuildDate` 冻结在那天），"DeepSeek 引发抛售"这类标题是真实
发生过的旧新闻，不是抓错——事件时间闸每次都正确拦截，召回率因此恒为 0。

和 FT 那次"grep -c 数错行数"是同一类教训：**只验证"内容像不像新闻"不够，
必须验证"这个 feed 是否还在更新"**（看 lastBuildDate 或首条 pubDate）。已经
按同一域名模式换成 `feeds.content.dowjones.io/public/rss/RSSMarketsMain`
（道琼斯官方内容平台真实域名，MarketWatch 那条本来就在这个域名下），实测
最新条目是几小时前，61 条待处理，P0 优先级确认生效。

## B. 头部资产新闻定义放宽（Cramer 类内容不再一律 C/D）

Lawrence 原话："Cramer 个股推荐/盘中异动汇总类，这些我们也要抓，放宽对新闻的
定义（针对头部媒体、主流资产标的时，比如apple）。个股也可以是新闻"。

`crawler/pipeline.py` 的 SYSTEM_PROMPT 里"single-stock news / analyst notes"
被硬编码在 C/D 档——这条规则本身对大多数场景是对的（挡掉小盘股分析师噪音），
但对一小撮头部标的（Apple/Nvidia/Microsoft/Amazon/Google/Meta/Tesla/Broadcom
及各市场自己的国民级龙头）由头部媒体报道时，"个股"不等于"低价值"。

加了一条范围很窄的例外：头部标的 + 头部媒体（CNBC/Bloomberg/WSJ/FT/Reuters/
MarketWatch/Nikkei/SCMP）才适用，且区分"真有具体事实"（估值里程碑、带具体
涨跌幅的异动）该给 B，"没有新事实的常规看多看空"仍然是 C——不是无差别放行。
实测验证：Nvidia 涨 6% 的异动写作 → B/0.52；Cramer"买入苹果、看好财报"这种
无新信息的常规喊多 → C/0.18（符合设计，不是失败）；无关小盘生物科技分析师
报告 → 仍然 D/0.08（例外没有被滥用波及）。

## C. 头部财经媒体抓取提到 30 分钟一次

之前的理解有误：以为主 pipeline（cron 0点整）和 stage_fetch.py（cron 30分）
两个 cron 组合起来已经是 30 分钟一次的抓取节奏。实际查证：**主 pipeline 从
2026-07-26 起就只消费 staging、不再自己抓取**（架构文档写得很清楚，是我没
重新验证就假设了旧行为）。真实抓取节奏是 stage_fetch.py 单独决定的，每小时
一次，不是 30 分钟。

新增 `crawler/main.py:fetch_global_markets_sources()`（只抓 CNBC/Bloomberg×4/
Forbes/WSJ/FT 等 15 个头部频道）+ `scripts/stage_fetch_priority.py`，配
`15,45 * * * *` 独立 cron，跟原有的 `stage_fetch.py`（全量源，仍每小时）并存。
只提速头部媒体，不把长尾加密自媒体也跟着提到 30 分钟——那些源不需要这么高
时效，提速只会增加 staging 表体积和后续处理压力，没有对应收益。

## D. 打分口径一致性护栏当天第三次抓到真实回归——`score_market_impact`/
`score_quality` 从未出现在 UPDATE 子句里

护栏部署当天已经抓过一次（`COALESCE` vs `VALUES` 不一致，121 行）。这次
手动触发一轮生产 pipeline 处理积压后，护栏**再次**抓到 19 行不吻合——查证
发现 `score_market_impact` 和 `score_quality` 这两列**压根没在 ON DUPLICATE
KEY UPDATE 子句里出现过**，跨轮归并命中的行，`importance_score` 用本轮新算
的 M/A/Q 刷新，这两列本身却停在首次入库时的旧值，同一行内部对不上。

这是同一天同一类 bug 的第三次变体（breadth 漏刷新 → COALESCE 语义反了 →
现在是 M/Q 干脆没写进子句）。补上后把规则写成结构性的、不再逐列判断：
**任何进 compute_macro_score 公式的列，都必须在 UPDATE 子句里用 VALUES
刷新，没有例外**。七个基础因子列现在全部确认在场（M/B/T/I/H/A/Q）。

## 验证

- QA 门禁 102/102（含新增的 M/A/Q 修复后重跑 rescore_factors.py 校准）
- WSJ-Markets 实测 61 条新条目，全部 2026-07 日期、P0 优先级
- 三个新分类测试用例（Apple异动/Cramer常规喊多/无关小盘）分类结果符合预期
- 手动触发生产 pipeline 清理 P0 积压（513 条待处理 → 持续消化中）

---

# 2026-07-29 · 系统评测报告

召回覆盖率、各信源 S/A/B/C/D 贡献率、画风感受、七因子在真实事件上的感知、
首屏热门感——用当场实测数据写成的一份自评报告，不是功能测试的替代，是更
主观的产品体检。存档：`docs/reports/2026-07-29-system-evaluation.html`。

要点：
- CNBC 45% / Bloomberg 35% / Forbes 8%（如实报告：这个信源本身噪音就大）/
  FT 36%，苹果 5 万亿市值一条被三家独立信源交叉验证命中
- dxFeed 累计 110 条→15 条独立事件（13.6%），10 条 B 档以上，结论"有用"
- 经济政策/社会信号 S+A 占比（12.2%/10.2%）明显高于加密/美股（3.4%/1.0%），
  符合"能进库本身就要求市场传导路径"的设计预期
- 因子案例拆解发现的真实限制：H 热度因子对"重大但信源少"的事件会给出反直觉
  的低分（本例 0.10）——这是"已被关注"和"应有重要性"两个维度的必然落差，
  建议靠产品文案解释而非改公式讨好直觉
- 同一天早些时候发现的 FT 芯片股抛售案例在报告里给出了具体量化解释：
  单信源 B/0.474 vs 9信源合并 A/0.680，去重粒度的固有张力，非分类错误

另外：手动触发的加速处理批次运行期间部署了 storage.py 的 M/A/Q 修复，该批次
进程仍用旧代码写完了 444 条（201 条归并），QA 门禁因此又抓到 39 行不吻合——
确认是同一个已修复 bug 在一个"修复前就已启动"的进程里的残留效应，非新问题。
重跑 rescore_factors.py 校准，QA 回到 102/102。cron 触发的进程每次都是全新
启动，不会重现这个时序问题。

---

# 2026-07-29 · 更正评测报告的召回率数字（方法错误，非系统问题）

用户追问"CNBC 45%、FT 36%，剩余的一半为什么没有召回到"，倒查发现第一版
报告的召回率本身是错的。

根因：原始核对用中文关键词反查库内记录（比如搜"谷歌%""亚马逊%"），但 LLM
会把英文标题意译，"Amazon, Meta and Microsoft face skeptical investors"
被写成"AI支出挤压科技巨头现金流"——字面不含任何公司名，关键词搜索系统性
漏判。改成按原文 URL（sources 字段本身存的原文链接）逐条精确回查后：

- **CNBC 真实值 70%（14/20）**，不是 45%。剩下 6 条经查*完全没有进过*
  `raw_items_staging`——不是分类问题，是 CNBC 首页滚动快、RSS 窗口只留最近
  30-50 条，小时级轮询会在窗口更新间隙漏掉部分内容（同一天已经动手在改的
  "滚屏丢失"问题，见本日早些时候新增的 stage_fetch_priority.py）。
- **FT 真实值接近 100%**（9/9 复核项全部命中），不是 36%。此前判定"未命中"
  的几条（Nvidia 500亿数据中心项目、UAE-伊朗关系）其实都在库里，只是打了
  较低的 tier（D/C），之前的关键词搜索方法没搜到。另外 2 条是几分钟前刚
  抓到、还没排到 LLM 处理，是队列延迟不是漏召。

已更正 `docs/reports/2026-07-29-system-evaluation.html` 里的数字和方法说明，
并新增一张"CNBC 剩下 6 条为什么没进来"的明细表——逐条说明是抓取层丢失，
不是分类层丢失。Bloomberg 的 35% 当时用的也是同一套（有问题的）关键词法，
报告里加了说明：真实值大概率同样被低估，但未重新核实，如实标注"未复核"
而不是继续沿用一个已知不可靠的数字。

---

# 2026-07-29 · 聚合器伪造时间导致的旧闻事故 + 信源时间可信度硬闸

## 事故

用户截图发现：一条 **6月27日** 的旧闻（"特朗普威胁就数字税征100%关税"）以
**A 档、日期 2026-07-28** 的身份在前端展示，整整差一个月。

## 根因（两道防线同时失效，不是参数没调好）

1. 条目来自 Google News RSS（`type='web_search'`），聚合器给的 `published_at`
   是 **2026-07-28T12:54:11**——那是它重新分发这条旧文的时间。原文实测是
   6/26-27（新华网/21财经/东方财富三家 URL 里都带 `20260627`）。
2. `filter_by_freshness`（LLM 前）读的就是这个假时间戳，顺利放行。
3. `filter_by_event_date`（LLM 后）本来就是**专门为"信源时间戳骗人"设计的
   兜底闸**——它查 LLM 从正文读出的真实 event_date。但这条的 summary 是
   `"特朗普威胁：若欧洲国家…征收100%关税&nbsp;&nbsp;财联社"`，即标题复读
   加来源名，**一个字正文都没有**。LLM 无从提取，event_date 只能回落成那个
   假的 published_at，于是这道闸对着一个假日期做校验、必然放行。

**关键认知：为防聚合器撒谎而建的闸，对聚合器条目结构上永远失效**——它需要
正文，而聚合器恰恰不给正文。防线建错了层。

实测普遍性：近 3 天 2870 条 web_search 条目里 **2640 条（92%）无正文**；
平均摘要 90 字符，直连 RSS 是 193 字符。

## 同一批清理里抓到的第二种失败模式

`98b51d65ae716cc6` **S 档**"韩股据报暴跌33%"（凤凰财经经 Google News）——
搜索核实当天 KOSPI 实际收跌 **10.84%**，那个 33% 多半是把"7月累计跌幅近30%"
当成了单日崩盘。同一个根因：只有标题没有正文，LLM 把有歧义的数字读错。
**S 档事实错误挂在首屏**，比日期错更伤。

## 修复

**`crawler/source_trust.py`（新增）** —— 把"媒体权威度"和"时间可信度"这两件
被长期混为一谈的事分开：财联社经 Google News 分发仍然是不可信时间，因为
我们拿到的时间戳已经不是财联社声明的那个了。判定 `should_drop_untrusted`
= 聚合器来源 **且** 无正文，放在 **LLM 之前**（纯字符串操作，不需要模型
理解，早丢早省钱）。

实测判别力（近12小时 3847 条 staging）：丢弃 1353 条（35%），**全部是
web_search 类型，RSS/爬虫零误杀**；同时 **119 条有真实正文的 web_search
被正确保留**——不是无差别封杀搜索源。顺带每 12 小时省 1353 次 LLM 调用。

**新鲜度窗口 7 天 → 5 天**（crawler 与 api/server.py 两侧同步改，避免
"库里按5天清过、接口还按7天放行"的口径错位）。

**存量清理** `scripts/purge_untrusted_stale.py`：删掉"单一信源 且 全部信源
都来自聚合器"的事件，30 天回溯命中 **742 条**（S 5 / A 44 / B 130 / C 161
/ D 402），已全部删除并备份进 `purged_stale_20260729`。

## 为什么敢连 S/A 档一起删——实测验证过自纠正

删之前验证了"重要新闻会被可信信源冗余覆盖"这个假设：那条造假的"韩股暴跌
33%"（单信源）旁边就躺着 `KOSPI跌超8%触发熔断`（**91 个信源**、S 档、准确）
和 `全球市场转跌，韩股暴跌超10%`（3 信源、与实际 10.84% 吻合）。**删掉聚合器
孤证，一条真新闻都没丢**，正确版本本来就在库里而且信源多得多。

## QA 红线（新增 2 条，104 项全绿）

- 库内无「聚合器孤证」事件
- /api/news 默认窗口已收紧到 5 天

写这条断言时自己踩了一次坑并当场修掉：第一版写成
`JSON_SEARCH(sources,'one','web_search')`（任一信源是聚合器）立刻误报 3 条——
它们是同一篇文章被直连 RSS/爬虫和 Google News 各收了一次（PANews 爬虫版 +
PANews 搜索版），直连那份带着可信时间戳，正是要保留的。口径必须是「**全部**
信源都是聚合器」，且 JSON_SEARCH 必须用 `'$[*].type'` 限定只查 type 字段——
不限定的话 Google News 的 url 里带 `/rss/articles/`，会被误匹配成 rss 类型。

## 留给后续的一个缺口（如实记录）

上一轮更正召回率时用的"按原文 URL 逐条精确回查"方法，**没有固化进代码**，
仍然是临时 SQL。它不好自动化成 QA 用例（需要预存"应该抓到什么"的期望集），
所以记录在这里作为**人工召回审计的标准动作**：核对召回率必须用 URL 锚点，
不能用译文关键词——见 docs/reports/2026-07-29-system-evaluation.html 的
更正说明。
