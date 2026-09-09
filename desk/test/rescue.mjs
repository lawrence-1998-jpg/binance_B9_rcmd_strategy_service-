import pkg from 'playwright'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const KEY = 'deskside.v1'
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0

/**
 * 读不出来的数据会怎么样。
 *
 * load() 里只要 JSON 解析失败、或者对象上没有 version 字段，就直接
 * `return seed()` —— 回到示例数据。然后她一动，persist() 就把示例数据
 * **盖回同一个 key**。也就是她那本日记会被静默地、永久地覆盖掉，
 * 而且没有任何提示。
 *
 * 这是这个 App 能造成的最坏结果，而它没有后端、没有回收站、
 * 她也还没有导出备份的习惯。所以先把它测出来。
 */
const REAL = {
  // 她真实数据的样子，但少了 version（或者坏了）
  entries: [{ id: 'e1', text: '这是她写了半年的东西', at: 1788000000000, kind: 'idea' }],
  anniversaries: [{ id: 'a1', name: '在一起', date: '2019-05-20' }],
  notes: [], tasks: [], engagements: [], inquiries: [], meetings: [],
  wishes: [], logs: [], photos: [], moments: [], myPrompts: [],
}

const cases = [
  ['没有 version 字段（对象是好的）', JSON.stringify(REAL)],
  ['version 是 0', JSON.stringify({ ...REAL, version: 0 })],
  ['JSON 被截断', JSON.stringify({ ...REAL, version: 1 }).slice(0, 120)],
  ['整个是一段乱码', 'not json at all {{{'],
]

const b = await chromium.launch()
for (const [name, raw] of cases) {
  const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
  const pg = await ctx.newPage()
  const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
  await pg.goto(URL, { waitUntil: 'load' })
  await pg.evaluate(([k, v]) => { localStorage.removeItem('deskside.v1.rescue'); localStorage.setItem(k, v) }, [KEY, raw])
  await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(700)

  const rendered = await pg.locator('.tabbar').count() > 0
  // 让她「用一下」——随便触发一次写盘
  await pg.evaluate(() => { location.hash = '#/life' })
  await pg.waitForTimeout(300)
  const chk = await pg.locator('.check, input[type=checkbox]').first()
  if (await chk.count()) { await chk.click({ force: true }).catch(() => {}) ; await pg.waitForTimeout(400) }

  const after = await pg.evaluate((k) => {
    const cur = localStorage.getItem(k)
    const keys = Object.keys(localStorage)
    return { cur: cur ? cur.slice(0, 60) : null, len: cur?.length ?? 0, keys }
  }, KEY)
  const kept = await pg.evaluate((r) => localStorage.getItem(r), 'deskside.v1.rescue')
  const byteExact = kept === raw
  const banner = await pg.locator('.rescue').count() > 0
  const canExport = await pg.locator('.rescue button:has-text("导出那份")').count() > 0

  console.log(`\n【${name}】`)
  console.log('   渲染出来了:', rendered, '| 页面错误:', errs.length || '无')
  console.log('   localStorage 里的 key:', JSON.stringify(after.keys))
  t('  不崩', rendered && errs.length === 0, errs[0] ?? '')
  t('  原始那份一个字节不差地留着', byteExact, kept === null ? '一点都没留' : `留了 ${kept.length} 字节`)
  t('  界面上明确告诉她了', banner)
  t('  能把那份导出去', canExport)
  await ctx.close()
}
// ---- 正常数据下绝不能报警 ----
{
  const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
  const pg = await ctx.newPage()
  await pg.goto(URL, { waitUntil: 'load' })
  await pg.evaluate(([k, v]) => { localStorage.removeItem('deskside.v1.rescue'); localStorage.setItem(k, v) },
    [KEY, JSON.stringify({ ...REAL, version: 1 })])
  await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(700)
  console.log('\n【正常数据】')
  t('  不弹「读不出来」（好数据不许被吓一跳）', await pg.locator('.rescue').count() === 0)
  t('  她的东西读出来了', (await pg.evaluate(() => document.body.innerText)).length > 50)
  t('  没有多留垃圾 key', (await pg.evaluate(() => Object.keys(localStorage))).join() === KEY)
  await ctx.close()
}

// ---- 第二次出事不许盖掉第一份 ----
{
  const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
  const pg = await ctx.newPage()
  await pg.goto(URL, { waitUntil: 'load' })
  await pg.evaluate(([k, v]) => { localStorage.removeItem('deskside.v1.rescue'); localStorage.setItem(k, v) },
    [KEY, '第一次坏掉的那份——她真正的数据'])
  await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(600)
  await pg.evaluate((k) => localStorage.setItem(k, '第二次坏掉的（这时主 key 已经是示例数据了）'), KEY)
  await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(600)
  const kept = await pg.evaluate(() => localStorage.getItem('deskside.v1.rescue'))
  console.log('\n【连着坏两次】')
  t('  留的还是第一份（先来的那份最接近她真的数据）',
    kept === '第一次坏掉的那份——她真正的数据', String(kept))
  await ctx.close()
}

await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ 全过')
process.exit(fail ? 1 : 0)
