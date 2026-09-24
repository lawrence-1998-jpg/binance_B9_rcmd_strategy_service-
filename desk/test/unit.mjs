/**
 * 纯逻辑：本地整理认得准不准（没开 Claude 时它就是全部）、Claude 回来的东西核得严不严、
 * 复制出去的样子对不对、备份导出导入合得对不对。
 * 不起浏览器，直接把 src/lib/card.ts 编译了跑。
 */
import { build as esbuild } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const dir = mkdtempSync(join(tmpdir(), 'card-'))
const out = join(dir, 'm.mjs')
await esbuild({
  stdin: { contents: "export * from './card'; export { normalize, toBackup, fromBackup, merge } from './store'; export * as A from './ask'", resolveDir: fileURLToPath(new URL('../src/lib/', import.meta.url)), loader: 'ts' },
  outfile: out, format: 'esm', bundle: true, logLevel: 'warning',
})
const C = await import(pathToFileURL(out).href)
rmSync(dir, { recursive: true, force: true })

let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
const val = (card, label) => card.fields.filter((f) => f.label === label).map((f) => f.value)

// ---------------------------------------------------------------- 本地先认一遍

const contact = C.quick('Lily Chen｜增长策略负责人\n手机 138 1234 5678\n邮箱 lily.chen@example.com')
t('名片：认出电话', val(contact, '电话').includes('138 1234 5678'), JSON.stringify(val(contact, '电话')))
t('名片：认出邮箱', val(contact, '邮箱')[0] === 'lily.chen@example.com')
t('名片：类型是联系人', contact.kind === 'contact', contact.kind)

const meet = C.quick('王总：周四下午的会挪到周五上午 10 点吧，地点还是国贸三期 B 座 1208。记得带上次那版竞品分析，财务的 Linda 也会来。')
t('会议：认出改到的那个时间', val(meet, '时间').length === 1 && val(meet, '时间')[0] === '周五上午 10 点', JSON.stringify(val(meet, '时间')))
t('会议：「挪到周五」之前的「周四」不算时间', !val(meet, '时间').includes('周四'))
t('会议：认出明说的地点', val(meet, '地点')[0] === '国贸三期 B 座 1208', JSON.stringify(val(meet, '地点')))
t('会议：类型是日程', meet.kind === 'event', meet.kind)
t('会议：「记得带…」变成一条待办', meet.todos.length === 1 && meet.todos[0].text === '带上次那版竞品分析', JSON.stringify(meet.todos))
t('会议：要点接着标题往下露，不从半个词开始', meet.summary.startsWith('记得带上次那版竞品分析'), meet.summary)
t('会议：标题不把「10」劈成两半', !/1…$/.test(meet.title) && [...meet.title].length <= 19, meet.title)
t('会议：配好一句按日程问 AI 的话', meet.prompt.startsWith('帮我把这件事整理成日程'), meet.prompt)

const price = C.quick('报价：年费版 ¥36,000/年（含 20 个席位），超出部分每席 ¥1,500/年；首年 8 折。')
t('报价：认出两个金额', val(price, '金额').length === 2 && val(price, '金额')[0].startsWith('¥36,000'), JSON.stringify(val(price, '金额')))

const link = C.quick('https://www.example.com/reports/2026-ai-adoption')
t('链接：类型是链接，标题用域名', link.kind === 'link' && link.title === 'example.com', `${link.kind} / ${link.title}`)
t('链接：不会把网址里的数字认成电话', val(link, '电话').length === 0)

const otp = C.quick('【某银行】您的验证码为 482913，5 分钟内有效。')
t('验证码：单独拎出来', val(otp, '验证码')[0] === '482913')

const plain = C.quick('今天想到：会员体系的核心问题可能不是权益，而是用户根本不知道自己有哪些权益。')
t('普通一段话：没有乱认出字段', plain.fields.length === 0, JSON.stringify(plain.fields))
t('标题按字截断，不超过 18 个字（加省略号）', [...plain.title].length <= 19, plain.title)
t('「今天想到：」开头：是想法，标题去掉这个前缀', plain.kind === 'idea' && plain.title.startsWith('会员体系'), `${plain.kind} / ${plain.title}`)
t('「今天想到」里的「今天」不当成时间', val(plain, '时间').length === 0)

const due = C.quick('周五前把季度复盘 PPT 发给王总')
t('「周五前把 PPT 发给王总」：待办，截止周五前', due.kind === 'todo' && val(due, '截止')[0] === '周五前' && due.todos[0]?.text === '周五前把季度复盘 PPT 发给王总', JSON.stringify(due))

const boxes = C.quick('- [ ] 订周五的会议室\n- [x] 发邮件给 Linda\n- [ ] 准备报价单')
t('勾框清单：每行一条待办，打了勾的算做完', boxes.kind === 'todo' && boxes.todos.length === 3 && boxes.todos[1].done && !boxes.todos[0].done, JSON.stringify(boxes.todos))
t('勾框清单：标题是「第一件 等 N 件」', boxes.title === '订周五的会议室 等 3 件', boxes.title)
const shop = C.quick('周末要买：\n- 牛奶\n- 鸡蛋\n- 咖啡豆')
t('「要买」清单：每行一条，标题去掉冒号', shop.kind === 'todo' && shop.todos.map((x) => x.text).join() === '牛奶,鸡蛋,咖啡豆' && shop.title === '周末要买', `${shop.title} ${JSON.stringify(shop.todos)}`)
const minutes = C.quick('会议纪要\n1. 下季度重点是留存\n2. 预算不变\n3. Linda 负责数据看板，月底前给初版')
t('会议纪要：是笔记不是清单，里面「月底前给初版」拎成待办', minutes.kind === 'note' && minutes.todos.length === 1 && minutes.todos[0].text.startsWith('Linda'), JSON.stringify(minutes))

const call = C.quick('明天下午 3 点和 Lily 通电话 138 1234 5678，聊报价 ¥36,000')
t('「明天 3 点通电话」：是日程，时间、电话、金额都在', call.kind === 'event' && val(call, '时间')[0] === '明天下午 3 点' && val(call, '电话').length === 1 && val(call, '金额').length === 1, JSON.stringify(call))

const err = C.quick("TypeError: Cannot read properties of undefined (reading 'map')\n    at App (App.tsx:42:13)")
t('报错：类型是代码，「42:13」不当成钟点', err.kind === 'code' && val(err, '时间').length === 0, JSON.stringify(err.fields))
t('每种类型都配了一句拿去问 AI 的话（验证码除外）', ['event', 'todo', 'contact', 'link', 'data', 'code', 'question', 'quote', 'idea', 'note', 'other'].every((k) => C.LOCAL_ASK[k].length > 10) && otp.prompt === '')
t('报价里的「36,000」不当成句子的逗号截断标题', !/¥36$/.test(price.title), price.title)

// ---------------------------------------------------------------- 交给 Claude 的指令

const now = new Date(2026, 8, 23, 10, 0) // 2026-09-23 周三
const pr = C.aiPrompt('明天下午三点和 Lily 通电话', now)
t('指令里写了今天是几号、星期几（「明天」才能换算）', pr.includes('2026-09-23（星期三）'))
t('指令里带着原文', pr.includes('<<<\n明天下午三点和 Lily 通电话\n>>>'))
t('指令要求只回 JSON', pr.includes('只回复一个 JSON 对象'))
t('指令不许编造', pr.includes('不编造'))
t('超长原文截到 1.2 万字以内（Claude 一次读得完）', C.aiPrompt('字'.repeat(50000), now).length < 14000)

// ---------------------------------------------------------------- Claude 回来的东西

const good = C.fromAi({
  kind: 'event', title: '王总的会改到周五', summary: '改到周五 10 点',
  fields: [{ label: '时间', value: '9月26日（周五）10:00' }, { label: '地点', value: '无' }, { label: '', value: 'x' }],
  todos: ['带上竞品分析'], tags: ['#客户会议'], prompt: '帮我回复王总',
})
t('正常的卡：收下', good && good.kind === 'event' && good.title === '王总的会改到周五')
t('「无」「未提及」这种假值被丢掉', good.fields.length === 1, JSON.stringify(good.fields))
t('待办变成可勾选的格式', good.todos[0].text === '带上竞品分析' && good.todos[0].done === false)
t('标签去掉 # 号', good.tags[0] === '客户会议')

const zhKind = C.fromAi({ kind: '联系人', title: 'Lily', fields: { 手机: '138 1234 5678' } })
t('kind 写成中文也认', zhKind.kind === 'contact', zhKind.kind)
t('fields 写成对象也认', zhKind.fields[0].label === '手机' && zhKind.fields[0].value === '138 1234 5678')
t('没有标题的回复不收（宁可重试，不要一张空卡）', C.fromAi({ kind: 'note', title: '' }) === null)
t('不是对象的回复不收', C.fromAi(['a']) === null && C.fromAi('x') === null && C.fromAi(null) === null)
t('奇怪的 kind 归为「其他」', C.fromAi({ kind: 'banana', title: 'x' }).kind === 'other')
t('字段最多 8 个', C.fromAi({ title: 'x', fields: Array.from({ length: 20 }, (_, i) => ({ label: 'l' + i, value: 'v' })) }).fields.length === 8)

// ---------------------------------------------------------------- 复制出去的样子

const item = { id: 'a', raw: '原文在这里', createdAt: 0, updatedAt: 0, status: 'done', pinned: false, ...good,
  todos: [{ text: '带上竞品分析', done: false }, { text: '已经做完的', done: true }] }
const txt = C.asText(item)
t('整理版：标题 + 要点 + 字段', txt.startsWith('王总的会改到周五\n改到周五 10 点\n\n时间：9月26日（周五）10:00'), JSON.stringify(txt.slice(0, 40)))
t('整理版：只列没做完的待办', txt.includes('· 带上竞品分析') && !txt.includes('已经做完的'))
const ai = C.asAi(item)
t('给 AI：第一行就是那句指令', ai.startsWith('帮我回复王总\n'))
t('给 AI：带上整理版和原文', ai.includes('【整理好的信息】') && ai.includes('"""\n原文在这里\n"""'))
t('给 AI：没有指令时有一句兜底', C.asAi({ ...item, prompt: '' }).startsWith('请帮我理解这条信息'))
const many = C.manyAi([item, { ...item, id: 'b', title: '第二条' }])
t('多条给 AI：说清楚一共几条、要做什么', many.startsWith('下面是我收集的 2 条信息') && many.includes('## 2. 第二条'))
t('多条整理版：编号', C.manyText([item, item]).startsWith('1. 王总的会改到周五') && C.manyText([item, item]).includes('\n\n2. '))

// ---------------------------------------------------------------- 找

t('搜：按字段值找得到', C.matches(item, '9月26日'))
t('搜：多个词都要命中', C.matches(item, '王总 周五') && !C.matches(item, '王总 上海'))
t('搜：按原文找得到', C.matches(item, '原文在'))

// ---------------------------------------------------------------- 数据库读出来的东西

const n = C.normalize('x1', { raw: 'r', kind: 'weird', fields: [{ label: 'a', value: 'b' }, { label: 1 }], todos: [{ text: 't' }, 'bad'], tags: ['ok', 3] })
t('读回来的脏数据补齐', n && n.kind === 'other' && n.fields.length === 1 && n.todos.length === 1 && n.todos[0].done === false && n.tags.length === 1)
t('没有原文的记录不认', C.normalize('x2', { title: 'x' }) === null)

// ---------------------------------------------------------------- 备份：导出 / 导入

const mine = [
  { ...item, id: 'a1', raw: '第一条', updatedAt: 10 },
  { ...item, id: 'a2', raw: '第二条', updatedAt: 10, status: 'pending' },
  { ...item, id: 'a3', raw: '第三条', updatedAt: 10, img: 'data:image/jpeg;base64,AAAA' },
]
const file = C.toBackup(mine, new Date(2026, 8, 23))
const back = C.fromBackup(file)
t('导出再导入：一条不少，截图也在', back.length === 3 && back[2].img === 'data:image/jpeg;base64,AAAA')
t('导出时整理到一半的不带「在整理」（换台设备不会一直转圈）', back.find((x) => x.id === 'a2').status === 'failed')
t('导出的文件认得出是随手拾的', JSON.parse(file).app === 'suishou' && JSON.parse(file).version === 1)
let threw = ''
try { C.fromBackup('{"hello":1}') } catch (e) { threw = e.message }
t('别的 JSON 不认，不瞎猜', threw === 'not_backup')
try { C.fromBackup('不是 JSON') } catch (e) { threw = e.message }
t('不是 JSON 的不认', threw === 'not_json')
const m1 = C.merge(mine, back)
t('导入同一份：全部跳过，不重复', m1.add.length === 0 && m1.skipped === 3)
const newer = { ...mine[0], title: '改过的', updatedAt: 99 }
const m2 = C.merge(mine, [newer, { ...mine[1], id: 'zz' }, { ...item, id: 'b9', raw: '全新的一条' }])
const shots = [{ ...item, id: 's1', raw: '［截图］', img: 'data:image/jpeg;base64,AAAA' }, { ...item, id: 's2', raw: '［截图］', img: 'data:image/jpeg;base64,BBBB' }]
t('导入：两张不同的截图（原文都是「［截图］」）都收下', C.merge([], shots).add.length === 2)
t('导入：同一条留改得更晚的；原文一样但 id 不同的不重复收；新的收下', m2.add.map((x) => x.id).join() === 'a1,b9' && m2.skipped === 1, JSON.stringify(m2.add.map((x) => x.id)))

// ---------------------------------------------------------------- 截图

const ip = C.aiPrompt('', now, true)
t('读截图的指令：先把图里的字原样转写进 raw', ip.includes('原样转写') && ip.includes('"raw"'))
t('读截图的指令：不带空的「原文」段', !ip.includes('<<<'))
t('读截图：Claude 转写的字收下', C.fromAi({ title: '报价', raw: '报价单\r\n年费 ¥36,000  ' }).raw === '报价单\n年费 ¥36,000')
t('读文字：Claude 没回 raw 就不带 raw（原文不许它改）', !('raw' in C.fromAi({ title: 'x' })))

// ---------------------------------------------------------------- 问一问

const T0 = new Date(2026, 8, 23, 15, 0).getTime()
const mk = (i, title, extra = {}) => ({ id: 'i' + i, raw: '原文' + i, createdAt: T0 - i * 1000, updatedAt: 0, status: 'done', pinned: false,
  kind: 'note', title, summary: '', fields: [], todos: [], tags: [], prompt: '', ...extra })
const lib = [mk(1, '周会纪要'), mk(2, 'Lily Chen', { kind: 'contact', fields: [{ label: '手机', value: '138 1234 5678' }] }), mk(3, '报价')]
const chosen = C.A.pick('Lily 的电话', lib)
t('问一问：跟问题沾边的卡排在最前面', chosen[0].title === 'Lily Chen', chosen.map((x) => x.title).join(','))
t('问一问：其余的也带上（它可能要对比）', chosen.length === 3)
const ap = C.A.askPrompt('Lily 的电话？', chosen, now)
t('问一问的提示：卡片带编号、带字段', ap.includes('[1] 联系人｜Lily Chen') && ap.includes('手机：138 1234 5678'))
t('问一问的提示：要求标出处、不许编', ap.includes('[3] 这样') && ap.includes('不要编'))
const big = Array.from({ length: 3000 }, (_, i) => mk(i, '一条很长的笔记' + i, { raw: '内容'.repeat(200) }))
const bigPick = C.A.pick('随便问问', big)
const bytes = new TextEncoder().encode(C.A.askPrompt('随便问问', bigPick, now)).length
t('问一问：收得再多，提示也塞得进 64 KiB', bytes < 60_000 && bigPick.length > 20, `${bigPick.length} 张 / ${bytes} 字节`)
const ps = C.A.pieces('电话是 138 1234 5678 [1]。另见 [9]。', 3)
t('回答切片：[1] 变成出处，超出范围的 [9] 照原样当字', ps.filter((p) => 'ref' in p).length === 1 && ps.some((p) => p.text?.includes('[9]')))
t('复制回答：[编号] 换成卡片标题', C.A.plainAnswer('电话是 138 1234 5678 [1]。', chosen) === '电话是 138 1234 5678（Lily Chen）。')

// ---------------------------------------------------------------- 时间

const base = new Date(2026, 8, 23, 15, 0).getTime()
t('分组：今天 / 昨天 / 这周早些时候 / 月份',
  C.dayGroup(base - 3600e3, base) === '今天' && C.dayGroup(base - 86400e3, base) === '昨天' &&
  C.dayGroup(base - 3 * 86400e3, base) === '这周早些时候' && C.dayGroup(new Date(2026, 5, 1).getTime(), base) === '6 月')

process.exit(fail ? 1 : 0)
