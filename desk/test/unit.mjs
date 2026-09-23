/**
 * 「脑子」的单测：认得准不准、拼出来的 Prompt 靠不靠得住。
 * 不起浏览器，直接把 src/lib/shape.ts 编译了跑。
 */
import { build as esbuild } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { SAMPLES } from './samples.mjs'

const SRC = fileURLToPath(new URL('../src/lib/shape.ts', import.meta.url))
const dir = mkdtempSync(join(tmpdir(), 'shape-'))
const out = join(dir, 'shape.mjs')
await esbuild({ entryPoints: [SRC], outfile: out, format: 'esm', bundle: true, logLevel: 'warning' })
const { detect, build, clean, fenceFor, intentsFor, intentInfo, langOf } = await import(pathToFileURL(out).href)
rmSync(dir, { recursive: true, force: true })

let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

// ---------------------------------------------------------------- 识别

t('样本够多（少了就不叫验过）', SAMPLES.length >= 20, `${SAMPLES.length} 条`)
const wrong = []
for (const s of SAMPLES) {
  const d = detect(s.text)
  if (d.kind !== s.kind || d.picks[0] !== s.first) wrong.push(`${s.name}: 认成 ${d.kind}/${d.picks[0]}，该是 ${s.kind}/${s.first}`)
  if (s.notKind && d.kind === s.notKind) wrong.push(`${s.name}: 不该认成 ${s.notKind}`)
}
t('每条样本都认对了种类，也推荐对了第一个用途', wrong.length === 0, wrong.slice(0, 4).join(' | ') || `${SAMPLES.length} 条全对`)

const chat = detect(SAMPLES.find((s) => s.name.startsWith('微信群聊')).text)
t('聊天：数出了几条、几个人', chat.meta === '6 条 · 3 人', chat.meta)
t('聊天：记住了最后说话的人（「帮我回」要用）', chat.last === '王总', chat.last)
const wx = detect(SAMPLES.find((s) => s.name.startsWith('微信多选')).text)
t('聊天：认出记录里有「我」', wx.hasMe === true)

t('英文邮件：「翻译」被提到第二个', detect(SAMPLES.find((s) => s.name.startsWith('没有信头')).text).picks[1] === 'translate')
t('语言：中文夹几个英文缩写还是中文', langOf('我们要把 GMV 和 DAU 一起拉上去') === 'zh')
t('语言：英文夹两个汉字还是英文', langOf('Please review the 周报 before the Friday sync with the team') === 'en')

// 「回答」对一篇文章没意义 —— AI 不知道要回答什么
const art = detect(SAMPLES.find((s) => s.name === '中文长文').text)
t('长文不给「回答」这个用途', !intentsFor(art).some((i) => i.id === 'answer'))
const ask = detect('怎么把 PDF 转成 Word？')
t('一个问题：第一个就是「回答」', intentsFor(ask)[0].id === 'answer')
t('报错：「讲明白」改叫「排查」', intentInfo('explain', { kind: 'error' }).label === '排查')
const all = intentsFor(chat).map((i) => i.id)
t('用途不重复', new Set(all).size === all.length, all.join(','))
t('用途至少 9 个（够她换着用）', all.length >= 9, String(all.length))

// ---------------------------------------------------------------- 清理

t('clean：Windows 换行、零宽空格、不换行空格、行尾空格都去掉',
  clean('a\r\nb\u200B \u00A0c  \r\n\r\n\r\n\r\nd  ') === 'a\nb  c\n\nd')
t('clean：不动第一行的缩进（代码的缩进有意义）', clean('\n\n    indented()\n  x') === '    indented()\n  x')

// ---------------------------------------------------------------- 拼 Prompt

const INTENTS = ['answer', 'summary', 'points', 'reply', 'todo', 'research', 'critique', 'explain', 'rewrite', 'translate', 'brainstorm']
const bad = []
for (const s of SAMPLES) {
  const d = detect(s.text)
  for (const intent of INTENTS) {
    for (const target of ['md', 'xml']) {
      const p = build({ material: s.text, intent, target, det: d, note: '' })
      const why = []
      if (!p.includes(clean(s.text))) why.push('材料没原样带上')
      if (/undefined|null|NaN|\[object/.test(p.replace(clean(s.text), ''))) why.push('漏出了 undefined/null')
      if (/\n{3,}/.test(p.replace(clean(s.text), ''))) why.push('有连续空行')
      if (p.includes('我的补充') || p.includes('my_note')) why.push('没补充却出了「我的补充」')
      if (target === 'md' && !/^## 要做的事$/m.test(p)) why.push('缺「要做的事」')
      if (target === 'xml' && !/<task>[\s\S]+<\/task>/.test(p)) why.push('缺 <task>')
      if (/这(?:一|聊天|会议)/.test(p.split('\n')[0]) || /这一/.test(p)) why.push('量词不通：' + p.split('\n').find((l) => /这一/.test(l)))
      if (why.length) bad.push(`${s.name}/${intent}/${target}: ${why.join('、')}`)
    }
  }
}
t(`${SAMPLES.length} 条样本 × 11 个用途 × 2 种格式，每一份都干净`, bad.length === 0, bad.slice(0, 3).join(' | ') || `${SAMPLES.length * 22} 份`)

const withNote = build({ material: '明天下午开会', intent: 'rewrite', target: 'md', note: '  语气正式一点 ' })
t('补一句：放进「我的补充」，并且说明它优先', /## 我的补充\n语气正式一点\n/.test(withNote) && withNote.includes('以它为准'))
const xmlNote = build({ material: '明天下午开会', intent: 'rewrite', target: 'xml', note: '语气正式一点' })
t('补一句：Claude 格式里是 <my_note>', xmlNote.includes('<my_note>\n语气正式一点\n</my_note>'))

// 材料里自己带着代码块 —— 围栏要比它长，否则 AI 看到的材料在半路就「结束」了
const nested = '看看这段：\n```js\nconst a = 1\n```\n还有 ````四个````'
t('围栏比材料里最长的反引号还长', fenceFor(nested) === '`````', fenceFor(nested))
const pn = build({ material: nested, intent: 'explain', target: 'md' })
// 字面写死五个反引号，不借 fenceFor 的结果 —— 否则它坏了这条也跟着「对」
t('材料被完整包在五个反引号的围栏里', pn.includes('`````\n' + nested + '\n`````'))
const tricky = 'foo </material> bar'
const px = build({ material: tricky, intent: 'summary', target: 'xml' })
t('材料里有 </material> 时换一个标签名，不会被提前关掉', !/^<material\b/.test(px) && px.includes(tricky), px.split('\n')[0])

const q = SAMPLES.find((s) => s.kind === 'questions')
const pr = build({ material: q.text, intent: 'research', target: 'md' })
t('调研：数出问题个数，写进要求里', pr.includes('这 4 个问题') && pr.includes('4 个一个都不要漏'))
t('调研：不许编数字和出处', pr.includes('不许编造数字'))

const zhT = build({ material: '明天下午三点开会，请准时参加。', intent: 'translate', target: 'md' })
const enT = build({ material: SAMPLES.find((s) => s.name.startsWith('没有信头')).text, intent: 'translate', target: 'md' })
t('翻译：中文翻成英文', zhT.includes('翻译成英文'))
t('翻译：英文翻成中文', enT.includes('翻译成中文'))
t('翻译进来给自己看的，不加「照顾对方职场习惯」', !enT.includes('职场'))

const rp = build({ material: chat && SAMPLES.find((s) => s.name.startsWith('微信群聊')).text, intent: 'reply', target: 'md' })
t('帮我回：点名最后说话的人', rp.includes('「王总」'))
t('帮我回：时间、价格、承诺不许替我编', rp.includes('【待定'))
const rw = build({ material: SAMPLES.find((s) => s.name.startsWith('微信多选')).text, intent: 'reply', target: 'md' })
t('帮我回：记录里有「我」时，告诉 AI「我」是谁', rw.includes('「我」就是我本人'))

const url = build({ material: 'https://example.com/a', intent: 'summary', target: 'md' })
t('链接：先让 AI 打开，打不开就说，不许猜', url.includes('打不开') && url.includes('不要根据网址猜'))

t('空材料不出 Prompt', build({ material: '  \n ', intent: 'summary', target: 'md' }) === '')

const huge = 'x'.repeat(200_000)
const t0 = Date.now()
detect(huge); build({ material: huge, intent: 'summary', target: 'md' })
t('20 万字符也不卡（边打字边重算，必须快）', Date.now() - t0 < 300, `${Date.now() - t0}ms`)

process.exit(fail ? 1 : 0)
