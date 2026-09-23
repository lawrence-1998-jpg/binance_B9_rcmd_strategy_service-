# 随手拾

**随手复制的信息，贴进来就被整理成一张卡片 —— 收着、找得到、随时复制出去用。**

聊天里的会议时间、名片、报价、链接、报错、一段想法……粘贴即收下。
Claude 读懂它，拆成：标题、一句话要点、字段（时间 / 地点 / 电话 / 金额…）、要做的事，
再替你想好「下一步拿去问 AI 的那一句」。

## 在哪用

**claude.ai 里（推荐）**：以 Artifact 的形式发布在你自己的账号里。能用 Claude 整理，
数据存在你那一格，只有你本人看得到；手机、电脑打开同一个链接，是同一份。

**GitHub Pages / 离线单文件**：没有 Claude 时也能用 —— 本地认出链接、电话、邮箱、金额、时间，
数据存在这台设备的浏览器里。

```
https://lawrence-1998-jpg.github.io/binance_B9_rcmd_strategy_service-/
web/desk/deskside-standalone.html   （双击即用）
```

## 怎么用

| 想做的 | 怎么做 |
|---|---|
| 收 | 长按收件框粘贴 ／ 电脑上在页面任何地方 ⌘V ／ 打字后点「收下」 |
| 复制一格 | 点字段那一行（或卡片上的字段小条）—— 只复制那个值 |
| 复制整张 | 右上角复制按钮 = 整理版；展开后「复制整理版 / 复制给 AI / 复制原文」 |
| 拿去问 AI | 「复制给 AI」= Claude 想好的那句指令 + 整理好的信息 + 原文，贴进哪家 AI 都能直接用 |
| 合成一段 | 「选择」→ 勾几张 → 复制整理版 ／ 复制给 AI |
| 找 | 按类型筛（日程、联系人、数据…）／ 🔍 搜标题、原文、字段 |
| 反悔 | 删了能撤销；同一段贴两次不会收两条 |

## 隐私

- 在 claude.ai 里：每一笔都写在 `data/users/<你的 id>/` 下 —— 平台保证这一格连 artifact 的
  主人、被分享的人都读不到。整理用的是你自己账号的 Claude，第一次会问你同不同意。
- 在别处：存在浏览器里，不上传。
- 页面不发任何第三方请求（没有埋点、没有外链字体）。`test/private.mjs` 把这些变成了会失败的检查。

---

## 开发

```bash
cd desk
npm install
npm run dev        # 本地开发（没有 Claude，走本地整理）
npm test           # 构建 + 起服务 + 跑全套（claude.ai 那条路用 test/mock-claude.js 模拟）
```

改完源码要重新生成离线单文件版并一起提交（CI 会逐字节比对）：

```bash
npx vite build --config vite.config.single.ts && node scripts-postbuild-single.mjs
```

`dist-single/artifact.html` 是发布到 claude.ai 的那一份（去掉了 doctype/head 外壳），
声明的能力：`sample`（Claude 整理）、`db`（存储）、`user`（找到你自己那一格）。

## 目录

```
src/
  App.tsx          整个页面：收件框、筛选、卡片列表、多选
  examples.ts      库还空着时的三张示例卡
  lib/card.ts      纯逻辑：本地认字段、给 Claude 的指令、核 Claude 的回复、复制出去的样子
  lib/store.ts     存在哪：claude.ai 的数据库（她自己那一格）或浏览器
  lib/copy.ts      写剪贴板（带 execCommand 兜底）
  lib/update.ts    GitHub Pages 装成 App 时，新版本怎么到手上（在 claude.ai 里不启用）
  styles/app.css   全部样式；颜色只在 :root 里定义
test/              见 test/README.md
```

## 改动时别踩的线

- **复制必须在点击事件里同步发起。** iOS 只认用户手势里发起的剪贴板写入。
- **Claude 的回复不可全信**：一律过 `fromAi()`，缺的补、假的（「无」「未提及」）丢。
- **不许从循环或定时器里调 Claude**：只在收下一条、或她点「重新整理」时调；
  用不了（没同意 / 没开）就降级成本地整理，不反复弹同意框。
- **数据库同一条一次只写一笔**：`store.ts` 里按条目排队。
- 能点的不小于 44×44，输入框字号不小于 16px。`look.mjs` 盯着。
