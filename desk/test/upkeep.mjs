// 「这几天你动了几天」—— 30 分钟/周那条阈值现在有数可以对照了。
//
// 两条要守住的：
// ① 一个字节都不新存（纯推导）—— 加了这一行之后 localStorage 不该变大
// ② 措辞是事实不是成绩单：不出现「才 / 只 / 已经」这类带评判的字
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
const DAY = 86400000
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', e => errs.push(e.message))

const key = (offset) => new Date(Date.now() - offset*DAY).toISOString().slice(0,10)

async function seed (mut) {
  await pg.goto(APP)
  await pg.evaluate(({ s, mutSrc, DAY }) => {
    // eslint-disable-next-line no-new-func
    new Function('s','DAY', mutSrc)(s, DAY)
    localStorage.setItem('deskside.v1', JSON.stringify(s))
  }, { s: makeState(today), mutSrc: mut, DAY })
  await pg.goto(APP+'#/review'); await pg.reload(); await pg.waitForTimeout(600)
}
const line = () => pg.locator('.upkeep').innerText()

// ---- 空空如也 ----
await seed(`
  s.notes=[]; s.wishes=[]; s.photos=[]; s.moments=[]; s.myPrompts=[];
  s.inquiries=[]; s.engagements=[]; s.entries=[]; s.tasks=[]; s.focus={};
`)
t('什么都没有时，说的是「没留下什么」', (await line()).includes('没在这儿留下什么'), await line())
t('没有「才」「只」这种带评判的字', !/才|只有|仅/.test(await line()), await line())

// ---- 三天有动静 ----
await seed(`
  s.notes=[]; s.wishes=[]; s.photos=[]; s.moments=[]; s.myPrompts=[];
  s.inquiries=[]; s.engagements=[]; s.entries=[]; s.tasks=[]; s.focus={};
  const d=(n)=>new Date(Date.now()-n*DAY).toISOString().slice(0,10)
  s.moments=[
    {id:'a',text:'一',createdAt:Date.now()-1*DAY},
    {id:'b',text:'二',createdAt:Date.now()-1*DAY},   // 同一天两条，只算一天
    {id:'c',text:'三',createdAt:Date.now()-3*DAY},
  ]
  s.focus[d(5)]='那天的重心'
`)
const l1 = await line()
t('三个不同的日子 → 动了 3 天', l1.includes('动了 3 天'), l1)
t('同一天写两条只算一天', l1.includes('动了 3 天'))
t('新添条数只数窗口内的', l1.includes('新添了 3 条'), l1)

// ---- 窗口外的不算 ----
await seed(`
  s.notes=[]; s.wishes=[]; s.photos=[]; s.moments=[]; s.myPrompts=[];
  s.inquiries=[]; s.engagements=[]; s.entries=[]; s.tasks=[]; s.focus={};
  s.moments=[
    {id:'a',text:'窗口内',createdAt:Date.now()-2*DAY},
    {id:'b',text:'半个月前',createdAt:Date.now()-15*DAY},
    {id:'c',text:'三个月前',createdAt:Date.now()-90*DAY},
  ]
`)
const l2 = await line()
t('七天以外的不算进来', l2.includes('动了 1 天') && l2.includes('新添了 1 条'), l2)

// ---- 不新存任何东西 ----
const before = await pg.evaluate(() => (localStorage.getItem('deskside.v1')||'').length)
await pg.reload(); await pg.waitForTimeout(500)
await pg.goto(APP+'#/review'); await pg.reload(); await pg.waitForTimeout(500)
const after = await pg.evaluate(() => (localStorage.getItem('deskside.v1')||'').length)
t('看这一行不会往存储里写东西（纯推导）', after === before, `${before} → ${after}`)
t('state 里没有多出计数器字段', await pg.evaluate(() => {
  const s = JSON.parse(localStorage.getItem('deskside.v1'))
  return !('opens' in s) && !('visits' in s) && !('usage' in s)
}))

// ---- 位置和分量 ----
t('这一行在复盘屏最底下、「回今日」上面', await pg.evaluate(() => {
  const u = document.querySelector('.upkeep')
  const back = [...document.querySelectorAll('button')].find(b => b.textContent.trim()==='回今日')
  return !!u && !!back && u.getBoundingClientRect().top < back.getBoundingClientRect().top
}))
t('是最轻的一行灰字，不是卡片', await pg.evaluate(() => {
  const cs = getComputedStyle(document.querySelector('.upkeep'))
  return cs.backgroundColor === 'rgba(0, 0, 0, 0)' && parseFloat(cs.fontSize) <= 13
}))

// ---- 不变量：天数永远不能超过窗口 ----
// 「这 7 天你动了 8 天」这种一眼假的数真的印出来过（窗口含头含尾算成 8 天）。
// 上面那些用例日子少，一条都没抓到 —— 是截图看见的。补一条把它钉死。
await seed(`
  const d=(n)=>new Date(Date.now()-n*DAY).toISOString().slice(0,10)
  s.moments=[]; for (let i=0;i<20;i++) s.moments.push({id:'m'+i,text:'第'+i+'天',createdAt:Date.now()-i*DAY})
  s.tasks=[]; for (let i=0;i<20;i++) s.tasks.push({id:'t'+i,title:'x',domain:'me',done:false,date:d(i)})
  s.focus={}; for (let i=0;i<20;i++) s.focus[d(i)]='重心'
`)
const l3 = await line()
const n = Number((l3.match(/动了 (\d+) 天/) || [])[1])
t('天天都有动静时，报的是「动了 7 天」而不是更多', n === 7, l3)
t('永远不会出现「N 天里动了 >N 天」', n <= 7, l3)

t('无页面错误', errs.length === 0, errs.slice(0,2).join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
