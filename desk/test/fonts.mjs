import pkg from 'playwright'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0

/**
 * 字体收进仓库之后：不许再有任何外部依赖，而且要真的用上。
 * 「不白屏」不等于「修好了」——如果代价是字体永远加载不出来，那是另一种坏。
 */
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const outside = []
// 除了本机的测试服务器，任何外部请求都算问题
await ctx.route('**/*', (route, request) => {
  const u = request.url()
  if (!u.startsWith('http://127.0.0.1:8765')) { outside.push(u); return route.abort() }
  return route.continue()
})
const pg = await ctx.newPage()
const t0 = Date.now()
await pg.goto(URL, { waitUntil: 'load' })
console.log(`  load: ${Date.now() - t0}ms`)
// 字体是按需加载的：页面上没用到的字形不会去取。要判断「装得上」，
// 必须显式让它加载一次，不然测的只是「这一屏刚好没用到」
await pg.evaluate(async () => {
  await Promise.all([
    document.fonts.load('400 40px Caprasimo'),
    document.fonts.load('400 16px Figtree'),
    document.fonts.load('800 16px Figtree'),
    document.fonts.load('500 16px "IBM Plex Mono"'),
  ])
  await document.fonts.ready
})

t('没有任何外部请求', outside.length === 0, outside.slice(0, 3).join(' '))

const checks = await pg.evaluate(() => ({
  capra: document.fonts.check('400 16px Caprasimo'),
  fig4: document.fonts.check('400 16px Figtree'),
  fig8: document.fonts.check('800 16px Figtree'),
  mono: document.fonts.check('500 16px "IBM Plex Mono"'),
  loaded: [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family + ' ' + f.weight),
}))
t('Caprasimo 装上了', checks.capra)
t('Figtree 400 装上了', checks.fig4)
t('Figtree 800 装上了（变体字重没丢）', checks.fig8)
t('IBM Plex Mono 装上了', checks.mono)
console.log('  实际加载:', checks.loaded.join(' | ') || '（无）')

// 真的用在了页面上 —— 光「装上」不算，得量出来它跟回退字体不一样宽
const widths = await pg.evaluate(() => {
  const mk = (ff) => {
    const s = document.createElement('span')
    s.textContent = 'Deskside 2026'
    s.style.cssText = `position:absolute;visibility:hidden;font-size:40px;font-family:${ff}`
    document.body.appendChild(s)
    const w = s.getBoundingClientRect().width
    s.remove()
    return Math.round(w)
  }
  return { capra: mk('Caprasimo, Georgia, serif'), georgia: mk('Georgia, serif'),
           fig: mk('Figtree, system-ui'), sys: mk('system-ui') }
})
t('Caprasimo 真的在渲染（不是退回 Georgia）', widths.capra !== widths.georgia, JSON.stringify(widths))

// Figtree 五个字重共用一个可变字体文件。文件只有一个，粗细必须还是五种——
// 声明写错的话全站会悄悄变成同一个字重，而截图上很难看出来。
// 不能量宽度：可变字体各字重的字宽几乎一样。直接画到 canvas 上数墨水
const ink = await pg.evaluate(async () => {
  await Promise.all([400, 500, 600, 700, 800].map((w) => document.fonts.load(`${w} 40px Figtree`)))
  const c = document.createElement('canvas')
  c.width = 400; c.height = 60
  const x = c.getContext('2d')
  return [400, 500, 600, 700, 800].map((w) => {
    x.clearRect(0, 0, 400, 60)
    x.fillStyle = '#000'
    x.font = `${w} 40px Figtree`
    x.fillText('Deskside', 4, 44)
    const d = x.getImageData(0, 0, 400, 60).data
    let n = 0
    for (let i = 3; i < d.length; i += 4) n += d[i]   // alpha 累加 = 墨水量
    return Math.round(n / 1000)
  })
})
console.log('  Figtree 400→800 墨水量:', ink.join(' / '))
const rising = ink.every((v, i) => i === 0 || v > ink[i - 1])
t('五个字重一个比一个粗（可变轴生效）', rising, ink.join('/'))


// 数字倒数用的就是这套字体，量一个真实元素
const real = await pg.evaluate(async () => {
  await document.fonts.ready
  const el = [...document.querySelectorAll('*')].find((e) => /Caprasimo/.test(getComputedStyle(e).fontFamily))
  return el ? { tag: el.tagName, cls: el.className, txt: el.textContent?.slice(0, 12) } : null
})
console.log('  页面上用 Caprasimo 的元素:', JSON.stringify(real))

await pg.screenshot({ path: `${OUT}/fonts-offline.png`, fullPage: false })
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 完全离线也是完整的样子')
process.exit(fail ? 1 : 0)
