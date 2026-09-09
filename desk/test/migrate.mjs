import pkg from 'playwright'
const { chromium, devices } = pkg
import { execSync } from 'node:child_process'
import { existsSync } from 'node:fs'

/**
 * 她手机上现在跑的是**旧**的 Service Worker（autoUpdate：自己 skipWaiting）。
 * 新版的 SW 不再自己上位，只认页面发来的 SKIP_WAITING —— 而旧页面里
 * 根本没有那段代码。
 *
 * 所以有一个我还没验过、而且赌不起的问题：**她到底能不能从旧版走到新版。**
 * 如果新 SW 装好之后一直等、旧页面又永远不叫它，她就卡在旧版上了，
 * 而我以后每一次修复对她都是隐形的 —— 正是这一整轮要修的那个病，
 * 只不过换成永久版。
 *
 * 这条测的就是：装着旧版，我发了新版，她最少要做什么才能拿到。
 */
const DIST = new globalThis.URL('../dist', import.meta.url).pathname
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
// 先确认源在，再动 DIST。
// 原来是 `rm -rf DIST && cp -r 源 DIST` 一行 —— 源不在的时候 rm 照样成功，
// 于是这条套件把**被测的 App 整个删掉**，后面每一条套件都在测空气，
// 而且各自报出一堆看着很真的失败。/tmp 是会被清掉的，所以这不是假设。
const use = (which) => {
  const src = `/tmp/${which}-dist`
  if (!existsSync(`${src}/index.html`)) {
    throw new Error(`缺少基线 ${src} —— 先建好再跑，绝不能在这儿动 dist（见 migrate.mjs 顶部）`)
  }
  execSync(`rm -rf ${DIST} && cp -r ${src} ${DIST}`)
}
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
// 探针：只是想知道「这一步够不够」，不够不算错 —— 真正的要求写在下面
const probe = (n, ok) => console.log(`  · ${n}：${ok ? '够了' : '不够'}`)

// 新版身上有自托管字体，旧版没有 —— 拿这个当「她现在看到的是哪一版」的标记
const isNew = (pg) => pg.evaluate(async () => {
  const r = await fetch('./index.html').then((x) => x.text()).catch(() => '')
  return !/fonts\.googleapis\.com/.test(r)
})

const b = await chromium.launch({ args: ['--host-resolver-rules=MAP fonts.googleapis.com 127.0.0.1:1, MAP fonts.gstatic.com 127.0.0.1:1'] })
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], ignoreHTTPSErrors: true })
try {
  // ---- 她现在的状态：旧版装着 ----
  use('old')
  const pg = await ctx.newPage()
  await pg.goto(URL, { waitUntil: 'domcontentloaded' }); await pg.waitForTimeout(2500)
  const sw0 = await pg.evaluate(async () => {
    const r = await navigator.serviceWorker.getRegistration()
    return r?.active ? 'active' : 'none'
  })
  t('旧版 SW 装上了（这就是她手机现在的样子）', sw0 === 'active', sw0)
  t('现在看到的确实是旧版', (await isNew(pg)) === false)

  // ---- 我发了新版 ----
  use('new')
  console.log('  （线上换成新版了）')

  // ① 她只是刷新 / 切回前台
  await pg.reload({ waitUntil: 'domcontentloaded' }); await pg.waitForTimeout(4000)
  const a = await isNew(pg)
  probe('① 刷新一次', a)

  // ② 再刷一次
  await pg.reload({ waitUntil: 'domcontentloaded' }); await pg.waitForTimeout(4000)
  const bb = await isNew(pg)
  probe('② 刷第二次', bb)

  const st = await pg.evaluate(async () => {
    const r = await navigator.serviceWorker.getRegistration()
    return { active: !!r?.active, waiting: !!r?.waiting }
  })
  console.log('  这时 SW 状态:', JSON.stringify(st))

  // ③ 彻底关掉再打开（= 从后台划掉 App 重进）
  await pg.close()
  const pg2 = await ctx.newPage()
  await pg2.goto(URL, { waitUntil: 'domcontentloaded' }); await pg2.waitForTimeout(4000)
  const c = await isNew(pg2)

  // 这条才是真要求，也是这整条套件存在的理由：
  // 旧 SW 是 autoUpdate、自己 skipWaiting；新 SW 只认页面发来的 SKIP_WAITING，
  // 而旧页面里没有那段代码。所以「刷新换不过来」是这次迁移的**预期行为**，
  // 不是 bug —— 以前它被写成 ✗，于是整批常年挂着两条永远修不掉的红，
  // 而一条永远微红的检查等于没有检查。
  // 真正赌不起的只有一件事：她**有没有一条路**能走到新版。
  // 没有的话，我以后每一次修复对她都是隐形的。
  t('她能走到新版（最差也就是把 App 关掉重开）', c, c ? '' : '⚠️ 关掉重开都不行 —— 她会永久卡在旧版')
  t('而且不需要她做任何「关掉重开」之外的事', a || bb || c)

  console.log(`\n她最少要做的：${a ? '什么都不用做，刷新/切回来就行' : bb ? '刷新两次' : c ? '把 App 彻底关掉再打开（我告诉她的就是这个）' : '⚠️ 都不行'}`)
} finally {
  // 还原失败也要说出来，不能悄悄留一个别的版本在 dist 里
  try { use('new') } catch (e) { console.log('✗ 没能把 dist 还原成新版 — ' + e.message); fail++ }
  await b.close()
}
process.exit(fail ? 1 : 0)
