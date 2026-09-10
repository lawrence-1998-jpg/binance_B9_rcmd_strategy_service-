// 「清空全部数据」之后这个 App 长什么样。
//
// 这套以前把一堆事实**印出来但不断言**：清空前的警告、横向溢出、
// 空态里还有没有可点的入口、有没有页面报错 —— 全是 console.log，
// 只有「有没有 undefined / NaN / Invalid Date / null」那一条真的会红。
// 于是空态可以横向溢出、可以一个入口都没有、可以满屏报错，照样 ✓8。
// 跟 verify-backup 是同一族：印出来不等于验过。
import pkg from 'playwright'
const { chromium } = pkg
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const b = await chromium.launch()

for (const scheme of (process.argv[2] ? [process.argv[2]] : ['light', 'dark'])) {
  const ctx = await b.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2, colorScheme: scheme })
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort())
  const pg = await ctx.newPage()
  const errs = []; pg.on('pageerror', e => errs.push(e.message))

  // 走真实路径清空：设置 → 清空全部数据 → 确认
  await pg.goto(URL); await pg.waitForTimeout(400)
  await pg.goto(URL + '#/review'); await pg.reload(); await pg.waitForTimeout(500)
  await pg.locator('button[aria-label=设置]').click(); await pg.waitForTimeout(400)
  await pg.locator('button:has-text("清空全部数据")').click(); await pg.waitForTimeout(300)
  const warned = await pg.evaluate(() => { const w = document.querySelector('.warn'); return w ? w.innerText.replace(/\n/g, ' ').slice(0, 50) : null })
  // 这是挡在「一键抹掉全部数据」前面的唯一一道门，必须真的在
  t(`[${scheme}] 清空前先弹警告`, !!warned, warned || '（没有！）')
  await pg.locator('button:has-text("确认清空")').click(); await pg.waitForTimeout(700)

  console.log(`\n=== ${scheme} 空状态 ===`)
  for (const [hash, name] of [['#/today', '今日'], ['#/work', '工作'], ['#/life', '生活'], ['#/review', '复盘']]) {
    await pg.goto(URL + hash); await pg.reload(); await pg.waitForTimeout(450)
    const r = await pg.evaluate(() => {
      const main = document.querySelector('main')
      const text = main ? main.innerText : ''
      const de = document.documentElement
      // 空态里有没有可操作的入口
      const actions = [...document.querySelectorAll('main button:not(.sr)')]
        .map(b => b.innerText.trim().replace(/\s+/g, ' ')).filter(Boolean)
      return {
        height: main ? Math.round(main.scrollHeight) : 0,
        chars: text.replace(/\s/g, '').length,
        bad: (text.match(/undefined|NaN|Invalid Date|null/g) || []),
        actions: actions.slice(0, 6),
        overflow: de.scrollWidth > innerWidth ? `${de.scrollWidth}>${innerWidth}` : 'none',
      }
    })
    t(`[${scheme}] ${name}：没有 undefined / NaN 这类脏字符`,
      r.bad.length === 0, `高 ${r.height}px, 文字 ${r.chars} 字${r.bad.length ? ', 脏字符: ' + r.bad.join(',') : ''}`)
    // 空态最容易横着溢出：没内容撑着的时候，某个 min-width 就露出来了
    t(`[${scheme}] ${name}：不横向溢出`, r.overflow === 'none', r.overflow)
    // 空态最怕的是死路一条 —— 什么都没有，也没有任何一处能开始
    t(`[${scheme}] ${name}：至少有一个能点的入口`,
      r.actions.length > 0, r.actions.join(' / ') || '（一个都没有）')
    await pg.screenshot({ path: `${OUT}/e-${scheme}-${name}.png`, fullPage: true })
  }
  // 清空之后 Prompt 工具里不该还留着一份她没写过的调研提纲
  await pg.goto(URL + '#/today?sheet=prompts'); await pg.reload(); await pg.waitForTimeout(500)
  await pg.getByRole('button', { name: 'Prompt' }).last().click().catch(() => {})
  await pg.waitForTimeout(600)
  // 那三个格子在「提纲 → 调研 Prompt」这个子页里，不在浮层首页
  await pg.locator('button.pitem', { hasText: '提纲 → 调研 Prompt' }).click()
  await pg.waitForTimeout(600)
  // ⚠️ 先确认这个浮层真的开了。
  // 开不了的话下面 querySelectorAll 一个输入框都找不到，
  // `draft.length === 0` 会**凭空通过** —— 又是一条假绿。
  const opened = await pg.locator('[role=dialog]').count()
  t(`[${scheme}] Prompt 浮层真的打开了（不然下面那条等于没验）`, opened === 1, `dialog=${opened}`)
  const draft = await pg.evaluate(() => {
    const fs = [...document.querySelectorAll('[role=dialog] textarea.field, [role=dialog] input.field')]
    return { n: fs.length, filled: fs.map((f) => f.value).filter((v) => v && v.trim()) }
  })
  t(`[${scheme}] Prompt 工具里确实有那几个输入框`, draft.n >= 3, `找到 ${draft.n} 个`)
  t(`[${scheme}] 清空之后 Prompt 工具里没有填好的内容`,
    draft.filled.length === 0, draft.filled.join(' | ').slice(0, 60))

  t(`[${scheme}] 全程没有页面报错`, errs.length === 0, errs.slice(0, 2).join(' | '))
  await ctx.close()
}
await b.close()
console.log(fail ? `\n${fail} 条没过` : '\n全过')
process.exit(fail ? 1 : 0)
