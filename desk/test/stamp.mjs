import pkg from 'playwright'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0
// 版本戳这次要真的在屏幕上。上一版是 define 配好了、类型也声明了，
// 就是没有任何一个组件把它渲染出来——等于没有
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(URL + '#/review', { waitUntil: 'load' })
await pg.reload(); await pg.waitForTimeout(600)
await pg.locator('button[aria-label=设置]').click(); await pg.waitForTimeout(600)
const about = await pg.locator('.card', { hasText: '案头 Deskside v1' }).innerText()
console.log('  关于卡片:\n   ' + about.replace(/\n/g, '\n   '))
t('版本号印在屏幕上了', /[0-9a-f]{7}|dev/.test(about), about.split('\n')[1] ?? '')
t('构建时间印在屏幕上了', /\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(about))
const btn = pg.locator('button:has-text("检查更新")')
t('有「检查更新」按钮', await btn.count() > 0)
const box = await btn.first().boundingBox()
t('按钮够大', box.height >= 44, `${Math.round(box.width)}×${Math.round(box.height)}`)
await btn.first().click()
await pg.waitForTimeout(900)
const toast = await pg.locator('.toast').count() ? await pg.locator('.toast').innerText() : '(没有提示)'
t('点了之后有明确回话', toast !== '(没有提示)', toast)

// 提示是不是真的看得见 —— 设置页是一整块不透明的浮层，
// 提示条如果层级比它低，就是「弹了但她看不到」
const vis = await pg.evaluate(() => {
  const el = document.querySelector('.toast')
  if (!el) return null
  const r = el.getBoundingClientRect()
  const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
  return { z: getComputedStyle(el).zIndex, sheetZ: getComputedStyle(document.querySelector('.sheet')).zIndex,
           onTop: !!top && (top === el || el.contains(top)), topEl: top?.className ?? null }
})
console.log('  提示层级:', JSON.stringify(vis))
t('提示条压在设置页上面（不是被盖住）', vis?.onTop === true, JSON.stringify(vis))
t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
