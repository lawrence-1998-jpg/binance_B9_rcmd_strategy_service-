import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'

const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const today = new Date().toISOString().slice(0,10)

const b = await chromium.launch()
const ctx = await b.newContext({ viewport:{width:430,height:932}, deviceScaleFactor:2 })
await ctx.addInitScript(() => {
  // 关掉入场动画再测量 —— 否则量到的是动画中途的 opacity
  const st = document.createElement('style')
  st.textContent = '*,*::before,*::after{animation:none!important;transition:none!important}'
  document.addEventListener('DOMContentLoaded', () => document.head.appendChild(st))
})
const pg = await ctx.newPage()
const errs = []
pg.on('pageerror', e => errs.push('PAGEERROR: ' + e.message))
pg.on('console', m => { if (m.type()==='error'||m.type()==='warning') errs.push(`${m.type()}: ${m.text()}`) })

await pg.goto(URL)
await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))

// ---- 测量工具，注入页面 ----
const TOOLS = `
window.__lum = (rgb) => {
  const f = (c) => { c/=255; return c<=0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4) }
  return 0.2126*f(rgb[0]) + 0.7152*f(rgb[1]) + 0.0722*f(rgb[2])
}
window.__parse = (s) => {
  const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null
  const p = m[1].split(',').map(x=>parseFloat(x.trim()))
  return { rgb:[p[0],p[1],p[2]], a: p.length>3 ? p[3] : 1 }
}
// 沿祖先链求实际背景（处理 transparent）
window.__bg = (el) => {
  let e = el
  while (e) {
    const c = window.__parse(getComputedStyle(e).backgroundColor)
    if (c && c.a > 0.9) return c.rgb
    e = e.parentElement
  }
  return [255,255,255]
}
window.__ratio = (fg, bg) => {
  const a = window.__lum(fg), b = window.__lum(bg)
  const hi = Math.max(a,b), lo = Math.min(a,b)
  return (hi+0.05)/(lo+0.05)
}
window.__audit = () => {
  const out = { contrast: [], touch: [], overflow: null, textNodes: 0 }
  // 对比度：所有含直接文本的元素
  document.querySelectorAll('*').forEach(el => {
    const direct = [...el.childNodes].some(n => n.nodeType===3 && n.textContent.trim())
    if (!direct) return
    const r = el.getBoundingClientRect()
    if (r.width<1 || r.height<1) return
    const cs = getComputedStyle(el)
    if (cs.visibility==='hidden' || cs.opacity==='0') return
    // 禁用状态的控件不算 —— WCAG 1.4.3 明确豁免 inactive 组件，
    // 而 .btn[disabled] 的 opacity:.75 会把它压到 3.65:1。
    // 以前没排除，于是这份报告长期挂着 3 条永远修不掉的「不达标」，
    // 结果是我每次看到 3 都当作正常 —— 一个永远微红的检查等于没有检查
    if (el.closest('[disabled],[aria-disabled="true"]')) return
    const fgp = window.__parse(cs.color); if (!fgp) return
    let fg = fgp.rgb
    const bg = window.__bg(el)
    // 元素自身 opacity 参与合成
    let op = 1, e = el
    while (e && e !== document.body) { op *= parseFloat(getComputedStyle(e).opacity||'1'); e = e.parentElement }
    const eff = fgp.a * op
    if (eff < 1) fg = fg.map((c,i)=> c*eff + bg[i]*(1-eff))
    const size = parseFloat(cs.fontSize)
    const weight = parseInt(cs.fontWeight)||400
    const large = size >= 24 || (size >= 18.66 && weight >= 700)
    const ratio = window.__ratio(fg, bg)
    const need = large ? 3 : 4.5
    if (ratio < need) {
      out.contrast.push({
        text: (el.textContent||'').trim().slice(0,28),
        cls: el.className && typeof el.className==='string' ? el.className : el.tagName,
        size: +size.toFixed(1), weight, ratio: +ratio.toFixed(2), need,
        fg: fg.map(x=>Math.round(x)).join(','), bg: bg.join(','),
      })
    }
    out.textNodes++
  })
  // 占位符文字。
  // 这一条以前查不到 —— 占位符不是文本节点，上面那个循环从定义上就够不着它。
  // 而 WCAG 不豁免占位符：它是文字，一样要 4.5:1。
  document.querySelectorAll('input,textarea').forEach(el => {
    const ph = el.getAttribute('placeholder')
    if (!ph || !ph.trim()) return
    const r = el.getBoundingClientRect()
    if (r.width<1 || r.height<1) return
    const cs = getComputedStyle(el, '::placeholder')
    const fgp = window.__parse(cs.color); if (!fgp) return
    const bg = window.__bg(el)
    let fg = fgp.rgb
    if (fgp.a < 1) fg = fg.map((c,i)=> c*fgp.a + bg[i]*(1-fgp.a))
    const ratio = window.__ratio(fg, bg)
    if (ratio < 4.5) {
      out.contrast.push({
        text: '占位符：' + ph.slice(0,20),
        cls: (typeof el.className==='string' ? el.className : el.tagName) + '::placeholder',
        size: +parseFloat(getComputedStyle(el).fontSize).toFixed(1),
        weight: 400, ratio: +ratio.toFixed(2), need: 4.5,
        fg: fg.map(x=>Math.round(x)).join(','), bg: bg.join(','),
      })
    }
  })
  // 触控目标
  document.querySelectorAll('button,a,input,textarea,select,[role=button],label.check').forEach(el => {
    const r = el.getBoundingClientRect()
    if (r.width<1||r.height<1) return
    if (getComputedStyle(el).visibility==='hidden') return
    // 视觉隐藏的元素（clip 掉的 checkbox、sr-only 说明）不是触控目标：
    // 真正被点的是包着它们的 label / button
    if (getComputedStyle(el).clip !== 'auto' || el.classList.contains('sr')) return
    if (el.tagName==='INPUT' && el.type==='checkbox') return
    if (r.width < 44 || r.height < 44) {
      out.touch.push({
        cls: (el.className && typeof el.className==='string' ? el.className : '') || el.tagName,
        label: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0,20),
        w: Math.round(r.width), h: Math.round(r.height),
      })
    }
  })
  const de = document.documentElement
  out.overflow = de.scrollWidth > window.innerWidth ? { sw: de.scrollWidth, iw: window.innerWidth } : null
  if (out.overflow) {
    out.overflow.culprits = [...document.querySelectorAll('*')]
      .filter(el => { const r = el.getBoundingClientRect(); return r.right > window.innerWidth + 1 || r.left < -1 })
      .slice(0,6).map(el => ({ cls: typeof el.className==='string'?el.className:el.tagName, right: Math.round(el.getBoundingClientRect().right), text:(el.textContent||'').trim().slice(0,20) }))
  }
  return out
}
`

const screens = [
  ['today',  '#/today'],
  ['work',   '#/work'],
  ['life',   '#/life'],
  ['review', '#/review'],
]

const report = {}
for (const [name, hash] of screens) {
  await pg.goto(URL + hash)
  await pg.reload()
  await pg.waitForTimeout(500)
  await pg.evaluate(TOOLS)
  report[name] = await pg.evaluate(() => window.__audit())
  await pg.screenshot({ path: `${OUT}/s-${name}.png`, fullPage: true })
}

// sheets
async function openSheet (name, hash, opener) {
  await pg.goto(URL + hash); await pg.reload(); await pg.waitForTimeout(400)
  const ok = await opener()
  if (!ok) { report[name] = { skipped: 'opener not found' }; return }
  await pg.waitForTimeout(500)
  await pg.evaluate(TOOLS)
  report[name] = await pg.evaluate(() => window.__audit())
  await pg.screenshot({ path: `${OUT}/s-${name}.png`, fullPage: true })
}

await openSheet('capture', '#/today', async () => {
  const el = pg.locator('.cap'); if (!await el.count()) return false; await el.click(); return true
})
await openSheet('settings', '#/review', async () => {
  for (const btn of await pg.locator('button').all()) {
    const al = (await btn.getAttribute('aria-label')) || ''
    if (al.includes('设置')) { await btn.click(); return true }
  }
  return false
})
await openSheet('prompts', '#/work', async () => {
  // 只认底栏那个入口。以前这里还认「提纲」，种子里有了调研线之后
  // 「贴提纲，拆成调研线」排在更前面，于是量到的其实是另一张表
  const el = pg.locator('.tabbar button:has-text("Prompt")')
  if (!await el.count()) return false
  await el.first().click(); return true
})

// 调研线详情 —— 她真正干活的那一屏。
// 以前审计够不着它：seed 里一条调研线都没有，而它又是 Work 里的一张表，
// 不是路由。于是关键词 / 数据（带出处、置信）/ 收口状态这些控件
// 从来没进过对比度、触控、溢出的体检。
async function openInquiry (name, nth) {
  await openSheet(name, '#/work', async () => {
    const eng = pg.locator('button:has-text("会员体系诊断")')
    if (!await eng.count()) return false
    await eng.first().click(); await pg.waitForTimeout(300)
    const row = pg.locator('.qrow')
    if (await row.count() <= nth) return false
    await row.nth(nth).click(); return true
  })
}
// 走完的那条
await openInquiry('inquiry', 0)
// 刚拆出来、一步都没走的那条。
// 必须单开一次：走完的那条四步全是「已完成」配色，
// 「还没走到」那个配色一次都没渲染过，也就一次都没被体检过
await openInquiry('inquiry-new', 2)

import('node:fs').then(fs => fs.writeFileSync(OUT + '/report.json', JSON.stringify({ report, errs }, null, 1)))
console.log('errs:', errs.length ? errs.slice(0,10) : 'none')
for (const [k,v] of Object.entries(report)) console.log('  ', k, '| 对比度不达标', (v.contrast||[]).length, '| 触控偏小', (v.touch||[]).length, '| 溢出', v.overflow ? v.overflow.sw+'>'+v.overflow.iw : 'none', v.skipped||'')

// 出断言 + 退出码。
// 以前这个脚本只把数字打出来，靠我自己看 —— 于是它跑出 0 我就说「全 0」，
// 跑出 1 我也照样往下走。现在它进 run-all.sh，红了就是红了。
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
for (const [k, v] of Object.entries(report)) {
  if (v.skipped) { t(`明 ${k} 打得开`, false, v.skipped); continue }
  const c = (v.contrast||[]), tp = (v.touch||[])
  t(`明 ${k} 对比度`, c.length === 0,
    c.slice(0,2).map(x=>`${x.ratio}:1 .${x.cls}「${x.text}」`).join('；'))
  t(`明 ${k} 触控 ≥44`, tp.length === 0,
    tp.slice(0,2).map(x=>`${x.w}x${x.h} 「${x.label}」`).join('；'))
  t(`明 ${k} 不横向溢出`, !v.overflow, v.overflow ? `${v.overflow.sw}>${v.overflow.iw}` : '')
}
t('明 控制台没有报错', errs.length === 0, errs.slice(0,2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
