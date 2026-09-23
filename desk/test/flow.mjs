/**
 * 在「claude.ai 里打开」的情况下把整条路走一遍（用 mock-claude.js 装一个假的运行时）：
 *   收 → Claude 整理 → 各种复制 → 待办 → 筛选 / 搜索 → 多选 → 删除撤销 → 置顶 → 改标题 → 刷新还在
 *   → Claude 忙 / 不可用 时怎么退。
 *
 * 复制的每一步都去读真的剪贴板，不看按钮上写了什么。
 */
import pkg from 'playwright'
const { chromium, devices } = pkg

const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const MOCK = new globalThis.URL('./mock-claude.js', import.meta.url).pathname
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const CONTACT = 'Lily Chen｜增长策略负责人\n手机 138 1234 5678\n邮箱 lily.chen@example.com'
const MEET = '王总：周四下午的会挪到周五上午 10 点吧，地点还是国贸三期 B 座 1208。记得带上次那版竞品分析，财务的 Linda 也会来。'
const NOTE = '想法：会员体系的核心问题可能不是权益太少，而是用户根本不知道自己有哪些权益。'

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'] })
await ctx.addInitScript({ path: MOCK })
const pg = await ctx.newPage()
const errs = []
pg.on('pageerror', (e) => errs.push(e.message))

const clip = () => pg.evaluate(() => navigator.clipboard.readText())
const setClip = (s) => pg.evaluate((x) => navigator.clipboard.writeText(x), s)
const cards = () => pg.locator('.list article.card')
const card = (text) => cards().filter({ hasText: text }).first()
const toast = () => pg.locator('.toast').innerText().catch(() => '')
const mock = (fn) => pg.evaluate(fn)
const docs = () => pg.evaluate(() => JSON.parse(sessionStorage.getItem('__mockdb') || '{}'))
const wait = (ms = 250) => pg.waitForTimeout(ms)
/** 真按一次 Ctrl+V（焦点在收件框里） */
const ensureOpen = async (c) => { if (!(await c.locator('.detail').count())) { await c.locator('.card-main').click(); await wait() } }
const pasteInBox = async (text) => { await setClip(text); await pg.locator('#capture').focus(); await pg.keyboard.press('Control+V') }

try {
  await pg.goto(URL, { waitUntil: 'load' })
  await wait(600)

  // ---------------------------------------------------------------- 一打开
  t('空的时候摆着示例卡，标着「示例」', (await cards().count()) === 3 && (await pg.locator('.badge', { hasText: '示例' }).count()) === 3)
  t('告诉她：粘贴即收下、Claude 整理、手机电脑同一份', (await pg.locator('.cap-hint').innerText()).includes('Claude'), await pg.locator('.cap-hint').innerText())

  // ---------------------------------------------------------------- 收
  await pasteInBox(CONTACT)
  await wait(120)
  const c1 = card('138 1234 5678')
  t('粘贴即收下：卡片马上出现', (await cards().count()) === 1)
  t('……先显示「Claude 在整理」', (await c1.locator('.busy-t').count()) === 1)
  t('……Claude 想的时候，本地认出来的电话已经摆上了', (await c1.locator('.row-v', { hasText: '138 1234 5678' }).count()) === 1)
  t('收下之后输入框清空', (await pg.locator('#capture').inputValue()) === '')
  await wait(700)
  t('Claude 整理完：标题换成它起的', (await c1.locator('h3').innerText()) === 'Lily Chen', await c1.locator('h3').innerText())
  t('……不再转圈', (await c1.locator('.busy-t').count()) === 0)
  t('……示例卡消失', (await pg.locator('.badge', { hasText: '示例' }).count()) === 0)
  const calls = await mock(() => window.__mock.calls.map((c) => c.tier))
  t('第一次整理用快速档（秒回）', calls.length === 1 && calls[0] === 'quick', JSON.stringify(calls))
  const saved = Object.entries(await docs())
  t('存进了她自己那一格（data/users/<id>/…）', saved.length === 1 && saved[0][0].startsWith('data/users/u_test/lib/items/'), saved.map(([p]) => p).join())
  const order = await mock(() => window.__mock.writes.map((w) => w[0]).join(','))
  t('先建再改：没有对不存在的文档 update', order === 'set,update', order)

  // ---------------------------------------------------------------- 复制：一格、整理版、给 AI、原文
  await c1.locator('.row', { hasText: '手机' }).click(); await wait()
  t('点「手机」那一行：只复制号码', (await clip()) === '138 1234 5678', await clip())
  t('……那一行说「已复制」', (await c1.locator('.row.done').innerText()).includes('已复制'))
  await c1.locator('.copies .btn', { hasText: '复制整理版' }).click(); await wait()
  const txt = await clip()
  t('复制整理版：标题 + 字段', txt.startsWith('Lily Chen\n') && txt.includes('手机：138 1234 5678'), JSON.stringify(txt.slice(0, 30)))
  await c1.locator('.copies .btn', { hasText: '复制给 AI' }).click(); await wait()
  const ai = await clip()
  t('复制给 AI：先是那句指令，后面带着整理版和原文', ai.startsWith('帮我给 Lily 写一条初次联系的微信。') && ai.includes('【原文】'), JSON.stringify(ai.slice(0, 24)))
  await c1.locator('.copies .btn', { hasText: '复制原文' }).click(); await wait()
  t('复制原文：一字不差', (await clip()) === CONTACT)
  await c1.locator('.ask').click(); await wait()
  t('点「下一步可以这样问 AI」那块：也是复制给 AI 的版本', (await clip()) === ai)

  // ---------------------------------------------------------------- 在页面任何地方粘贴
  await setClip(MEET)
  await pg.locator('.group-h').first().click()
  await pg.keyboard.press('Control+V')
  await wait(900)
  const c2 = card('王总的会改到周五')
  t('在页面空白处 Ctrl+V 也算收下', (await cards().count()) === 2)
  t('新收的那张自动展开，上一张收起', (await c2.locator('.detail').count()) === 1 && (await c1.locator('.detail').count()) === 0)
  t('Claude 把相对时间换成了具体日期', (await c2.locator('.row-v').first().innerText()).includes('9月26日'))

  // 收起来的卡上，字段小条点一下就复制
  await c1.locator('.chip', { hasText: '姓名' }).click(); await wait()
  t('收起的卡：点字段小条，复制那一格', (await clip()) === 'Lily Chen')
  await c1.locator('.copy-ic').click(); await wait()
  t('收起的卡：右上角复制按钮 = 整理版', (await clip()).startsWith('Lily Chen\n'))

  // ---------------------------------------------------------------- 待办
  await c2.locator('.todo').first().click(); await wait(300)
  const meetDoc = Object.values(await docs()).find((d) => d.title === '王总的会改到周五')
  t('勾掉一个待办：存进去了', meetDoc?.todos?.[0]?.done === true, JSON.stringify(meetDoc?.todos))
  await c2.locator('.copies .btn', { hasText: '复制整理版' }).click(); await wait()
  t('勾掉的待办不再出现在整理版里', !(await clip()).includes('带上竞品分析') && (await clip()).includes('回复王总确认'))

  // ---------------------------------------------------------------- 重复的
  await pasteInBox(MEET); await wait(400)
  t('同一段再贴一次：不重复收，告诉她收过了', (await cards().count()) === 2 && (await toast()).includes('收过'), await toast())

  // ---------------------------------------------------------------- 筛选 / 搜索
  await pg.locator('.kinds button', { hasText: '日程' }).click(); await wait()
  t('按类型看：只剩日程', (await cards().count()) === 1 && (await cards().first().innerText()).includes('王总'))
  await pg.locator('.kinds button', { hasText: '全部' }).click(); await wait()
  await pg.locator('.ghost[aria-label="搜索"]').click()
  await pg.locator('#search').fill('1208'); await wait()
  t('搜「1208」：找到那场会', (await cards().count()) === 1 && (await cards().first().innerText()).includes('王总'))
  await pg.locator('#search').fill('上海'); await wait()
  t('搜不到时说一声', (await pg.locator('.none').innerText()).includes('上海'))
  await pg.locator('.ghost[aria-label="搜索"]').click(); await wait()
  t('关掉搜索：全都回来', (await cards().count()) === 2)

  // ---------------------------------------------------------------- 多选
  await pg.locator('.ghost', { hasText: '选择' }).click(); await wait()
  await cards().nth(0).locator('.tick').click()
  await cards().nth(1).locator('.card-main').click(); await wait()
  t('多选：勾卡片、点卡片都能选上', (await pg.locator('.pick-n').innerText()).includes('2'))
  await pg.locator('.pickbar .btn', { hasText: '复制整理版' }).click(); await wait()
  const mt = await clip()
  t('多选复制整理版：编好号的合集', mt.startsWith('1. ') && mt.includes('\n\n2. '), JSON.stringify(mt.slice(0, 20)))
  await pg.locator('.pickbar .btn', { hasText: '复制给 AI' }).click(); await wait()
  t('多选复制给 AI：一段能直接问的', (await clip()).startsWith('下面是我收集的 2 条信息'))
  await pg.locator('.ghost', { hasText: '完成' }).click(); await wait()
  t('点「完成」退出多选', (await pg.locator('.pickbar').count()) === 0)

  // ---------------------------------------------------------------- 删除 + 撤销
  await ensureOpen(card('王总'))
  await card('王总').locator('.acts .danger').click(); await wait(300)
  t('删除', (await cards().count()) === 1)
  await pg.locator('.toast button', { hasText: '撤销' }).click(); await wait(300)
  t('删了能撤销', (await cards().count()) === 2)

  // ---------------------------------------------------------------- 置顶 / 改标题
  await ensureOpen(card('Lily Chen'))
  await card('Lily Chen').locator('.acts button', { hasText: '置顶' }).click(); await wait(300)
  t('置顶：排到最上面，单独一组', (await pg.locator('.group-h').first().innerText()) === '置顶' && (await cards().first().innerText()).includes('Lily'))
  await card('Lily Chen').locator('.acts button', { hasText: '改标题' }).click()
  await pg.locator('.title-in').fill('Lily · 增长负责人')
  await pg.locator('.title-in').press('Enter'); await wait(300)
  t('改标题：存进去了', Object.values(await docs()).some((d) => d.title === 'Lily · 增长负责人'))

  // ---------------------------------------------------------------- 刷新
  await pg.reload({ waitUntil: 'load' }); await wait(700)
  t('刷新之后都还在（存的是数据库，不是这一页）', (await cards().count()) === 2 && (await cards().first().innerText()).includes('Lily · 增长负责人'))

  // ---------------------------------------------------------------- Claude 忙
  await mock(() => { window.__mock.fail = 'rate_limited' })
  await pasteInBox(NOTE); await wait(700)
  // 整理完标题会变，按 id 找它，别按字
  const c3 = pg.locator('#' + await card('会员体系').getAttribute('id'))
  t('Claude 忙：卡照样收下，说清楚怎么了', (await c3.locator('.note').innerText()).includes('忙'), await c3.locator('.note').innerText().catch(() => ''))
  await mock(() => { window.__mock.fail = null })
  await c3.locator('.acts button', { hasText: '重新整理' }).click(); await wait(900)
  t('点「重新整理」：整理好了', (await c3.locator('.note').count()) === 0 && (await c3.locator('h3').innerText()) === '一条笔记')
  const last = await mock(() => window.__mock.calls.at(-1))
  t('重新整理用更仔细的档，而且不拿缓存里的旧答案', last.tier === 'default' && last.cache === false, JSON.stringify({ tier: last.tier, cache: last.cache }))

  // ---------------------------------------------------------------- 手打的也能收
  await pg.locator('#capture').fill('周五前把季度复盘 PPT 发给王总')
  await pg.locator('.take').click(); await wait(700)
  t('手打的：点「收下」', (await cards().count()) === 4)

  // ---------------------------------------------------------------- Claude 用不了
  await mock(() => { window.__mock.fail = 'not_granted' })
  await pasteInBox('第一条不让用 Claude 的'); await wait(700)
  const before = await mock(() => window.__mock.calls.length)
  t('不让用 Claude：卡照样收下，只做本地整理', (await card('第一条不让用').getAttribute('data-status')) === 'local')
  t('……顶上的提示改口', (await pg.locator('.cap-hint').innerText()).includes('没开 Claude'), await pg.locator('.cap-hint').innerText())
  await pasteInBox('第二条也不让用'); await wait(700)
  t('……之后不再去问 Claude（不反复弹同意框）', (await mock(() => window.__mock.calls.length)) === before)

  t('全程没有页面报错', errs.length === 0, errs.slice(0, 2).join(' | '))
} finally {
  await b.close()
}
process.exit(fail ? 1 : 0)
