/**
 * 看得清、点得到、不出界 —— 手机 / 电脑 × 浅色 / 深色，空着 / 贴进来之后，八种情况都量一遍。
 *
 * 截图落在 test/shots/，出问题时 CI 会把它们捞出来。
 */
import pkg from 'playwright'
import { mkdirSync } from 'node:fs'
import { SAMPLES } from './samples.mjs'
const { chromium, devices } = pkg

const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const SHOTS = new globalThis.URL('./shots/', import.meta.url).pathname
mkdirSync(SHOTS, { recursive: true })
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
const CHAT = SAMPLES.find((s) => s.name.startsWith('微信群聊')).text

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

// 字 × 底：页面上真的出现过的组合
const PAIRS = [
  ['--ink', '--bg'], ['--ink-2', '--bg'], ['--ink-3', '--bg'],
  ['--ink', '--card'], ['--ink-2', '--card'], ['--ink-3', '--card'],
  ['--ink-2', '--sunk'], ['--ink', '--raise'], ['--ink-3', '--sunk'],
  ['--on-btn', '--btn'], ['--on-ok', '--ok'], ['--ok-text', '--ok-soft'],
  ['--accent', '--accent-soft'], ['--accent', '--card'], ['--accent', '--bg'],
]

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
  const pg = await ctx.newPage()
  const errs = []
  pg.on('pageerror', (e) => errs.push(e.message))
  await pg.goto(URL, { waitUntil: 'load' })
  await pg.evaluate(() => localStorage.clear())
  await pg.reload({ waitUntil: 'load' })
  const tag = name.replace('·', '-')
  const phone = !name.startsWith('电脑')

  // ---- 颜色：只在第一次遇到这个配色时量
  if (name === '手机·浅色' || name === '手机·深色') {
    const vars = await pg.evaluate((names) => {
      const cs = getComputedStyle(document.documentElement)
      return Object.fromEntries(names.map((n) => [n, cs.getPropertyValue(n).trim()]))
    }, [...new Set(PAIRS.flat())])
    const low = PAIRS.map(([f, g]) => [f, g, ratio(vars[f], vars[g])]).filter(([, , r]) => r < 4.5)
    t(`${name}：${PAIRS.length} 组字/底的对比度都 ≥ 4.5`, low.length === 0,
      low.map(([f, g, r]) => `${f} on ${g} ${r.toFixed(2)}`).join(' | ') || '')
  }

  const measure = () => pg.evaluate(() => {
    const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' }
    const small = [...document.querySelectorAll('button, a, input, textarea, [role="button"], label.switch')]
      .filter(vis)
      .filter((el) => !el.closest('.pv'))
      // 开关里那个 checkbox 是藏起来的，真正让手指点的是外面整条 label
      .filter((el) => !(el.matches('input[type=checkbox]') && el.closest('label.switch')))
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter(({ r }) => r.height < 44 || r.width < 44)
      .map(({ el, r }) => `${el.className || el.tagName}「${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 8)}」${Math.round(r.width)}×${Math.round(r.height)}`)
    const tinyInputs = [...document.querySelectorAll('input:not([type=checkbox]), textarea')]
      .filter(vis).filter((el) => parseFloat(getComputedStyle(el).fontSize) < 16).length
    return {
      overflow: document.documentElement.scrollWidth - innerWidth,
      small, tinyInputs,
      nameH: document.querySelector('.name')?.getBoundingClientRect().height ?? 0,
    }
  })

  // ---- 空着
  let m = await measure()
  await pg.screenshot({ path: `${SHOTS}look-${tag}-空.png` })
  t(`${name}·空：没有横向滚动`, m.overflow <= 0, `多出 ${m.overflow}px`)
  t(`${name}·空：每个能点的都 ≥ 44×44`, m.small.length === 0, m.small.slice(0, 4).join(' | '))
  const pb = await pg.locator('.paste-btn').boundingBox()
  t(`${name}·空：「从剪贴板贴入」在第一屏里`, pb && pb.y + pb.height <= (opts.viewport?.height ?? 800), pb ? `底边 ${Math.round(pb.y + pb.height)}` : '')

  // ---- 贴进来之后
  await pg.evaluate((x) => navigator.clipboard.writeText(x), CHAT)
  await pg.locator('.paste-btn').click()
  await pg.waitForTimeout(400)
  m = await measure()
  await pg.screenshot({ path: `${SHOTS}look-${tag}-贴进来.png` })
  t(`${name}·贴进来：没有横向滚动`, m.overflow <= 0, `多出 ${m.overflow}px`)
  t(`${name}·贴进来：每个能点的都 ≥ 44×44`, m.small.length === 0, m.small.slice(0, 4).join(' | '))
  t(`${name}·贴进来：输入框字号都 ≥ 16px（iOS 不会放大页面）`, m.tinyInputs === 0, `${m.tinyInputs} 个`)
  t(`${name}·贴进来：顶栏的「随手」没被挤成两行`, m.nameH > 0 && m.nameH < 32, `${Math.round(m.nameH)}px`)

  const vh = await pg.evaluate(() => innerHeight)
  const bar = await pg.locator('.bar').boundingBox()
  const go = await pg.locator('.go').boundingBox()
  t(`${name}·贴进来：复制按钮和「复制并打开」整条都在屏幕里`, bar && go && bar.y >= 0 && go.y + go.height <= vh + 0.5,
    bar && go ? `底栏 ${Math.round(bar.y)}–${Math.round(go.y + go.height)}，屏高 ${vh}` : '')
  const first = await pg.locator('.intent').first().boundingBox()
  t(`${name}·贴进来：不用滚就能看到第一个用途`, first && first.y + first.height <= (phone ? bar.y : vh), first ? `${Math.round(first.y + first.height)}` : '')

  if (phone) {
    // 底栏是浮着的 —— 滚到最底下，最后一行字不能被它压住
    await pg.evaluate(() => scrollTo(0, document.documentElement.scrollHeight))
    await pg.waitForTimeout(200)
    const card = await pg.locator('.card').boundingBox()
    const bar2 = await pg.locator('.bar').boundingBox()
    t(`${name}·滚到底：Prompt 卡片最后一行没被底栏压住`, card.y + card.height <= bar2.y + 0.5, `卡片底 ${Math.round(card.y + card.height)}，底栏顶 ${Math.round(bar2.y)}`)

    // 提示条要浮在底栏上面，不能叠在一起
    const ERR = SAMPLES.find((s) => s.name === 'Python 报错').text
    await pg.evaluate((x) => navigator.clipboard.writeText(x), ERR)
    await pg.locator('.mini', { hasText: '换一段' }).click()
    await pg.waitForTimeout(300)
    const toast = await pg.locator('.toast').boundingBox({ timeout: 2000 }).catch(() => null)
    const bar3 = await pg.locator('.bar').boundingBox()
    t(`${name}：「撤销」提示条不压在底栏上`, toast !== null && toast.y + toast.height <= bar3.y, toast ? `提示底 ${Math.round(toast.y + toast.height)}，底栏顶 ${Math.round(bar3.y)}` : '提示条没出来')
  } else {
    const right = await pg.locator('.right').boundingBox()
    const left = await pg.locator('.left').boundingBox()
    t(`${name}·贴进来：左右两栏并排`, right.x > left.x + left.width - 1, `左 ${Math.round(left.x)}+${Math.round(left.width)}，右 ${Math.round(right.x)}`)
  }

  t(`${name}：没有页面报错`, errs.length === 0, errs.join(' | '))
  await ctx.close()
}

await b.close()
process.exit(fail ? 1 : 0)
