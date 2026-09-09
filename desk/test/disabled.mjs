import pkg from 'playwright'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
/**
 * 主按钮「存下来」在输入框空着时是禁用的。
 * 要看的不是对比度（禁用控件豁免），是**她看不看得出来它按不动**。
 */
const b = await chromium.launch()
const scheme = process.argv[2] === 'dark' ? 'dark' : 'light'
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], colorScheme: scheme })
const pg = await ctx.newPage()
await pg.goto(URL + '#/today', { waitUntil: 'load' })
await pg.reload(); await pg.waitForTimeout(500)
// 先把「加到主屏幕」那条关掉，别挡着
const notice = pg.locator('.install button')
if (await notice.count()) { await notice.first().click(); await pg.waitForTimeout(300) }
await pg.locator('.cap').click(); await pg.waitForTimeout(600)

const read = async () => pg.evaluate(() => {
  const btns = [...document.querySelectorAll('.sheet .btn')]
  const b = btns.find((x) => x.disabled) ?? btns.find((x) => /存|定|加/.test(x.innerText)) ?? btns[0]
  if (!b) return null
  const cs = getComputedStyle(b)
  return { text: b.innerText.trim(), disabled: b.disabled, opacity: cs.opacity,
           bg: cs.backgroundColor, color: cs.color, border: cs.borderColor,
           events: cs.pointerEvents }
})

const off = await read()
console.log(`[${scheme}] 空着：  `, JSON.stringify(off))
await pg.locator('.sheet').screenshot({ path: OUT + '/btn-off.png' })

await pg.locator('.sheet textarea, .sheet input[type=text]').first().fill('写点东西')
await pg.waitForTimeout(500)
const on = await read()
console.log('写了字：', JSON.stringify(on))
await pg.locator('.sheet').screenshot({ path: OUT + '/btn-on.png' })

const ratio = (x, y) => {
  const lum = (c) => {
    const [r, g, b] = c.match(/[\d.]+/g).slice(0, 3).map(Number).map((v) => {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const [hi, lo] = [lum(x), lum(y)].sort((m, n) => n - m)
  return +((hi + 0.05) / (lo + 0.05)).toFixed(2)
}
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
if (off && on) {
  console.log('')
  t('禁用/可用一眼分得出（底色不同，不是只差个透明度）',
    off.bg !== on.bg, `${off.bg} vs ${on.bg}`)
  t('禁用态字仍读得出（≥3:1，她要知道这按钮是干嘛的）',
    ratio(off.color, off.bg) >= 3, String(ratio(off.color, off.bg)))
  t('可用态没被动到（仍是实心主色）', on.opacity === '1' && on.bg !== off.bg, `${on.bg} @${on.opacity}`)
}
await b.close()
process.exit(fail ? 1 : 0)
