/**
 * 本地版把整条路走一遍（没填 Claude 的 Key —— 这是默认的样子）：
 *   收 → 本地整理 → 各种复制 → 待办 → 筛选 / 搜索 → 多选 → 删除撤销 → 置顶 → 改标题 → 刷新还在
 *   → 清单 → 截图（没有 AI 也收，能复制图片）→ 从别的 App 分享进来 → 换个问法 / 我的问法
 *   → 加到日历 / 存到通讯录 → 导出 / 导入备份 → 老版本的数据搬过来。
 *
 * 复制的每一步都去读真的剪贴板，不看按钮上写了什么。
 * 存进去的每一步都去读真的 IndexedDB。
 */
import pkg from 'playwright'
import { readFileSync } from 'node:fs'
const { chromium, devices } = pkg

const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const CONTACT = 'Lily Chen｜增长策略负责人\n手机 138 1234 5678\n邮箱 lily.chen@example.com'
const MEET = '王总：周四下午的会挪到周五上午 10 点吧，地点还是国贸三期 B 座 1208。记得带上次那版竞品分析，财务的 Linda 也会来。'
const LIST = '- [ ] 订周五的会议室\n- [x] 发邮件给 Linda\n- [ ] 准备报价单'

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'], acceptDownloads: true })
const outside = []
ctx.on('request', (r) => { if (!r.url().startsWith(new globalThis.URL(URL).origin) && !/^(data|blob):/.test(r.url())) outside.push(r.url()) })
const pg = await ctx.newPage()
const errs = []
pg.on('pageerror', (e) => errs.push(e.message))

const clip = () => pg.evaluate(() => navigator.clipboard.readText())
const setClip = (s) => pg.evaluate((x) => navigator.clipboard.writeText(x), s)
const cards = () => pg.locator('.list article.card')
const card = (text) => cards().filter({ hasText: text }).first()
const toast = () => pg.locator('.toast').innerText().catch(() => '')
const wait = (ms = 250) => pg.waitForTimeout(ms)
/** 真的去 IndexedDB 里读 —— 「存上了」以盘上为准 */
const disk = () => pg.evaluate(() => new Promise((ok, no) => {
  const r = indexedDB.open('suishou')
  r.onerror = () => no(r.error)
  r.onsuccess = () => {
    const q = r.result.transaction('items').objectStore('items').getAll()
    q.onsuccess = () => { ok(q.result); r.result.close() }
  }
}))
const ensureOpen = async (c) => { if (!(await c.locator('.detail').count())) { await c.locator('.card-main').click(); await wait() } }
const pasteInBox = async (text) => { await setClip(text); await pg.locator('#capture').focus(); await pg.keyboard.press('Control+V') }

try {
  await pg.goto(URL, { waitUntil: 'load' })
  await wait(600)

  // ---------------------------------------------------------------- 一打开
  t('空的时候摆着示例卡，标着「示例」', (await cards().count()) === 3 && (await pg.locator('.badge', { hasText: '示例' }).count()) === 3)
  t('告诉她：粘贴即收下、只存在这台设备', (await pg.locator('.cap-hint').innerText()).includes('只存在这台设备'), await pg.locator('.cap-hint').innerText())
  t('右上角有「设置」', (await pg.locator('.ghost[aria-label="设置"]').count()) === 1)

  // ---------------------------------------------------------------- 收
  await pasteInBox(CONTACT)
  await wait(200)
  const c1 = card('138 1234 5678')
  t('粘贴即收下：卡片马上出现', (await cards().count()) === 1)
  t('……不转圈（本地整理，当场就好）', (await c1.locator('.busy-t').count()) === 0 && (await c1.getAttribute('data-status')) === 'local')
  t('……认出了电话和邮箱', (await c1.locator('.row-v', { hasText: '138 1234 5678' }).count()) === 1 && (await c1.locator('.row-v', { hasText: 'lily.chen@example.com' }).count()) === 1)
  t('……类型是联系人', (await c1.locator('.kind').innerText()) === '联系人')
  t('收下之后输入框清空', (await pg.locator('#capture').inputValue()) === '')
  t('……示例卡消失', (await pg.locator('.badge', { hasText: '示例' }).count()) === 0)
  const saved = await disk()
  t('存进了这台设备的 IndexedDB', saved.length === 1 && saved[0].raw === CONTACT, `${saved.length} 条`)
  t('没有「重新整理」（没开 Claude，本地那遍已经是全部）', (await c1.locator('.acts button', { hasText: /整理|读图/ }).count()) === 0)

  // ---------------------------------------------------------------- 复制：一格、整理版、给 AI、原文
  await c1.locator('.row', { hasText: '电话' }).click(); await wait()
  t('点「电话」那一行：只复制号码', (await clip()) === '138 1234 5678', await clip())
  t('……那一行说「已复制」', (await c1.locator('.row.done').innerText()).includes('已复制'))
  await c1.locator('.copies .btn', { hasText: '复制整理版' }).click(); await wait()
  const txt = await clip()
  t('复制整理版：标题 + 字段', txt.startsWith('Lily Chen｜增长策略负责人\n') && txt.includes('电话：138 1234 5678'), JSON.stringify(txt.slice(0, 40)))
  await c1.locator('.ask').click(); await wait()
  const ai = await clip()
  t('「拿去问 AI」那块就是「复制给 AI」：按联系人配好的那句开头，后面带着整理版和原文', ai.startsWith('帮我把这个人整理成通讯录格式') && ai.includes('【整理好的信息】') && ai.includes('【原文】'), JSON.stringify(ai.slice(0, 24)))
  t('……那块上的按钮说「已复制」', (await c1.locator('.ask-btn').innerText()).includes('已复制'))
  await c1.locator('.copies .btn', { hasText: '复制原文' }).click(); await wait()
  t('复制原文：一字不差', (await clip()) === CONTACT)
  t('「复制给 AI」只有一处（不在下面那排里重复）', (await c1.locator('.copies .btn', { hasText: '复制给 AI' }).count()) === 0 && (await c1.locator('.ask').count()) === 1)

  // ---------------------------------------------------------------- 在页面任何地方粘贴
  await setClip(MEET)
  await pg.locator('.group-h').first().click()
  await pg.keyboard.press('Control+V')
  await wait(400)
  const c2 = card('国贸三期')
  t('在页面空白处 Ctrl+V 也算收下', (await cards().count()) === 2)
  t('新收的那张自动展开，上一张收起', (await c2.locator('.detail').count()) === 1 && (await c1.locator('.detail').count()) === 0)
  const meetVals = await c2.locator('.row-v').allInnerTexts()
  t('本地认出了改到的时间和地点（不把「周四」当时间）', meetVals.includes('周五上午 10 点') && meetVals.includes('国贸三期 B 座 1208') && !meetVals.includes('周四'), JSON.stringify(meetVals))
  t('……类型是日程', (await c2.locator('.kind').innerText()) === '日程')
  t('……「记得带…」变成了待办', (await c2.locator('.todo').innerText()).includes('带上次那版竞品分析'))

  // 收起来的卡上，字段小条点一下就复制
  await c1.locator('.chip', { hasText: '电话' }).click(); await wait()
  t('收起的卡：点字段小条，复制那一格', (await clip()) === '138 1234 5678')
  await c1.locator('.copy-ic').click(); await wait()
  t('收起的卡：右上角复制按钮 = 整理版', (await clip()).startsWith('Lily Chen｜'))

  // ---------------------------------------------------------------- 待办
  await c2.locator('.todo').first().click(); await wait(300)
  const meetDoc = (await disk()).find((d) => d.raw === MEET)
  t('勾掉一个待办：存进去了', meetDoc?.todos?.[0]?.done === true, JSON.stringify(meetDoc?.todos))
  await c2.locator('.copies .btn', { hasText: '复制整理版' }).click(); await wait()
  t('勾掉的待办不再出现在整理版里', !(await clip()).includes('待办'))

  // ---------------------------------------------------------------- 重复的
  await pasteInBox(MEET); await wait(300)
  t('同一段再贴一次：不重复收，告诉她收过了', (await cards().count()) === 2 && (await toast()).includes('收过'), await toast())

  // ---------------------------------------------------------------- 筛选 / 搜索
  await pg.locator('.kinds button', { hasText: '日程' }).click(); await wait()
  t('按类型看：只剩日程', (await cards().count()) === 1 && (await cards().first().innerText()).includes('王总'))
  await pg.locator('.kinds button', { hasText: '全部' }).click(); await wait()
  await pg.locator('.ghost[aria-label="搜索"]').click()
  await pg.locator('#search').fill('1208'); await wait()
  t('搜「1208」：找到那场会', (await cards().count()) === 1 && (await cards().first().innerText()).includes('王总'))
  t('没开 Claude：搜索框里没有「问 Claude」', (await pg.locator('.ask-go').count()) === 0)
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
  t('删除', (await cards().count()) === 1 && (await disk()).length === 1)
  await pg.locator('.toast button', { hasText: '撤销' }).click(); await wait(300)
  t('删了能撤销（盘上也回来了）', (await cards().count()) === 2 && (await disk()).length === 2)

  // ---------------------------------------------------------------- 置顶 / 改标题
  await ensureOpen(card('Lily Chen'))
  await card('Lily Chen').locator('.acts button', { hasText: '置顶' }).click(); await wait(300)
  t('置顶：排到最上面，单独一组', (await pg.locator('.group-h').first().innerText()) === '置顶' && (await cards().first().innerText()).includes('Lily'))
  await card('Lily Chen').locator('.acts button', { hasText: '改标题' }).click()
  await pg.locator('.title-in').fill('Lily · 增长负责人')
  await pg.locator('.title-in').press('Enter'); await wait(300)
  t('改标题：存进去了', (await disk()).some((d) => d.title === 'Lily · 增长负责人'))

  // ---------------------------------------------------------------- 刷新
  await pg.reload({ waitUntil: 'load' }); await wait(700)
  t('刷新之后都还在（存在这台设备上）', (await cards().count()) === 2 && (await cards().first().innerText()).includes('Lily · 增长负责人'))

  // ---------------------------------------------------------------- 清单
  await pasteInBox(LIST); await wait(300)
  const c3 = pg.locator('.card.open')
  t('勾框清单：一行一条待办，打了勾的已经勾上', (await c3.locator('.todo').count()) === 3 && (await c3.locator('.todo.did').count()) === 1)
  t('……标题是「第一件 等 3 件」，类型是待办', (await c3.locator('h3').innerText()) === '订周五的会议室 等 3 件' && (await c3.locator('.kind').innerText()) === '待办')

  // ---------------------------------------------------------------- 截图（没开 Claude 也收）
  const ICON = new globalThis.URL('../public/icons/icon-192.png', import.meta.url).pathname
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
  t('收件框旁边有「截图」按钮（不需要 Claude）', (await pg.locator('.shot-btn').count()) === 1)
  const n0 = await cards().count()
  await pasteImage(); await wait(400)
  const s1 = pg.locator('.card.open')
  t('粘贴一张截图：收下，标着「截图」，图就在卡上', (await cards().count()) === n0 + 1 && (await s1.locator('.badge', { hasText: '截图' }).count()) === 1 && ((await s1.locator('.shot img').getAttribute('src')) ?? '').startsWith('data:image/jpeg'))
  t('……说清楚：读不了图里的字，但能复制图片', (await s1.locator('.note').innerText()).includes('复制图片'))
  t('……不转圈', (await s1.locator('.busy-t').count()) === 0)
  await s1.locator('.copies .btn', { hasText: '复制图片' }).click(); await wait(600)
  const types = await pg.evaluate(async () => { try { return (await navigator.clipboard.read()).flatMap((i) => i.types) } catch (e) { return ['读不了: ' + e.message] } })
  t('「复制图片」：剪贴板里是一张 PNG，贴进哪家 AI 都行', types.includes('image/png'), JSON.stringify(types))
  t('……没有空的「复制原文」「看原文」', (await s1.locator('.copies .btn', { hasText: '复制原文' }).count()) === 0 && (await s1.locator('.raw-t').count()) === 0)
  const shotDoc = (await disk()).find((d) => d.img)
  t('卡里存了一份压缩过的图', typeof shotDoc?.img === 'string' && shotDoc.img.length <= 600_000, `${shotDoc?.img?.length ?? 0} 字符`)
  const n1 = await cards().count()
  await pg.locator('#shot').setInputFiles(ICON); await wait(500)
  t('点「截图」从相册挑一张：也收下了', (await cards().count()) === n1 + 1)

  // ---------------------------------------------------------------- 手打的也能收
  const n2 = await cards().count()
  await pg.locator('#capture').fill('周五前把季度复盘 PPT 发给王总')
  await pg.locator('.take').click(); await wait(300)
  const c4 = pg.locator('.card.open')
  t('手打的：点「收下」', (await cards().count()) === n2 + 1)
  t('……认出是待办、截止周五前', (await c4.locator('.kind').innerText()) === '待办' && (await c4.locator('.row', { hasText: '截止' }).innerText()).includes('周五前'))

  // ---------------------------------------------------------------- 从别的 App 分享进来（安卓装成 App 后）
  const shareUrl = URL + '?title=' + encodeURIComponent('一篇文章') + '&text=' + encodeURIComponent('值得一看') + '&url=' + encodeURIComponent('https://example.com/a')
  await pg.goto(shareUrl, { waitUntil: 'load' }); await wait(700)
  t('分享进来的：当场收下', (await cards().filter({ hasText: 'example.com/a' }).count()) === 1)
  t('……地址栏里的参数清掉了（刷新不会再收一次）', !(await pg.evaluate(() => location.search)))
  const total = await cards().count()

  // ---------------------------------------------------------------- 换个问法
  const meetCard = card('国贸三期')
  await ensureOpen(meetCard)
  t('聊天里的「王总：」拎成了「来自」', (await meetCard.locator('.row', { hasText: '来自' }).innerText()).includes('王总'))
  await meetCard.locator('.alt', { hasText: '起草确认回复' }).click(); await wait()
  const alt = await clip()
  t('换个问法：点「起草确认回复」，复制的是这句 + 整理版 + 原文', alt.startsWith('帮我起草一条回复，确认时间和地点') && alt.includes('【原文】') && alt.includes('国贸三期'), JSON.stringify(alt.slice(0, 30)))
  t('……那个按钮说「已复制」', (await meetCard.locator('.alt.done').innerText()) === '已复制')

  // ---------------------------------------------------------------- 加到日历 / 存到通讯录
  const [icsDl] = await Promise.all([pg.waitForEvent('download'), meetCard.locator('.copies .btn', { hasText: '加到日历' }).click()])
  const ics = readFileSync(await icsDl.path(), 'utf8')
  const d0 = ics.match(/DTSTART:(\d{4})(\d{2})(\d{2})T100000/)
  const fri = d0 && new Date(+d0[1], +d0[2] - 1, +d0[3])
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const ahead = fri ? Math.round((fri - today) / 86_400_000) : -1
  t('日程卡「加到日历」：一个 .ics，就是接下来这个周五的上午 10 点', icsDl.suggestedFilename().endsWith('.ics') && !!fri && fri.getDay() === 5 && ahead >= 0 && ahead < 7, `${ics.split('\r\n').find((l) => l.startsWith('DTSTART'))}，离今天 ${ahead} 天`)
  t('……地点、提醒都在，告诉她点开就能加', ics.includes('LOCATION:国贸三期 B 座 1208') && ics.includes('BEGIN:VALARM') && (await toast()).includes('日历'))
  const lilyCard = card('Lily · 增长负责人')
  await ensureOpen(lilyCard)
  t('联系人卡：没有时间，就没有「加到日历」', (await lilyCard.locator('.copies .btn', { hasText: '日历' }).count()) === 0)
  const [vcfDl] = await Promise.all([pg.waitForEvent('download'), lilyCard.locator('.copies .btn', { hasText: '存到通讯录' }).click()])
  const vcf = readFileSync(await vcfDl.path(), 'utf8')
  t('联系人卡「存到通讯录」：一个 .vcf，名字、电话、邮箱都在', vcfDl.suggestedFilename().endsWith('.vcf') && vcf.includes('FN:Lily') && vcf.includes('TEL;TYPE=CELL:13812345678') && vcf.includes('EMAIL;TYPE=INTERNET:lily.chen@example.com'), vcf.split('\r\n').slice(2, 5).join(' / '))

  // ---------------------------------------------------------------- 我的问法
  await pg.locator('.ghost[aria-label="设置"]').click(); await wait(200)
  await pg.locator('#newask').fill('帮我改写成一条朋友圈')
  await pg.locator('.sheet .btn', { hasText: '存下' }).click(); await wait(150)
  t('设置里存一句自己的问法', (await pg.locator('.my-asks li').count()) === 1 && (await pg.locator('.my-asks').innerText()).includes('改写成一条朋友圈'))
  await pg.keyboard.press('Escape'); await wait(150)
  await pg.reload({ waitUntil: 'load' }); await wait(600)
  const lily2 = card('Lily · 增长负责人')
  await ensureOpen(lily2)
  const mine = lily2.locator('.alt', { hasText: '改写成一条朋友圈' })
  t('每张卡的「换个问法」里都有它（刷新后还在）', (await mine.count()) === 1)
  await mine.click(); await wait()
  t('……点一下：这句 + 这条信息一起复制', (await clip()).startsWith('帮我改写成一条朋友圈\n\n【整理好的信息】\nLily'))

  // ---------------------------------------------------------------- 备份：导出 / 导入
  await pg.locator('.ghost[aria-label="设置"]').click(); await wait(300)
  t('设置：说清楚数据只在这台设备上', (await pg.locator('.sheet').innerText()).includes('只存在这台设备'))
  t('设置：Claude 整理是「可选」的，默认没开', (await pg.locator('.sheet .pill').innerText()) === '可选')
  const [dl] = await Promise.all([pg.waitForEvent('download'), pg.locator('.sheet .btn', { hasText: '导出备份' }).click()])
  const file = await dl.path()
  const backup = JSON.parse(readFileSync(file, 'utf8'))
  t('导出备份：一个 JSON 文件，每一条都在（截图也在）', backup.app === 'suishou' && backup.items.length === total && backup.items.some((x) => x.img), `${backup.items.length} / ${total}`)
  t('……文件名看得出是什么', /^suishou-backup-\d{8}\.json$/.test(dl.suggestedFilename()), dl.suggestedFilename())
  await pg.keyboard.press('Escape'); await wait(200)
  t('Esc 关掉设置', (await pg.locator('.sheet').count()) === 0)

  // 换一台「设备」：新的浏览器上下文，什么都没有
  const ctx2 = await b.newContext({ ...devices['iPhone 13'] })
  const pg2 = await ctx2.newPage()
  pg2.on('pageerror', (e) => errs.push('新设备: ' + e.message))
  await pg2.goto(URL, { waitUntil: 'load' }); await pg2.waitForTimeout(500)
  await pg2.locator('.ghost[aria-label="设置"]').click()
  await pg2.locator('#import').setInputFiles(file); await pg2.waitForTimeout(600)
  t('换台设备导入备份：全回来了', (await pg2.locator('.list article.card').count()) === total, `${await pg2.locator('.list article.card').count()} / ${total}`)
  t('……告诉她导入了几条', (await pg2.locator('.toast').innerText()).includes(`导入了 ${total} 条`))
  t('……她存的问法也跟着过来了', (await pg2.locator('.my-asks').innerText().catch(() => '')).includes('改写成一条朋友圈'))
  await pg2.locator('#import').setInputFiles(file); await pg2.waitForTimeout(500)
  t('同一份再导一次：不重复', (await pg2.locator('.list article.card').count()) === total && (await pg2.locator('.toast').innerText()).includes('已经有了'))
  await pg2.locator('#import').setInputFiles({ name: 'x.json', mimeType: 'application/json', buffer: Buffer.from('{"a":1}') }); await pg2.waitForTimeout(300)
  t('导入别的文件：说清楚不是备份，什么都不动', (await pg2.locator('.toast').innerText()).includes('不是随手拾的备份') && (await pg2.locator('.list article.card').count()) === total)
  await ctx2.close()

  // 删掉自己的问法
  await pg.locator('.ghost[aria-label="设置"]').click(); await wait(200)
  await pg.locator('.my-ask-x').first().click(); await wait(150)
  t('问法可以删掉', (await pg.locator('.my-asks li').count()) === 0)
  await pg.keyboard.press('Escape'); await wait(150)

  // ---------------------------------------------------------------- 老版本的数据（存在 localStorage 里的）
  const ctx3 = await b.newContext()
  const old = [{ id: 'old1', raw: '老版本收的一条', createdAt: Date.now() - 86400e3, updatedAt: 0, status: 'local', kind: 'note', title: '老版本收的一条', summary: '', fields: [], todos: [], tags: [], prompt: '', pinned: false }]
  await ctx3.addInitScript((v) => { if (!sessionStorage.getItem('__seeded')) { localStorage.setItem('suishou.items.v2', v); sessionStorage.setItem('__seeded', '1') } }, JSON.stringify(old))
  const pg3 = await ctx3.newPage()
  await pg3.goto(URL, { waitUntil: 'load' }); await pg3.waitForTimeout(600)
  t('老版本存的东西：打开就搬过来了', (await pg3.locator('.list article.card').filter({ hasText: '老版本收的一条' }).count()) === 1)
  t('……搬完把旧的那份清掉（不会搬两次）', (await pg3.evaluate(() => localStorage.getItem('suishou.items.v2'))) === null)
  await pg3.reload({ waitUntil: 'load' }); await pg3.waitForTimeout(500)
  t('……刷新后还在，只有一条', (await pg3.locator('.list article.card').count()) === 1)
  await ctx3.close()

  t('没开 Claude：全程一个请求都没出过这个网站', outside.length === 0, outside.slice(0, 3).join(' | '))
  t('全程没有页面报错', errs.length === 0, errs.slice(0, 2).join(' | '))
} finally {
  await b.close()
}
process.exit(fail ? 1 : 0)
