# 案头 Deskside

一个人用的移动 + 桌面工作台。四条线：**咨询顾问 · 字节产品 · 我们俩 · 我自己**。

打开五秒内回答三件事：今天干什么、哪条线卡住了、有什么要记的。

---

## 装到 iPhone 主屏（推荐）

**首次要手动开一次 Pages**（只需一次，我做不到——Actions 的 token 没有创建 Pages
站点的权限）：仓库 **Settings → Pages → Build and deployment → Source** 选
**GitHub Actions**。开完重跑一次流水线，之后每次推送自动发布。

地址是：

```
https://lawrence-1998-jpg.github.io/binance_B9_rcmd_strategy_service-/
```

iPhone Safari 打开 → 分享 → **添加到主屏幕**。之后从主屏图标启动：
独立窗口、没有地址栏、有自己的图标，离线也能开（service worker 会缓存）。

部署由 `.github/workflows/deploy-desk.yml` 完成，改了 `desk/` 推上去就自动发布。

## 其它用法

> ⚠️ **数据存在浏览器本地，按「来源」隔离。**
> `file://` 打开的单文件、`localhost` 服务、手机 Safari，三者的数据**互不相通**。
> 选定一种用法就一直用它；要换，先在设置里导出 JSON，再到新的地方导入。

### 1. 桌面 · 最省事（推荐）

双击 `web/desk/deskside-standalone.html`。

这是一个自包含单文件，JS/CSS/图标全内联，**不需要任何服务器**。

> 注意：这个文件在**各类网页预览器里会显示空白**——那种预览通常用
> `sandbox="allow-scripts"` 的 iframe 嵌入，实测下来里面**任何内联脚本都不执行**
> （连一行 `postMessage` 都跑不了）。这不是文件的问题，把它下载下来用浏览器打开就正常。
想要 Dock 图标：把这个文件拖到 Dock（macOS），或在 Chrome 里
「⋮ → 投放、保存和共享 → 创建快捷方式」。

### 2. 桌面 · 真的 App 窗口

```bash
cd desk && ./run.sh          # 零依赖，只要有 python3
```

浏览器打开 http://localhost:5173 → Chrome 地址栏右侧的**安装**图标 → 装到桌面。
装完有独立窗口、独立图标，离线也能开（service worker 会缓存）。

### 3. 手机

把 `web/desk/` 部署到能访问的地址（现有 Flask 站点直接就能托管，
路径 `/desk/`，和 API 同源）。手机 Safari 打开 → 分享 → **添加到主屏幕**。

---

## 开发

```bash
cd desk
npm install
npm run dev        # 开发服务器
npm run build      # 构建 → dist/（多文件 + PWA）
npm run typecheck  # 只跑类型检查

# 单文件版（双击即用的那个）
npx vite build --config vite.config.single.ts   # → dist-single/index.html
```

发布到仓库（两种产物都要）：

```bash
npm run build && npx vite build --config vite.config.single.ts
rm -rf ../web/desk && mkdir -p ../web/desk
cp -r dist/. ../web/desk/
cp dist-single/index.html ../web/desk/deskside-standalone.html
```

## 依赖只有三个

`react` · `react-dom` · `vite`（加 `vite-plugin-pwa` / `vite-plugin-singlefile` 两个构建插件）。

**没有** UI 组件库、CSS-in-JS、图表库、日期库、图标库、路由库——
Organic 这套形态（药丸、大圆角、纸感）跟任何现成库都对不上，改库比自己写慢；
五个屏也不值得引一个路由，hash 路由三十行搞定，而且 `file://` 下能用。

## 目录

```
desk/
├─ run.sh                    本地起服务
├─ vite.config.ts            正常构建 + PWA
├─ vite.config.single.ts     单文件构建
├─ scripts-gen-icons.py      生成 PWA 图标（纯标准库，无依赖）
└─ src/
   ├─ styles/tokens.css      ← 改配色 / 字号 / 间距只改这里
   ├─ styles/base.css        组件样式
   ├─ lib/                   types · date · seed · store
   ├─ components/            ui · icons · TabBar
   └─ screens/               Today · Work · Life · Capture · Review · Settings · PromptTool
```

## 几条改动时别踩的线

- **配色只改 `tokens.css`**，组件里不许写死颜色。领域色（赤陶/雾蓝/梅陶）只用于
  3px 标识条、小圆点、chip，**绝不做卡片底色**——否则整屏变成四种颜色互相喊。
- **不要用 `backdrop-filter`。** 页面上有无限循环的脉动点，毛玻璃会让浏览器每帧
  重算，整页闪烁。顶栏和 tab bar 一律不透明纯色。
- **固定定位元素保留 `transform: translateZ(0)` + `contain: layout paint`**，
  否则部分机型滚动会撕裂。
- **状态不能只靠颜色。** 正常=实心圆、注意=空心环、阻塞=方块，截成灰度图仍要能分辨。
- **今日三件事的上限就是 3。** 这个摩擦是故意的，别为了「灵活」去掉它。

## 数据

全部存在浏览器 `localStorage`（键 `deskside.v1`），不上传任何地方，没有后端。

首次打开装的是**示例数据**（客户 A、推荐位改版这些），看懂每块放什么之后，
到「复盘 → 右上角齿轮 → 清空全部数据」换成你自己的。

同一个地方还能**导出 / 导入 JSON**。换设备、清缓存都会丢数据，**每周导出一次**。

导出做了三级降级（`src/lib/save.ts`）：托管环境走平台的下载能力 → 本地走普通 blob
下载 → 都不通就把 JSON 摊在页面上让你手动复制。**导出是数据安全的最后一道，
不允许静默失败。**

## Prompt 管理器

「工作」屏右上角。内置 15 条来自 `docs/playbook/lawrence-prompt-list.md`，
**构建期解析生成**（`scripts-build-prompts.mjs` → `src/data/prompts.json`），
改那份 md 再发布这里就跟着变，不存第二份。支持搜索、按分类筛、一键复制、
按复制次数排序、自己加条目（存 localStorage）。

里面还挂着「提纲 → Prompt」生成器。

## 照片与「我们俩」

照片本体存 **IndexedDB**（`src/lib/media.ts`），localStorage 只放 id 和文字说明——
localStorage 只有约 5MB 且只能存字符串，base64 还要再膨胀 33%，几张图就撑爆了。
存之前用 canvas 压到 1600px / JPEG 0.82，手机直出的 4MB 照片会降到几百 KB。

> ⚠️ **iOS Safari 会清掉「7 天没访问」的站点数据，但添加到主屏幕的 PWA 不在此列。**
> 这是「一定要添加到主屏幕」的实质理由，不只是为了好看。

另外两块：「今晚聊点什么」是一副 36 张的离线牌（`src/data/sparks.ts`），
「想对他说」是一条随手写的流。

## 自动日记与时间轴

「复盘」屏分两栏。**今天**那栏的三句话是从当天真实发生的事拼出来的草稿
（`src/lib/diary.ts`，纯函数，不调模型——这三句的价值在准确而不在文采，
写错比写得平淡糟糕得多），你可以直接改，改过就不再自动覆盖。
**时间轴**那栏按日期倒序列出过去每一天：三句话 + 完成数 + 四条线的时间分布条。

## 提纲 → Prompt

「工作」屏右上角那个魔杖图标。输入几条要问的问题，出一段能直接贴给
Claude Code / GPT 的调研 prompt。

生成是**纯本地模板拼装**（`src/lib/prompt.ts`），不联网、不调模型，飞行模式也能用。
模板里最要紧的一条是**「不许编数字」**——像「XX 的流量占比大概有多少」这类问题，
模型极容易一本正经给一个看起来很专业的假百分比，而你会拿着它去跟客户讲。
所以模板强制：没有公开来源就必须写「没有公开数据」，再给带推导过程的区间估算并标注「估算」。

另外三条约束：每段结论标 `[事实]`/`[推断]`/`[猜测]`；必须标时间（平台机制变得快）；
不许说「加强创作者激励」这种零信息量的话。

要改模板就改 `src/lib/prompt.ts`，它是个纯函数。

设计与实现说明：`docs/prd/deskside-mobile-workbench.html`。
