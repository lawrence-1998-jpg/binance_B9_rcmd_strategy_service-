import pkg from 'playwright'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0

/**
 * 「有新版本」那一条自己的对比度和触控。
 *
 * 单独量是因为它平时不出现，跑不进常规的全屏扫描——而上一次栽跟头
 * 就是这种「截图看着好，量出来 1.5:1」的东西。里面那句小字还带着
 * opacity: .72，透明度是会吃掉对比度的
 */
const b = await chromium.launch()
for (const scheme of ['light', 'dark']) {
  const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], colorScheme: scheme })
  const pg = await ctx.newPage()
  await pg.goto(URL, { waitUntil: 'load' })
  // 把那一条按真实结构塞进去（组件平时不渲染）
  await pg.evaluate(() => {
    const el = document.createElement('button')
    el.className = 'update-pill'
    el.innerHTML = '<span class="update-t">有新版本</span><span class="update-a">点一下换过来</span>'
    document.body.appendChild(el)
  })
  await pg.waitForTimeout(300)
  const r = await pg.evaluate(() => {
    const lum = (c) => {
      const [r, g, b] = c.match(/[\d.]+/g).slice(0, 3).map(Number).map((v) => {
        v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
      })
      return 0.2126 * r + 0.7152 * g + 0.0722 * b
    }
    const mix = (fg, bg, a) => fg.match(/[\d.]+/g).slice(0, 3).map((v, i) =>
      Number(v) * a + Number(bg.match(/[\d.]+/g)[i]) * (1 - a))
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05) }
    const pill = document.querySelector('.update-pill')
    const bg = getComputedStyle(pill).backgroundColor
    const out = {}
    for (const cls of ['update-t', 'update-a']) {
      const s = getComputedStyle(pill.querySelector('.' + cls))
      const eff = `rgb(${mix(s.color, bg, Number(s.opacity)).join(',')})`
      out[cls] = { ratio: +ratio(eff, bg).toFixed(2), size: s.fontSize, weight: s.fontWeight }
    }
    const box = pill.getBoundingClientRect()
    out.box = { w: Math.round(box.width), h: Math.round(box.height) }
    out.bg = bg
    return out
  })
  console.log(`${scheme}:`, JSON.stringify(r))
  // 小字 13px 不算大字号，按 4.5:1 要求
  t(`${scheme} 「有新版本」对比度 ≥ 4.5`, r['update-t'].ratio >= 4.5, String(r['update-t'].ratio))
  t(`${scheme} 「点一下换过来」对比度 ≥ 4.5`, r['update-a'].ratio >= 4.5, String(r['update-a'].ratio))
  t(`${scheme} 高度 ≥ 44`, r.box.h >= 44, String(r.box.h))
  await ctx.close()
}
await b.close()
process.exit(fail ? 1 : 0)
