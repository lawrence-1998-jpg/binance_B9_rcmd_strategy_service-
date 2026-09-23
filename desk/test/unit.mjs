/**
 * 纯逻辑：本地先认一遍认得准不准、Claude 回来的东西核得严不严、复制出去的样子对不对。
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
  stdin: { contents: "export * from './card'; export { normalize } from './store'", resolveDir: fileURLToPath(new URL('../src/lib/', import.meta.url)), loader: 'ts' },
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

const meet = C.quick('王总：周四下午的会挪到周五上午 10 点吧，地点还是国贸三期 B 座 1208')
t('会议：认出时间', val(meet, '时间').some((v) => v.includes('周五')), JSON.stringify(val(meet, '时间')))
t('会议：类型是日程', meet.kind === 'event', meet.kind)

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

// ---------------------------------------------------------------- 时间

const base = new Date(2026, 8, 23, 15, 0).getTime()
t('分组：今天 / 昨天 / 这周早些时候 / 月份',
  C.dayGroup(base - 3600e3, base) === '今天' && C.dayGroup(base - 86400e3, base) === '昨天' &&
  C.dayGroup(base - 3 * 86400e3, base) === '这周早些时候' && C.dayGroup(new Date(2026, 5, 1).getTime(), base) === '6 月')

process.exit(fail ? 1 : 0)
