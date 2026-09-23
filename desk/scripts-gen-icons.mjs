/**
 * 生成 PWA 图标：墨色底 + 白色「随」字。跟页面左上角那个标一致。
 *
 * 用浏览器画字而不是手写像素：字形要用真的中文字体才好看。
 * 需要装了中文字体的机器（Noto Sans CJK 之类）；图标已经签进仓库，平时不用跑。
 *
 *   node scripts-gen-icons.mjs
 */
import pkg from 'playwright'
import { fileURLToPath } from 'node:url'
const { chromium } = pkg
const OUT = fileURLToPath(new URL('./public/icons/', import.meta.url))

const html = (size) => `<!doctype html><meta charset="utf-8"><style>
  html,body{margin:0;background:transparent}
  div{width:${size}px;height:${size}px;background:#1a1917;display:grid;place-items:center}
  span{color:#fff;font:700 ${Math.round(size * 0.5)}px/1 "Noto Sans CJK SC","PingFang SC","Source Han Sans SC",sans-serif;
       transform:translateY(-${Math.round(size * 0.02)}px)}
  i{position:absolute;width:${Math.round(size * 0.09)}px;height:${Math.round(size * 0.09)}px;border-radius:50%;
    background:#e8703a;left:${Math.round(size * 0.7)}px;top:${Math.round(size * 0.7)}px}
</style><div><span>随</span></div><i></i>`

const b = await chromium.launch()
const pg = await b.newPage({ deviceScaleFactor: 1 })
for (const [name, size] of [['icon-512.png', 512], ['icon-192.png', 192], ['apple-touch-icon.png', 180]]) {
  await pg.setViewportSize({ width: size, height: size })
  await pg.setContent(html(size))
  await pg.evaluate(() => document.fonts.ready)
  await pg.screenshot({ path: OUT + name, clip: { x: 0, y: 0, width: size, height: size } })
  console.log('ok', name)
}
await b.close()
