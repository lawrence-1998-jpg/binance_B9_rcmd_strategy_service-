import pkg from 'playwright'
const { chromium } = pkg
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
  console.log(`[${scheme}] 清空前的警告: ${warned || '（没有！）'}`)
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
    const mark = r.bad.length ? '✗' : '✓'
    console.log(`${mark} ${name}: 高 ${r.height}px, 文字 ${r.chars} 字, 溢出 ${r.overflow}${r.bad.length ? ', 脏字符: ' + r.bad.join(',') : ''}`)
    console.log(`    可点入口: ${r.actions.join(' / ') || '（一个都没有）'}`)
    await pg.screenshot({ path: `${OUT}/e-${scheme}-${name}.png`, fullPage: true })
  }
  console.log(`[${scheme}] 页面错误: ${errs.length ? errs.slice(0, 3).join(' | ') : '无'}`)
  await ctx.close()
}
await b.close()
