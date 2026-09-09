import pkg from 'playwright'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0

/**
 * 「导入备份」是她唯一一个能一次性覆盖掉全部内容的动作。
 * 刚修完「读不出来的数据不许扔」，这条就得一起验：
 * 拿错文件、拿到坏文件的时候，会不会把好数据冲掉。
 */
const MINE = {
  version: 1,
  entries: [{ id: 'e1', text: '她自己写的东西', at: 1788000000000, kind: 'idea' }],
  anniversaries: [{ id: 'a1', name: '在一起', date: '2019-05-20' }],
  tasks: [], notes: [], engagements: [], inquiries: [], meetings: [],
  wishes: [], logs: [], photos: [], moments: [], myPrompts: [],
}

const bad = [
  ['随便一个 JSON（不是备份）', JSON.stringify({ hello: 'world', items: [1, 2, 3] })],
  ['形状对但字段类型错', JSON.stringify({ version: 1, entries: 'not an array', tasks: [] })],
  ['一张图（二进制乱码）', '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'],
  ['空文件', ''],
  ['截断的备份', JSON.stringify(MINE).slice(0, 80)],
]

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(URL, { waitUntil: 'load' })

for (const [name, content] of bad) {
  await pg.evaluate((s) => {
    localStorage.removeItem('deskside.v1.rescue')
    localStorage.setItem('deskside.v1', s)
  }, JSON.stringify(MINE))
  await pg.goto(URL + '#/review', { waitUntil: 'load' })
  await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(500)
  await pg.locator('button[aria-label=设置]').click(); await pg.waitForTimeout(500)

  const input = pg.locator('.sheet input[type=file]')
  if (await input.count() === 0) { t(`找得到导入入口`, false); break }
  await input.first().setInputFiles({ name: '乱七八糟.json', mimeType: 'application/json', buffer: Buffer.from(content) })
  await pg.waitForTimeout(900)
  // 如果弹了确认就点确认 —— 我们要测的是「确认之后也不会毁数据」
  const go = pg.locator('.sheet button:has-text("确认导入"), .dialog button:has-text("导入")')
  if (await go.count()) { await go.first().click(); await pg.waitForTimeout(900) }

  const kept = await pg.evaluate(() => {
    const raw = localStorage.getItem('deskside.v1')
    try { return (JSON.parse(raw).entries ?? []).some((e) => e.text === '她自己写的东西') } catch { return false }
  })
  const toast = await pg.locator('.toast').count() ? (await pg.locator('.toast').innerText()).trim() : '(没提示)'
  console.log(`\n【${name}】提示: ${toast}`)
  t('  她原来的东西没被冲掉', kept)
  t('  明确说了这个文件不行', toast !== '(没提示)' && !/导入好了/.test(toast), toast)
}
t('全程无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 拿错文件不会毁掉她的东西')
process.exit(fail ? 1 : 0)
