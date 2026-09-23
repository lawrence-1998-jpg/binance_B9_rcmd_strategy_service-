/**
 * 看得清、点得到、不出界：手机 / 小屏 / 电脑 × 浅色 / 深色，
 * 空着（示例卡）、收了几条（一张展开）、多选三种状态都量一遍。
 * 截图落在 test/shots/，CI 挂了会把它们捞出来。
 */
import pkg from 'playwright'
import { mkdirSync } from 'node:fs'
const { chromium, devices } = pkg

const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const MOCK = new globalThis.URL('./mock-claude.js', import.meta.url).pathname
const SHOTS = new globalThis.URL('./shots/', import.meta.url).pathname
mkdirSync(SHOTS, { recursive: true })
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

// ---------------------------------------------------------------- 对比度（WCAG 2.x）
const rgb = (s) => {
  const m = s.match(/rgba?\(([^)]+)\)/)
  if (m) return m[1].split(',').map((x) => parseFloat(x))
  const h = s.trim().replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
}
const lum = ([r, g, b]) => {
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
const ratio = (a, b) => { const [x, y] = [lum(rgb(a)), lum(rgb(b))].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05) }
const KINDS = ['event', 'todo', 'contact', 'link', 'note', 'idea', 'data', 'quote', 'question', 'code', 'other']
// 字 × 底：页面上真的出现过的组合
const PAIRS = [
  ['--ink', '--ground'], ['--ink-2', '--ground'], ['--ink-3', '--ground'],
  ['--ink', '--card'], ['--ink-2', '--card'], ['--ink-3', '--card'],
  ['--ink', '--well'], ['--ink-2', '--well'], ['--ink-3', '--well'],
  ['--on-btn', '--btn'], ['--on-ok', '--ok'], ['--ok-text', '--ok-soft'],
  ['--accent', '--accent-soft'], ['--accent', '--card'], ['--ink', '--accent-soft'],
  ['--danger', '--card'],
  ...KINDS.map((k) => [`--k-${k}`, `--k-${k}-bg`]),
]

const CONTACT = 'Lily Chen｜增长策略负责人\n手机 138 1234 5678\n邮箱 lily.chen@example.com'
const MEET = '王总：周四下午的会挪到周五上午 10 点吧，地点还是国贸三期 B 座 1208。记得带上次那版竞品分析，财务的 Linda 也会来。'

const b = await chromium.launch()
const CONFIGS = [
  ['手机·浅色', { ...devices['iPhone 13'], colorScheme: 'light' }],
  ['手机·深色', { ...devices['iPhone 13'], colorScheme: 'dark' }],
  ['小屏·浅色', { ...devices['iPhone SE'], colorScheme: 'light' }],
  ['电脑·浅色', { viewport: { width: 1280, height: 800 }, colorScheme: 'light' }],
  ['电脑·深色', { viewport: { width: 1280, height: 800 }, colorScheme: 'dark' }],
]

for (const [name, opts] of CONFIGS) {
  const ctx = await b.newContext({ ...opts, permissions: ['clipboard-read', 'clipboard-write'] })
  await ctx.addInitScript({ path: MOCK })
  const pg = await ctx.newPage()
  const errs = []
  pg.on('pageerror', (e) => errs.push(e.message))
  await pg.goto(URL, { waitUntil: 'load' })
  await pg.waitForTimeout(600)
  const tag = name.replace('·', '-')

  if (name === '手机·浅色' || name === '手机·深色') {
    const vars = await pg.evaluate((names) => {
      const cs = getComputedStyle(document.documentElement)
      return Object.fromEntries(names.map((n) => [n, cs.getPropertyValue(n).trim()]))
    }, [...new Set(PAIRS.flat())])
    const missing = Object.entries(vars).filter(([, v]) => !v).map(([k]) => k)
    t(`${name}：每个颜色都定义了`, missing.length === 0, missing.join(' '))
    const low = PAIRS.filter(([f, g]) => vars[f] && vars[g]).map(([f, g]) => [f, g, ratio(vars[f], vars[g])]).filter(([, , r]) => r < 4.5)
    t(`${name}：${PAIRS.length} 组字/底的对比度都 ≥ 4.5`, low.length === 0, low.map(([f, g, r]) => `${f} on ${g} ${r.toFixed(2)}`).join(' | '))
  }

  const measure = () => pg.evaluate(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' }
    const small = [...document.querySelectorAll('button, a, input, textarea, [role="button"], label.todo')]
      .filter(vis)
      // 待办的勾选框：真正让手指点的是外面整行 label
      .filter((el) => !(el.matches('input[type=checkbox]') && el.closest('label.todo')))
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.height < 44 || r.width < 44)
      .map(({ el, r }) => `${el.className || el.tagName}「${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 8)}」${Math.round(r.width)}×${Math.round(r.height)}`)
    const tiny = [...document.querySelectorAll('input:not([type=checkbox]), textarea')].filter(vis)
      .filter((el) => parseFloat(getComputedStyle(el).fontSize) < 16).length
    const clipped = [...document.querySelectorAll('.card h3, .row-v, .card-main p')].filter(vis)
      .filter((el) => el.scrollWidth > el.clientWidth + 1).length
    return {
      overflow: document.documentElement.scrollWidth - innerWidth,
      small, tiny, clipped,
      h1: document.querySelector('.brand h1')?.getBoundingClientRect().height ?? 0,
      vh: innerHeight,
    }
  })
  const check = async (state) => {
    const m = await measure()
    await pg.screenshot({ path: `${SHOTS}look-${tag}-${state}.png` })
    t(`${name}·${state}：没有横向滚动`, m.overflow <= 0, `多出 ${m.overflow}px`)
    t(`${name}·${state}：能点的都 ≥ 44×44`, m.small.length === 0, m.small.slice(0, 4).join(' | '))
    t(`${name}·${state}：输入框字号 ≥ 16px（iOS 不会放大页面）`, m.tiny === 0, `${m.tiny} 个`)
    t(`${name}·${state}：标题、字段值没有被横着裁掉`, m.clipped === 0, `${m.clipped} 处`)
    t(`${name}·${state}：「随手拾」没被挤成两行`, m.h1 > 0 && m.h1 < 34, `${Math.round(m.h1)}px`)
    return m
  }

  // ---- 空着：示例卡
  await check('空')
  const cap = await pg.locator('.capture').boundingBox()
  const ex = await pg.locator('.list .card').first().boundingBox()
  const vh = await pg.evaluate(() => innerHeight)
  t(`${name}·空：收件框和第一张示例卡都在第一屏`, cap && ex && cap.y + cap.height < vh && ex.y < vh - 60, ex ? `示例卡顶 ${Math.round(ex.y)}，屏高 ${vh}` : '')

  // ---- 收了两条，一张展开
  for (const text of [CONTACT, MEET]) {
    await pg.evaluate((x) => navigator.clipboard.writeText(x), text)
    await pg.locator('#capture').focus()
    await pg.keyboard.press('Control+V')
    await pg.waitForTimeout(700)
  }
  await check('收了两条')
  const open = pg.locator('.card.open')
  const copies = await open.locator('.copies').boundingBox()
  const cardBox = await open.boundingBox()
  t(`${name}·收了两条：三个复制按钮在卡片里排成一行`, copies && copies.height < 60 && copies.x >= cardBox.x && copies.x + copies.width <= cardBox.x + cardBox.width,
    copies ? `${Math.round(copies.width)}×${Math.round(copies.height)}` : '')

  // ---- 截图卡
  await pg.evaluate(async () => {
    const c = document.createElement('canvas'); c.width = 600; c.height = 1300
    const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 600, 1300)
    g.fillStyle = '#111'; g.font = '40px sans-serif'; g.fillText('报价单 ¥36,000', 40, 120)
    const blob = await new Promise((r) => c.toBlob(r, 'image/png'))
    const dt = new DataTransfer(); dt.items.add(new File([blob], 's.png', { type: 'image/png' }))
    document.querySelector('#capture').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
  })
  await pg.waitForTimeout(800)
  await check('截图卡')
  const shot = await pg.locator('.card.open .shot').boundingBox()
  t(`${name}·截图卡：图先露一截（不把整屏占满）`, shot && shot.height <= 242, shot ? `${Math.round(shot.height)}px 高` : '没有图')

  // ---- 问答
  await pg.locator('.ghost[aria-label="搜索"]').click()
  await pg.locator('#search').fill('Lily 电话')
  await pg.locator('.ask-go').click()
  await pg.waitForTimeout(900)
  await check('问答')
  const ansBox = await pg.locator('.answer').boundingBox()
  t(`${name}·问答：回答在第一屏里`, ansBox && ansBox.y + 60 < vh, ansBox ? `顶 ${Math.round(ansBox.y)}，屏高 ${vh}` : '')
  await pg.locator('.ghost[aria-label="搜索"]').click()
  await pg.waitForTimeout(200)

  // ---- 多选
  await pg.locator('.ghost', { hasText: '选择' }).click()
  await pg.locator('.list .card .tick').first().click()
  await pg.waitForTimeout(200)
  await check('多选')
  const bar = await pg.locator('.pickbar').boundingBox()
  t(`${name}·多选：底栏整个在屏幕里`, bar && bar.y >= 0 && bar.y + bar.height <= vh + 0.5, bar ? `${Math.round(bar.y)}–${Math.round(bar.y + bar.height)}，屏高 ${vh}` : '')
  await pg.locator('.pickbar .btn', { hasText: '复制整理版' }).click()
  await pg.waitForTimeout(250)
  const toast = await pg.locator('.toast').boundingBox().catch(() => null)
  t(`${name}·多选：「已复制」提示不压在底栏上`, toast && toast.y + toast.height <= bar.y, toast ? `提示底 ${Math.round(toast.y + toast.height)}，底栏顶 ${Math.round(bar.y)}` : '提示没出来')

  t(`${name}：没有页面报错`, errs.length === 0, errs.join(' | '))
  await ctx.close()
}
await b.close()
process.exit(fail ? 1 : 0)
