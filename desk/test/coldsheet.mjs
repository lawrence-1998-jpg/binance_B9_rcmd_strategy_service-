// 被系统杀掉之后重开，浮层不能把整个 App 弹走。
//
// iPhone 上主屏 PWA 被系统回收是家常便饭。回收的那一刻如果正开着速记，
// hash 就停在 `#/today?sheet=capture`；从桌面图标重开，浏览器把这个 URL
// 原样还给你。
//
// 而浮层状态只在 hashchange 里读，**初次挂载不读**。于是：
//
//   冷启动 : dialog=0  hash=#/today?sheet=capture  histLen=2   ← URL 说有，屏上没有
//   点开＋ : dialog=1  hash=#/today?sheet=capture  histLen=2   ← 没新增历史
//   点关闭 : dialog=0  url=about:blank                          ← 整个 App 被弹走
//
// 第二步是关键：`location.hash` 要写的值跟当前一模一样，赋值不触发跳转、
// history 里不多一格；而 closeSheet 走的是 `history.back()`，
// 那一下弹掉的就是 App 自己。standalone 窗口没有浏览器返回键，
// 她只能杀掉重进。
//
// 修法是冷启动时先把 `?sheet=` 抹掉（replaceState，不触发 hashchange
// 也不加历史）。不恢复浮层：草稿本来就没存，恢复出来是个空壳，
// 「重开 App 弹出一个空速记框」比回到今日更奇怪。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })

// 先把数据种好
const warm = await ctx.newPage()
await warm.goto(APP)
await warm.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await warm.close()

const dialogs = (p) => p.locator('[role=dialog]').count()
const hash = (p) => p.evaluate(() => location.hash)
const hist = (p) => p.evaluate(() => history.length)
const inApp = (p) => p.url().includes('index.html')

// ---- 对照组：正常路径不能被改坏 ----
{
  const p = await ctx.newPage()
  await p.goto(APP + '#/today'); await p.waitForTimeout(600)
  const h0 = await hist(p)
  await p.locator('button.cap').click(); await p.waitForTimeout(400)
  t('正常路径：点 ＋ 开出浮层', await dialogs(p) === 1)
  t('正常路径：点 ＋ 会往 history 里加一格', await hist(p) === h0 + 1, `${h0} → ${await hist(p)}`)
  await p.locator('button.icon-btn[aria-label=关闭]').click(); await p.waitForTimeout(600)
  t('正常路径：点关闭，浮层关掉', await dialogs(p) === 0)
  t('正常路径：点关闭，人还在案头里', inApp(p), p.url())
  t('正常路径：关掉之后 hash 里没有 sheet 了', !(await hash(p)).includes('sheet='), await hash(p))
  await p.close()
}

// ---- 真正要测的：冷启动就落在一个挂着 ?sheet= 的 URL 上 ----
for (const [label, url, route] of [
  ['速记', '#/today?sheet=capture', 'today'],
  ['设置', '#/review?sheet=settings', 'review'],
  ['Prompt', '#/today?sheet=prompts', 'today'],
]) {
  const p = await ctx.newPage()
  await p.goto(APP + url); await p.waitForTimeout(800)

  // ① URL 和屏幕必须对得上。以前是 URL 说有浮层、屏上没有
  t(`冷启动落在「${label}」的 URL：屏幕上没有浮层`, await dialogs(p) === 0)
  t(`冷启动落在「${label}」的 URL：hash 里的 sheet= 被抹掉了`,
    !(await hash(p)).includes('sheet='), await hash(p))
  t(`冷启动落在「${label}」的 URL：路由没被带跑`,
    (await hash(p)).includes(route), await hash(p))

  await p.close()
}

// ---- 冷启动之后再走一遍完整的开→关，这是会把 App 弹走的那条路 ----
{
  const p = await ctx.newPage()
  await p.goto(APP + '#/today?sheet=capture'); await p.waitForTimeout(800)
  const h0 = await hist(p)

  await p.locator('button.cap').click(); await p.waitForTimeout(400)
  t('冷启动之后点 ＋：浮层开出来了', await dialogs(p) === 1)
  // 这一条是病根：hash 没变 → 不加历史 → 之后 history.back() 弹的是 App 自己
  t('冷启动之后点 ＋：history 真的多了一格', await hist(p) === h0 + 1, `${h0} → ${await hist(p)}`)

  await p.locator('button.icon-btn[aria-label=关闭]').click(); await p.waitForTimeout(900)
  t('冷启动之后点关闭：浮层关掉了', await dialogs(p) === 0)
  t('冷启动之后点关闭：人还在案头里，没被弹到 about:blank', inApp(p), p.url())
  await p.close()
}

await b.close()
console.log(fail ? `\n${fail} 条没过` : '\n全过')
process.exit(fail ? 1 : 0)
