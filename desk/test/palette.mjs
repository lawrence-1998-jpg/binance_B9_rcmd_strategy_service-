// 屏幕上的每一种文字颜色，都得是我们自己定的。
//
// 起因：样例那张卡的标题是**浏览器默认的链接蓝**（亮色 #0000EE /
// 暗色 #9E9EFF）。这套配色里没有蓝。
//
// 怎么混进来的：那张卡是 <a>，它下面那张「去复盘」是 <button>。
// button 从 body 继承墨色，<a> 不会 —— 它拿 UA 默认的链接色；
// 而 .gocard / .card 都没设 color，于是同样的 class、同样的长相，
// 两张卡的标题一个墨色一个蓝色。
//
// 为什么现有的测试全看不见：查对比度的那套只问「这个颜色在这个底色上
// 读不读得清」。#0000EE 在纸色上有 8:1，**它过了**。没有任何一条断言
// 问过「这个颜色是不是我们的颜色」。
//
// 所以这里不写死一张颜色清单（那种清单加个色就得改一次，早晚被随手改绿）。
// 做法是运行时从 :root 上把所有 --* 变量里长得像颜色的读出来，
// 那就是合法调色板；屏幕上任何一段文字的颜色不在里面就红。
// 加一个新 token 会自动合法 —— 而 UA 默认色永远不可能是 token。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

// 七个屏幕状态，两套配色。
//
// ⚠️ 分段控件的 tab 是组件内部 state，**不吃 URL 参数**。
// 第一版这里写的是 `#/work?tab=byte` / `#/life?tab=trip` /
// `#/review?tab=timeline` —— 那三个参数一个都不起作用，
// 于是「七个屏幕状态」实际上是四个屏，其中三个被原地扫了两遍。
// 断言是真的，覆盖面是虚的。要切 tab 就得去点那个按钮。
const ROUTES = [
  ['今日', '#/today', null],
  ['工作·咨询', '#/work', null],
  ['工作·字节', '#/work', '字节产品'],
  ['生活·我们俩', '#/life', null],
  ['生活·假期', '#/life', /国庆|假期/],
  ['复盘·今天', '#/review', null],
  ['复盘·时间轴', '#/review', '时间轴'],
]

const SCAN = () => {
  // :root 上所有 --* 里能被浏览器解析成颜色的，就是合法调色板
  const cs = getComputedStyle(document.documentElement)
  const legal = new Set()
  const probe = document.createElement('span')
  document.body.appendChild(probe)
  for (const name of Array.from(cs).filter((n) => n.startsWith('--'))) {
    const v = cs.getPropertyValue(name).trim()
    if (!v) continue
    probe.style.color = ''
    probe.style.color = v                    // 不是颜色的话浏览器会拒绝，style.color 留空
    if (probe.style.color) legal.add(getComputedStyle(probe).color)
  }
  probe.remove()

  const bad = []
  let scanned = 0
  for (const el of document.querySelectorAll('*')) {
    // 只看自己直接带字的元素，不看容器 —— 否则一段字会被父链上每一层重复计一次
    const txt = [...el.childNodes]
      .filter((n) => n.nodeType === 3 && n.textContent.trim())
      .map((n) => n.textContent.trim()).join('')
    if (!txt) continue
    const s = getComputedStyle(el)
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) === 0) continue
    scanned++
    if (!legal.has(s.color)) {
      bad.push(`${s.color} ← ${el.tagName.toLowerCase()}.${String(el.className||'').slice(0,26)}「${txt.slice(0,16)}」`)
    }
  }
  return { legal: legal.size, scanned, bad }
}

const b = await chromium.launch()

for (const scheme of ['light', 'dark']) {
  const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], colorScheme: scheme })
  const pg = await ctx.newPage()
  await pg.goto(APP)
  await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))

  let totalScanned = 0
  let paletteSize = 0
  for (const [label, hash, tab] of ROUTES) {
    await pg.goto(APP + hash); await pg.reload(); await pg.waitForTimeout(700)
    if (tab) {
      await pg.getByRole('button', { name: tab }).first().click()
      await pg.waitForTimeout(500)
    }
    const r = await pg.evaluate(SCAN)
    paletteSize = r.legal
    totalScanned += r.scanned
    t(`[${scheme}] ${label}：没有调色板以外的文字颜色`,
      r.bad.length === 0, r.bad.slice(0, 3).join(' ｜ '))
  }

  // 「0 处违规」也可能是根本没扫到东西。这两条把假绿堵住
  t(`[${scheme}] 调色板真的读出来了`, paletteSize > 20, `读到 ${paletteSize} 个`)
  t(`[${scheme}] 七个屏真的扫到了字`, totalScanned > 200, `一共扫了 ${totalScanned} 段`)

  await ctx.close()
}

await b.close()
console.log(fail ? `\n${fail} 条没过` : '\n全过')
process.exit(fail ? 1 : 0)
