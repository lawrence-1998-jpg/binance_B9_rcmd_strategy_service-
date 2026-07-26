# Handoff: B9 推荐策略工作台（B9 Recommendation Strategy Hub）视觉/交互改版

给 Claude Code 的实施说明。改造对象是现有仓库
`lawrence-1998-jpg/binance_B9_rcmd_strategy_service-` 的 `web/index.html` 与 `web/lab.html`。

## 一、这份材料是什么

- `B9 Workbench.dc.html` 是**设计参考稿（HTML 高保真原型）**，不是可直接上线的生产代码。
  任务是在现有代码库（纯 HTML + 内联 CSS/JS，无构建）里**按现有技术形态重造这套设计**。
- 保真度：**hifi**。颜色、字号、间距、圆角、组件形态照稿实现；数据一律接回现有 API（原型里的数据是按线上字段结构造的样例）。
- 铁律（来自产品负责人）：**只改设计，不改逻辑**。showTab() 依赖的 data-tab / #panel-N、
  接口调用、所有功能按钮/表单必须保留；tab04 的 #panel-4 + --ev-* 作用域隔离保留。

## 二、信息架构变化（本次改版核心）

原：左侧 238px 固定侧边栏（两组 + 06）。
新：**顶部横向分组 tab 导航**，侧边栏整体移除，内容全宽。

顶栏两层：
1. **全局深色条 (52px, #2e2b25)**：左 = Logo（新 SVG 标记，见 assets 节）+ 「B9 Recommendation Strategy Hub」(Caprasimo 15px 米白) + 分隔线 + 「INTERNAL · READ & TUNE」小号 mono；右 = Pipeline 状态胶囊（脉动绿点，见性能红线）+ UTC 时间 (mono 11px) + 头像。
2. **tab 条（米白 #f9f4ed，底 1px 分隔线，padding 12px 22px 14px）**，三个分组，每组结构：
   - 组标题行：9px 圆角3px 色块（组1 赤陶 #c67139 / 组2 鼠尾草 #8fa073 / 组3 中性 #a19786）+ 13px/700 组名 + 10px mono 序号范围
   - 胶囊容器（bg #eee7db, radius 999, padding 4px），内放 tab 药丸按钮（h34, padding 0 18px, radius 999, 14px/600；序号 11px mono 60% 透明）
   - 分组：「新闻策略数据服务 01–03」(生成流程/数据展示/API 接入)、「策略产品工作台 04–05」(评测工具/策略实验室)、「其它 06–07」(历史数据/开发者资讯)
   - 选中态：bg 赤陶 #c67139 + 文字米白；hover：bg #f9f4ed
   - 右侧：搜索假输入框（⌘K 占位，radius 999）
3. **05 策略实验室并入同页 tab**（原 lab.html 独立跳转取消），内部两个子工具做同页子 tab。
4. 每个 tab 内容区顶部有**吸顶页内锚点条**（见交互节）。

## 三、设计 Token（Organic 设计系统，全部落到 CSS 变量）

建议抽到共享 `web/assets/app.css`（预留路径已存在），index/lab 双页引用，解决双份内联样式问题。

```css
:root {
  --paper:   #f5ead8;  /* 页面底色（替换原 --paper 取值） */
  --surface: #ebddc5;  /* 卡片底（.card） */
  --ink:     #201e1d;  /* 主文字 */
  --gold:    #c67139;  /* 强调（原 --gold 语义，改为赤陶） */
  --indigo:  #7a8a5e;  /* 次强调（原 --indigo 语义，改为鼠尾草） */
  --green:   #7a8a5e;  /* 正向/已核实 同鼠尾草系 */
  /* 中性阶梯 */
  --n100:#f9f4ed; --n200:#eee7db; --n300:#dcd3c4; --n400:#c0b6a5; --n500:#a19786;
  --n600:#82796a; --n700:#645c50; --n800:#474238; --n900:#2e2b25;
  /* 赤陶阶梯 */
  --a100:#fff2eb; --a200:#ffe1d0; --a300:#ffc6a5; --a400:#f6a06b; --a500:#d67f48;
  --a600:#b2622d; --a700:#8c491a; --a800:#643312; --a900:#402310;
  /* 鼠尾草阶梯 */
  --g100:#f0fae1; --g200:#e1eecc; --g300:#ccdbb2; --g400:#aebf92; --g500:#8fa073;
  --g600:#728157; --g700:#56633f; --g800:#3d472b; --g900:#272e1b;
  --radius-sm:8px; --radius-md:16px; --radius-lg:28px;  /* 按钮/输入/标签一律 999px 药丸 */
  --shadow-sm:0 1px 2px rgba(46,43,37,.14);
  --shadow-md:0 3px 10px rgba(46,43,37,.16);
  --shadow-lg:0 12px 32px rgba(46,43,37,.22);
}
```

字体：标题 **Caprasimo**（Google Fonts，仅拉丁字形；中文标题回退系统黑体，刻意如此）；
正文 **Figtree** + PingFang SC / Microsoft YaHei；数字/代码 ui-monospace 栈 + `font-variant-numeric: tabular-nums`。
正文 15px/1.55；页面 h1 30–34px；节 h2 24px；节眉（eyebrow）10px/600 大写 letter-spacing .18em 色 --a700。

组件形态：
- 卡片 .card：bg --surface，radius ~32px（--radius-lg×1.15），无边框，投影 --shadow-sm
- 按钮/输入/标签全部 radius 999px；主按钮 bg --gold 文字 --paper，hover --a600
- 标签 .tag：11px，padding 3px 10px；accent 用 a100/a800，accent-2 用 g100/g800（板块标签），币种标签 a200/a800，中性 n200/n700
- Tier 徽章（S/A/B/C/D，21×21 radius 6 mono 11px/700 + inset 1px 描边）：
  S a200/a900/a400 · A a100/a800/a300 · B g100/g800/g300 · C n200/n700/n400 · D n100/n500/n300
- 校验状态色：VERIFIED --g700 · PROBABLE --a700 · UNVERIFIED --n600 · DISPUTED --a800；谣言标签 bg --a800 文字米白
- 焦点态 :focus-visible { outline:2px solid var(--gold); outline-offset:2px }，不留浏览器默认蓝框
- 深色码块 bg #2e2b25，代码字色 #e1eecc，注释/头部 rgba(245,234,216,.45)

## 四、逐 Tab 说明（信息结构 = 线上现状，不得增删；下面只列视觉/交互差异与新增）

### 01 生成流程
结构照线上 panel-1：hero → 指标 4 卡 → 流程图 → 八步流水线 → 打分模型 → 去重与校验 → 运行记录。
改动：
- hero kicker 改为鼠尾草胶囊（脉动点）；h1 重点短语用 --a700。
- **新增：最近调度监控横条**（卡片，单行：脉动点 + 「最近调度」+ mono 结果 + 分段状态点 + 「下轮 UTC 12:00」+ 展开箭头；点击展开近三轮列表 + 日志入口）。数据来自 /api/runs。
- **流程图 SVG 重绘**（几何沿用线上，配色映射：币安金→赤陶、靛蓝→鼠尾草、绿色→鼠尾草浅阶、红色高亮→--a700）：
  - 顶部列标题升级为**深色步骤胶囊条** 01→05（rect h30 rx15 #2e2b25，序号 --a400 mono，标题 13px/700 米白，右侧汇总耗时 mono 9.5px 半透明；03 的耗时用 #ffc6a5 高亮），胶囊间箭头串联。
  - **删除所有节点级微观耗时标注**（<1秒/≈2秒等），耗时只留在步骤胶囊上。
  - 分支 2 改为与分支 1 同款标签框（鼠尾草 tint），其下排序分节点（h90），节点内底部加虚线小签「＋ Rel 相关性 · 选板块后并入」。
  - 分支曲线统一为对称平滑贝塞尔：fork(900,260) → 上 C934 曲线入分支1 → L 入 API 框；下 C934 曲线入排序分左缘；排序分右缘 → C 曲线上行入 API 框底部。箭头 marker 三角 7px。
- 板块标签 20 个、信源 Top8 条形、部署 kv 三卡并排（Operations 节）。

### 02 数据展示
- 视图切换（表格/App 模拟器）做成右上分段药丸；筛选区 = 卡片内 6 列 grid 的假输入药丸（实现时换回真实 input/select，样式照药丸）。
- 表格列：# / 重要性(Tier 徽章+分数+进度条) / 事件标题(中文+标记 tag+英文) / 板块-币种 / 信源 / 观测时间 / 展开箭头。行 hover bg --n200。
- 行展开详情双栏：左（短摘要加粗 14px / 长摘要 / 英文标题 / 谣言警示框 a100+a300 / 原文信源+权威 x/5）；右（五因子 M·T·H·A·Q 细条 + 综合分高亮行 / 真实性校验 / 元数据 kv / X 原贴卡）。
- App 模拟器：手机壳 340px 圆角 44 深色边框，内部 Sector/Macro Insight 子 tab（下划线 2px --gold）、条目「标题 2 行 + 信源·日期」，右侧三张说明卡（文案照线上）。

### 03 API 接入
结构照线上 panel-3：开发者联系横幅(a100 卡 + ! 圆徽) → Base URL/双鉴权 + 在本页测试(secret 输入) 双卡 → 7 端点清单(参数表 + urlbox + 复制/浏览器打开/试一下 + 深色响应区) → 字段格式表(分组行用 g100 底) → 案例数据 → cURL/Python/JS 接入示例 → 注意事项双卡。
「试一下」逻辑不变（真实 fetch），仅响应区改深色码块样式。

### 04 评测工具
子 tab 吸顶。三个子工具的输入/结果结构照线上：判重(截图上传→提取→跨图重复组)、LLM 评测室(3 输入方式 + 5 persona 卡 + Momentum/Novelty)、AB 对比(A/B 组三模式填充 + 重合度/GSB 表/规则总结)。「保存结果」条样式统一为药丸输入 + 次按钮。
persona 结果卡：5 列 grid，头像圆徽 26px（各自阶梯色）、分数 Caprasimo 26px、判定 tag、评语 11.5px。

### 05 策略实验室（并入主站 —— 新增集成点）
- 原 lab.html 整页并入 tab05；hero + 公式条 + 全局设置条（板块/时间范围/候选池/TopN/池大小 pill）+ 两个子 tab 吸顶。
- 权重面板：预设按钮组（生产默认/时效优先/权威优先/热度优先）+ 5 滑块（accent-color: --gold）+ **归一化堆叠条**（5 段：a500/a400/a300/g600/g400）+ 归一化提示。
- Top N 结果行：rank mono / 标题双语 / 新分 / 位次变化 tag（升 g200/g800、降 a200/a800、持平 n200/n600）。
- 两版本对比：A/B 双面板（A 点鼠尾草、B 点赤陶）→ 居中主按钮 → 换手率/升降卡 + 对比表 + 规则总结（g100 提示框）。
- 若保持 lab.html 独立文件实现，至少共享 app.css 与顶部导航，保证视觉无缝。

### 06 历史数据
筛选卡（工具类型/每页条数/刷新 + 右侧快捷筛选 tag 组，选中 bg --gold）→ 记录表（时间 mono/工具 tag/备注/成本/删除）→ 行点击展开 payload JSON 深色码块 → Usage 条形统计卡。

### 07 开发者资讯（**全新模块**）
- 归入「其它 06–07」组。面向接入方的变更公告流。
- 左：公告列表卡（每行：日期 mono 12px / 类型 tag（发布=g、API 变更=a、维护=n）/ 标题 13.5px 加粗 + 摘要 12.5px）。
- 右：「订阅与联系」卡 +「兼容性承诺」卡（v1 只加字段不删改；破坏性变更提前 30 天公告）。
- 数据可先静态维护（数组/JSON），后续可接 /api/history 同款存储。

## 五、交互与状态

- tab 切换：沿用 showTab()；切换后内容区 scrollTop 归零。
- **吸顶页内锚点条（新增，每个长 tab 都要）**：内容滚动容器顶部 position:sticky; top:0; z-index:6；外层 bg --paper 垫底（防止透出），内层药丸组（bg --n100 + 1px 分隔线色 + shadow-sm）。点击滚动到节锚点（目标位 - 72px 偏移）。⚠ 本环境 scrollTo({behavior:'smooth'}) 不可靠，**直接赋值 scrollTop**（或容器 CSS scroll-behavior:smooth）。
  各 tab 锚点：01 概览/流程图/八步流水线/打分模型/去重与校验/运行记录 · 02 视图/筛选/列表 · 03 鉴权/端点/字段表/案例/示例/注意事项 · 06 筛选/记录/统计；04/05 用吸顶子工具切换条代替。
- 行展开（02 表格、06 历史）：同一时刻只开一行，再点收起；展开行 bg --n200。
- 滑块 onChange 实时重排；权重自动归一化显示。
- 状态灯脉动动画 keyframes：0/100% opacity 1 scale 1；50% opacity .45 scale .82；1.8s ease-in-out infinite。

## 六、性能红线与工程注意点（务必遵守）

1. **禁止 backdrop-filter**，至少禁止用在包含无限动画（脉动灯/loading/跑马灯）的容器上 —— 曾导致整页每帧重算高斯模糊闪烁。本设计所有吸顶条/顶栏都用**不透明纯色**，请保持。
2. 若保留任何 fixed 定位元素，保留 `transform:translateZ(0)` + `contain:layout paint` 合成层提升（原侧边栏的经验，防滚动撕裂）。
3. tab04 的 `--ev-*` 变量与 `#panel-4` 前缀选择器**保留隔离**，只把取值统一到上面的 token（如 --ev-gold → var(--gold)）。
4. 抽取共享 `web/assets/app.css`：token、卡片、按钮、tag、tier 徽章、表格、tab 导航、吸顶锚点条；index.html 与 lab.html 都引用。文案与交互逻辑不动。
5. SVG 流程图文字类名（原型里 .b9f-*）随图迁移；SVG 内颜色全部走 var()。
6. 中文字体不做 webfont，用系统栈；Caprasimo/Figtree 用 Google Fonts，加 `display=swap`。
7. 回归清单：每个 tab 正常切换；02 筛选改动触发重新请求；03 每个端点「试一下」能出响应；04 三工具能提交；05 滑块实时重排、保存结果落 06；06 展开/删除正常；窄屏 ≤1080px 时 tab 条允许横向滚动（原汉堡抽屉可移除）。

## 七、Assets

- **Logo（新）**：26×26 内联 SVG —— 圆角 9 的赤陶方块 + 深色(#2e2b25)上升信号柱三根（第三根 45% 透明）+ 节点圆点 + 50% 透明折线。源码在设计稿顶栏处，直接拷贝。
- 图标若需要：Lucide（stroke-width 2.75）。
- 无位图资产。

## 八、文件清单

- `B9 Workbench.dc.html` —— 高保真设计稿源文件（本包内副本；在设计项目里可直接交互预览）。含全部 7 个 tab、吸顶锚点、流程图 SVG、示例数据。
- `organic-styles.css` —— 设计系统原始 token/组件样式表（上表 token 的出处，类名 .card/.tag/.btn 的参考实现）。
