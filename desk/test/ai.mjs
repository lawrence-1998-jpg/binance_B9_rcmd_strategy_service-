/**
 * 在设置里填了自己的 Claude API Key 之后（mock-anthropic.mjs 装一个假的 api.anthropic.com）：
 *   填 Key（填错、测不过、测过）→ Claude 整理 → 截图读字 → 忙 / 不接 / 断网时怎么退 → 重新整理
 *   → 问一问 → Key 失效时停手 → 关掉并删除 Key 之后一个请求都不再发。
 *
 * 核对的是真正发出去的请求：模型、Key 放在哪、结构化输出、fallback、读图。
 */
import pkg from 'playwright'
import { mockAnthropic, TEST_KEY } from './mock-anthropic.mjs'
const { chromium, devices } = pkg

const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const CONTACT = 'Lily Chen｜增长策略负责人\n手机 138 1234 5678\n邮箱 lily.chen@example.com'
const MEET = '王总：周四下午的会挪到周五上午 10 点吧，地点还是国贸三期 B 座 1208。记得带上次那版竞品分析，财务的 Linda 也会来。'
const NOTE = '想法：会员体系的核心问题可能不是权益太少，而是用户根本不知道自己有哪些权益。'

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'] })
const api = await mockAnthropic(ctx)
const pg = await ctx.newPage()
const errs = []
pg.on('pageerror', (e) => errs.push(e.message))

const clip = () => pg.evaluate(() => navigator.clipboard.readText())
const setClip = (s) => pg.evaluate((x) => navigator.clipboard.writeText(x), s)
const cards = () => pg.locator('.list article.card')
const card = (text) => cards().filter({ hasText: text }).first()
const byId = async (text) => pg.locator('#' + await card(text).getAttribute('id'))
const wait = (ms = 250) => pg.waitForTimeout(ms)
const pasteInBox = async (text) => { await setClip(text); await pg.locator('#capture').focus(); await pg.keyboard.press('Control+V') }
const msgs = () => api.calls.filter((c) => c.path === '/v1/messages')
const openSettings = async () => { await pg.locator('.ghost[aria-label="设置"]').click(); await wait(200) }
const closeSettings = async () => { await pg.locator('.sheet .ghost[aria-label="关闭设置"]').click(); await wait(150) }

try {
  await pg.goto(URL, { waitUntil: 'load' })
  await wait(500)

  // ---------------------------------------------------------------- 填 Key
  await openSettings()
  await pg.locator('#apikey').fill('abc123')
  await pg.locator('.sheet .btn', { hasText: '保存并开启' }).click(); await wait(200)
  t('填了个不像 Key 的：当场说，不发请求', (await pg.locator('.set-msg').innerText()).includes('sk-ant-') && api.calls.length === 0)
  api.fail = 'bad_key'
  await pg.locator('#apikey').fill(TEST_KEY)
  await pg.locator('.sheet .btn', { hasText: '保存并开启' }).click(); await wait(700)
  t('Key 测不过：说清楚，也不存', (await pg.locator('.set-msg').innerText()).includes('Key 不对') && (await pg.evaluate(() => localStorage.getItem('suishou.apikey'))) === null)
  api.fail = null
  await pg.locator('.sheet .btn', { hasText: '保存并开启' }).click(); await wait(700)
  t('Key 测过了：开启，存在这台设备上', (await pg.locator('.set-msg').innerText()).includes('已开启') && (await pg.evaluate(() => localStorage.getItem('suishou.apikey'))) === TEST_KEY)
  t('……设置里显示「已开」，Key 只露最后 4 位', (await pg.locator('.sheet .pill').innerText()) === '已开' && (await pg.locator('.key-on').innerText()).includes('…' + TEST_KEY.slice(-4)) && !(await pg.locator('.sheet').innerText()).includes(TEST_KEY))
  const probe = api.calls.at(-1)
  t('测 Key 用的是查模型（不花钱），Key 放在 x-api-key 头里', probe.method === 'GET' && probe.path === '/v1/models/claude-opus-5' && probe.key === TEST_KEY, `${probe.method} ${probe.path}`)
  await closeSettings()
  t('顶上的提示改口：Claude 帮你整理', (await pg.locator('.cap-hint').innerText()).includes('Claude 帮你整理'))

  // ---------------------------------------------------------------- Claude 整理
  await pasteInBox(CONTACT)
  await wait(120)
  const c1 = await byId('138 1234 5678')
  t('粘贴即收下：先显示「Claude 在整理」', (await c1.locator('.busy-t').count()) === 1)
  t('……Claude 想的时候，本地认出来的电话已经摆上了', (await c1.locator('.row-v', { hasText: '138 1234 5678' }).count()) === 1)
  await wait(700)
  t('Claude 整理完：标题换成它起的', (await c1.locator('h3').innerText()) === 'Lily Chen', await c1.locator('h3').innerText())
  t('……不再转圈', (await c1.locator('.busy-t').count()) === 0 && (await c1.getAttribute('data-status')) === 'done')
  const m1 = msgs().at(-1)
  t('请求：claude-opus-5，effort low', m1.body.model === 'claude-opus-5' && m1.body.output_config?.effort === 'low', JSON.stringify(m1.body.output_config?.effort))
  t('请求：结构化输出（json_schema，kind 只能是那 11 种）', m1.body.output_config?.format?.type === 'json_schema' && m1.body.output_config.format.schema.properties.kind.enum.length === 11)
  t('请求：开着服务端 fallback（主力模型不接时自动换一个接着做）', m1.body.fallbacks === 'default' && m1.beta.includes('server-side-fallback-2026-07-01'), m1.beta)
  t('请求：原文原样放在指令里', m1.prompt.includes('<<<\n' + CONTACT + '\n>>>'))
  await c1.locator('.copies .btn', { hasText: '复制给 AI' }).click(); await wait()
  t('复制给 AI：换成 Claude 想好的那句', (await clip()).startsWith('帮我给 Lily 写一条初次联系的微信。'))

  await pasteInBox(MEET); await wait(900)
  const c2 = card('王总的会改到周五')
  t('Claude 把相对时间换成了具体日期', (await c2.locator('.row-v').first().innerText()).includes('9月26日'))

  // ---------------------------------------------------------------- 截图：Claude 读字
  const pasteImage = () => pg.evaluate(async () => {
    const c = document.createElement('canvas'); c.width = 600; c.height = 900
    const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 600, 900)
    g.fillStyle = '#111'; g.font = '40px sans-serif'; g.fillText('报价单 ¥36,000', 40, 120)
    const blob = await new Promise((r) => c.toBlob(r, 'image/png'))
    const dt = new DataTransfer()
    dt.items.add(new File([blob], 'shot.png', { type: 'image/png' }))
    document.querySelector('#capture').focus()
    document.querySelector('#capture').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
  })
  await pasteImage(); await wait(200)
  const s1 = pg.locator('.card.open')
  t('粘贴截图：Claude 在读', (await s1.locator('.busy-t').count()) === 1 && (await s1.locator('.badge', { hasText: '截图' }).count()) === 1)
  await wait(800)
  t('Claude 读完：按图里的内容起了标题、拆了字段', (await s1.locator('h3').innerText()) === '年费报价截图' && (await s1.locator('.row', { hasText: '年费' }).count()) === 1)
  await s1.locator('.raw-t').click()
  t('「看图里的字」：Claude 转写出来的原文', (await s1.locator('.raw pre').innerText()).includes('报价单'))
  const shotCall = msgs().at(-1)
  t('图随请求一起发过去（base64 JPEG），指令是读图的，不带空原文', shotCall.hasImage && shotCall.imageType === 'image/jpeg' && shotCall.prompt.includes('读图') && !shotCall.prompt.includes('<<<'))
  t('读截图的结构化输出要 raw（图里的字）', shotCall.body.output_config.format.schema.required.includes('raw'))
  await s1.locator('.copies .btn', { hasText: '复制原文' }).click(); await wait()
  t('截图卡「复制原文」= 图里的字', (await clip()).startsWith('报价单'))
  await s1.locator('.shot-copy').click(); await wait(600)
  const types = await pg.evaluate(async () => { try { return (await navigator.clipboard.read()).flatMap((i) => i.types) } catch (e) { return ['读不了: ' + e.message] } })
  t('读过字的截图：图上还有「复制图片」', types.includes('image/png'), JSON.stringify(types))

  // ---------------------------------------------------------------- 出岔子
  api.fail = 'rate_limited'
  await pasteInBox(NOTE); await wait(700)
  const c3 = await byId('会员体系')
  t('Claude 忙：卡照样收下，本地整理的留着，说清楚怎么了', (await c3.locator('.note').innerText()).includes('忙') && (await c3.getAttribute('data-status')) === 'failed', await c3.locator('.note').innerText().catch(() => ''))
  api.fail = null
  await c3.locator('.acts button', { hasText: '重新整理' }).click(); await wait(900)
  t('点「重新整理」：整理好了', (await c3.locator('.note').count()) === 0 && (await c3.locator('h3').innerText()) === '一条笔记')
  t('重新整理让 Claude 想得仔细些（effort medium）', msgs().at(-1).body.output_config.effort === 'medium')

  api.fail = 'refusal'
  await pasteInBox('一条 Claude 不接的'); await wait(700)
  t('Claude 不接：卡留着，说清楚', (await (await byId('一条 Claude 不接的')).locator('.note').innerText()).includes('没接'))

  api.fail = 'offline'
  await pasteInBox('明天下午 3 点和张三碰一下 139 0000 1111'); await wait(2500)
  const c5 = await byId('张三')
  t('断网：卡留着，本地认出来的电话还在，说清楚', (await c5.locator('.note').innerText()).includes('没连上网') && (await c5.locator('.row-v', { hasText: '139 0000 1111' }).count()) === 1, await c5.locator('.note').innerText().catch(() => ''))
  api.fail = null

  // ---------------------------------------------------------------- 问一问
  await pg.locator('.ghost[aria-label="搜索"]').click()
  await pg.locator('#search').fill('Lily 电话'); await wait()
  t('搜索框里打一句话：出现「问 Claude」', (await pg.locator('.ask-go').innerText()).includes('Lily 电话'))
  await pg.locator('.ask-go').click(); await wait(900)
  const ans = await pg.locator('.answer-t').innerText()
  t('回答：直接给出电话', ans.includes('138 1234 5678'), ans)
  t('回答里标了出处，下面列出那张卡', (await pg.locator('.answer-t .ref').count()) === 1 && (await pg.locator('.src').innerText()).includes('Lily'))
  const askCall = msgs().at(-1)
  t('问的时候流式返回，带上了她收的卡片', askCall.stream && askCall.prompt.includes('我的问题：Lily 电话') && askCall.body.fallbacks === 'default')
  await pg.locator('.answer .mini', { hasText: '复制回答' }).click(); await wait()
  const copied = await clip()
  t('复制回答：[编号] 换成了卡片名', copied.includes('138 1234 5678') && !/\[\d+\]/.test(copied) && copied.includes('（Lily'), copied)
  await pg.locator('.src').first().click(); await wait(400)
  t('点出处：跳到那张卡并展开', (await card('Lily Chen').locator('.detail').count()) === 1)
  await pg.locator('#search').fill('上海办公室地址')
  await pg.locator('#search').press('Enter'); await wait(900)
  t('回车也能问；收的东西里没有就直说', (await pg.locator('.answer-t').innerText()).includes('没有'))
  await pg.locator('.ghost[aria-label="搜索"]').click(); await wait()

  // ---------------------------------------------------------------- Key 失效
  api.fail = 'bad_key'
  await pasteInBox('第一条撞上失效的 Key'); await wait(700)
  t('Key 失效：卡照样收下，说清楚去设置里换', (await (await byId('第一条撞上失效')).locator('.note').innerText()).includes('设置'))
  t('……顶上的提示改口，齿轮上有个红点', (await pg.locator('.cap-hint').innerText()).includes('Key 用不了') && (await pg.locator('.ghost.warn-dot').count()) === 1)
  const before = api.calls.length
  await pasteInBox('第二条也不该去撞'); await wait(700)
  t('……之后不再去撞（不白发请求）', api.calls.length === before && (await (await byId('第二条也不该去撞')).getAttribute('data-status')) === 'local')
  await openSettings()
  t('……设置里标着「用不了」', (await pg.locator('.sheet .pill').innerText()) === '用不了')
  api.fail = null
  await pg.locator('.sheet .btn', { hasText: '测一下' }).click(); await wait(700)
  t('Key 又能用了：「测一下」通过，红点消失', (await pg.locator('.set-msg').innerText()).includes('能用') && (await pg.locator('.sheet .pill').innerText()) === '已开')
  await closeSettings()
  const local = await byId('第二条也不该去撞')
  if (!(await local.locator('.detail').count())) { await local.locator('.card-main').click(); await wait() }
  await local.locator('.acts button', { hasText: '让 Claude 整理' }).click(); await wait(900)
  t('只做了本地整理的卡：点「让 Claude 整理」补上', (await local.getAttribute('data-status')) === 'done')

  // ---------------------------------------------------------------- 关掉
  await openSettings()
  await pg.locator('.sheet .btn', { hasText: '关掉并删除 Key' }).click(); await wait(200)
  t('关掉：Key 从这台设备上删了', (await pg.evaluate(() => localStorage.getItem('suishou.apikey'))) === null && (await pg.locator('.sheet .pill').innerText()) === '可选')
  await closeSettings()
  const n = api.calls.length
  await pasteInBox('关掉之后收的一条 138 0000 0000'); await wait(700)
  t('关掉之后：一个请求都不再发，照样本地整理', api.calls.length === n && (await (await byId('关掉之后收的一条')).getAttribute('data-status')) === 'local')
  await pg.locator('.ghost[aria-label="搜索"]').click()
  await pg.locator('#search').fill('Lily'); await wait()
  t('……搜索照样能用，不再出现「问 Claude」', (await pg.locator('.ask-go').count()) === 0 && (await cards().count()) >= 1)

  t('每个发出去的请求都带着她的 Key、都是发给 api.anthropic.com 的', api.calls.every((c) => c.key === TEST_KEY))
  t('全程没有页面报错', errs.length === 0, errs.slice(0, 2).join(' | '))
} finally {
  await b.close()
}
process.exit(fail ? 1 : 0)
