# 随手

**复制了什么，就贴进来 —— 拿走一段结构化的 AI Prompt。**

只干这一件事：聊天记录、邮件、文章、报错、会议纪要、一串问题、一个链接……
贴进来，它认出是什么、推荐拿去做什么（总结 / 帮我回 / 拆待办 / 排查 / 调研 / 翻译……），
拼好一段结构清楚的 Prompt，**贴进来的那一下就已经复制好了**，切到 ChatGPT / Claude / 豆包直接粘贴。

```
https://lawrence-1998-jpg.github.io/binance_B9_rcmd_strategy_service-/
```

iPhone：Safari 打开 → 分享 → **添加到主屏幕**。离线也能用。

---

## 怎么用

| 想做的 | 怎么做 |
|---|---|
| 贴进来 | 点「从剪贴板贴入」／ 长按输入框粘贴 ／ 电脑上在页面任何地方 ⌘V |
| 换个用途 | 点那一排按钮里的另一个 —— **点一下就是复制那一版** |
| 加一句要求 | 「补一句」：*给老板看的* ／ *婉拒但留余地* ／ *我不懂技术* |
| 复制 | 底部整条按钮 ／ 点 Prompt 卡片任意一处 ／ ⌘↵ ／ 数字键 1–9 选用途并复制 |
| 复制并打开 | 底部「ChatGPT · Claude · 豆包 · DeepSeek · Kimi」：先复制再打开（ChatGPT 和 Claude 直接预填） |
| 找回刚才那条 | 右上角「最近」—— 最近复制过的 30 条，同一段材料换个用途再问 |
| 反悔 | 换掉、清空、手改被覆盖、删记录，都有「撤销」 |

改了一个字，底部按钮就从「✓ 已复制」变回「复制新版本」—— 不会带着旧的那版去粘贴。

**两种格式**：「通用」是 Markdown 小标题（哪家 AI 都吃）；「Claude」是 XML 标签
（材料在前、指令在后，Claude 官方推荐的写法）。

**安卓**装到桌面之后，在任何 App 里点「分享 → 随手」就能直接丢进来。
**iOS 快捷指令**可以打开 `…/index.html?text=<内容>` 达到同样效果。

## 隐私

全部在这台设备上跑，**不调任何模型、不上传任何东西**。识别用的是规则，不是 AI ——
她贴进来的可能是客户的邮件，在她自己决定拿去问 AI 之前，一个字都不该离开手机。
`test/private.mjs` 把这条变成了会失败的检查。

## 离线单文件版

`web/desk/deskside-standalone.html`：一个自包含的 HTML，下载下来双击就能用，不需要服务器。
CI 会逐字节比对它跟源码是否一致，不一致就红（见 workflow 里「仓库里那份离线版不许过期」）。

---

## 开发

```bash
cd desk
npm install
npm run dev        # 本地开发
npm test           # 构建 + 起服务 + 跑全套
```

改完源码要重新生成离线版并一起提交：

```bash
npx vite build --config vite.config.single.ts && node scripts-postbuild-single.mjs
```

## 目录

```
src/
  App.tsx          整个页面
  Preview.tsx      Prompt 卡片（整张可点、长材料折叠、选中文字时不抢）
  examples.ts      空着时给的四个示例
  lib/shape.ts     脑子：认出是什么 → 推荐用途 → 拼 Prompt（纯函数）
  lib/store.ts     本机存储：正在弄的这条 + 最近 30 条 + 两个偏好
  lib/copy.ts      写剪贴板（带 execCommand 兜底）
  lib/update.ts    新版本怎么到手上（打开一次就换，用着时只浮一条）
  styles/app.css   全部样式；颜色只在 :root 里定义
test/              见 test/README.md
```

## 改动时别踩的线

- **复制必须在点击 / 粘贴事件里同步发起。** iOS 只认用户手势里发起的剪贴板写入，
  前面垫一个 `await` 就会被拒。`App.tsx` 里 `doCopy` 的注释写了。
- **改识别规则之前，先往 `test/samples.mjs` 加一条会被改坏的样本。**
  样本同时喂给单测和界面测试。
- 输入框字号不能小于 16px，否则 iPhone 聚焦时会把整页放大。`look.mjs` 盯着。
- 能点的东西不能小于 44×44。`look.mjs` 盯着。
