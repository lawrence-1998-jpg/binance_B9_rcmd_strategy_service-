import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0, 10)
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', e => errs.push(e.message))

await pg.goto(URL)
await pg.evaluate(s => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))

/**
 * iOS Safari 在聚焦一个字号 < 16px 的输入框时会自动放大整个页面。
 * 放大之后 position:fixed 的 tab 栏被推出可视区——真机上「复盘」那个 tab 直接消失。
 * Chromium 不会这样，所以之前那套测试完全没抓到。
 * 这里不测「有没有放大」（测不了），直接测触发条件：字号必须 ≥ 16。
 */
const NEEDS_16 = 'input:not([type=checkbox]):not([type=radio]):not([type=file]), textarea, select'

const routes = [['#/today', '今日'], ['#/work', '工作'], ['#/life', '生活'], ['#/review', '复盘']]
let bad = 0, total = 0
const seen = {}

async function scan(where) {
  const r = await pg.evaluate((sel) => {
    return [...document.querySelectorAll(sel)].map(el => ({
      tag: el.tagName.toLowerCase() + (el.type ? `[${el.type}]` : ''),
      cls: (typeof el.className === 'string' ? el.className : '').slice(0, 26),
      ph: (el.placeholder || el.getAttribute('aria-label') || '').slice(0, 16),
      size: +parseFloat(getComputedStyle(el).fontSize).toFixed(2),
      visible: el.getBoundingClientRect().width > 1,
    }))
  }, NEEDS_16)
  for (const x of r) {
    total++
    const ok = x.size >= 16
    if (!ok) { bad++; console.log(`  ✗ [${where}] ${x.tag} .${x.cls} 「${x.ph}」 ${x.size}px`) }
  }
  return r.length
}

for (const [hash, name] of routes) {
  await pg.goto(URL + hash); await pg.reload(); await pg.waitForTimeout(400)
  let n = await scan(name)
  // 展开所有行内新增，把藏起来的输入框也翻出来
  for (const btn of await pg.locator('main button').all()) {
    const txt = (await btn.innerText().catch(() => '')) || ''
    if (/＋|加一件|再加|写一句|再想|排一天|加第一个|定一个/.test(txt)) {
      await btn.click({ timeout: 1500 }).catch(() => {})
      await pg.waitForTimeout(180)
    }
  }
  n += await scan(name + '(展开)')
  console.log(`${name}: 扫了 ${n} 个可输入控件`)
}

// sheet 里的
for (const [open, name] of [
  [async () => { await pg.goto(URL + '#/today'); await pg.reload(); await pg.waitForTimeout(400); await pg.locator('.cap').click() }, '速记'],
  [async () => { await pg.goto(URL + '#/review'); await pg.reload(); await pg.waitForTimeout(400); await pg.locator('button[aria-label=设置]').click() }, '设置'],
  [async () => { await pg.goto(URL + '#/work'); await pg.reload(); await pg.waitForTimeout(400); await pg.locator('button[aria-label*=Prompt]').first().click() }, 'Prompt'],
  // 提纲那三个格子在子页里，不在浮层首页 —— 以前一个都没扫到
  [async () => {
    await pg.goto(URL + '#/today'); await pg.reload(); await pg.waitForTimeout(400)
    await pg.getByRole('button', { name: 'Prompt' }).last().click()
    await pg.waitForTimeout(400)
    await pg.locator('button.pitem', { hasText: '提纲 → 调研 Prompt' }).click()
  }, 'Prompt·生成器'],
]) {
  await open().catch(() => {})
  await pg.waitForTimeout(500)
  const n = await scan(name)
  seen[name] = n
  console.log(`${name}: 扫了 ${n} 个`)
}

console.log(`\n${bad === 0 ? '✓' : '✗'} 共 ${total} 个可输入控件，字号 < 16px 的 ${bad} 个`)

// ⚠️ `bad === 0` 只有在**真的扫到东西**的时候才有意义。
// 选择器写错、某个浮层没打开（下面那几步都带 .catch 吞异常），
// 扫到 0 个控件时 bad 也是 0 —— 一条凭空通过的断言。
// 所以把「扫到了多少」也钉住。
let fail = bad
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
t(`整个 App 一共扫到了足够多的可输入控件`, total >= 15, `扫到 ${total} 个`)
// 这三处是最容易「浮层没打开却照样通过」的地方，单独钉
t('速记浮层里扫到了输入框', (seen['速记'] ?? 0) >= 1, `${seen['速记']} 个`)
t('设置浮层里扫到了输入框', (seen['设置'] ?? 0) >= 1, `${seen['设置']} 个`)
t('Prompt 生成器子页里扫到了那三个格子',
  (seen['Prompt·生成器'] ?? 0) >= 3, `${seen['Prompt·生成器']} 个`)
t('没有页面报错', errs.length === 0, errs.slice(0, 2).join(' | '))

await b.close()
process.exit(fail === 0 ? 0 : 1)
