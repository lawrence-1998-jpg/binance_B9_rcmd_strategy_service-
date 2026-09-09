import pkg from 'playwright'
const { chromium, devices } = pkg
import { execSync } from 'node:child_process'
import fs from 'node:fs'

/**
 * 新版本到底会不会到她手上。
 *
 * 第一次跑这条的结论是：**要开两次才拿得到新版**。也就是我每修一个 bug，
 * 她第一次打开看到的还是坏的。所以这条测试从此是硬指标——
 * 三关全绿才算「已部署」这句话是真的：
 *   ① 打开一次就换过来（她什么都不用做）
 *   ② 用着用着才出的新版，浮一条出来，不打断她
 *   ③ 点那一条，真的换过去
 */
const DESK = new globalThis.URL('..', import.meta.url).pathname
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const TODAY = DESK + '/src/screens/Today.tsx'
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0

const orig = fs.readFileSync(TODAY, 'utf8')
/** 往源码里塞一个能认出来的标记，重新构建 = 造一个「新版本」 */
function deploy(mark) {
  fs.writeFileSync(TODAY, orig.replace('<InstallNotice />', `<InstallNotice />\n      <span data-swtest>${mark}</span>`))
  try { execSync('npm run build', { cwd: DESK, stdio: 'ignore' }) } finally { fs.writeFileSync(TODAY, orig) }
}
const markOf = (pg) => pg.evaluate(() => document.querySelector('[data-swtest]')?.textContent ?? null)

// Service Worker 自己发的请求绕过 playwright 的 route，在这个没有外网的沙箱里
// 会一直挂着——旧 SW 手上挂着请求就让不了位，测出来的全是环境的毛病。
// 把字体域名解到本地，让它快速失败
const b = await chromium.launch({
  args: ['--host-resolver-rules=MAP fonts.googleapis.com 127.0.0.1:1, MAP fonts.gstatic.com 127.0.0.1:1'],
})
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], ignoreHTTPSErrors: true })
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort())
const pg = await ctx.newPage()

try {
  // ---- A 版：装上，就当是她手机上现在跑着的那一版 ----
  await pg.goto(URL, { waitUntil: 'domcontentloaded' }); await pg.waitForTimeout(2000)
  const swA = await pg.evaluate(async () => {
    const r = await navigator.serviceWorker.getRegistration()
    return r?.active ? 'active' : r ? 'installing' : 'none'
  })
  t('A 版：SW 装上了', swA === 'active', swA)
  t('A 版身上没有标记（干净的基线）', (await markOf(pg)) === null)

  // ---- ① 我部署了 B。她打开一次，应该就拿到 B ----
  const B = 'B_' + Date.now()
  deploy(B)
  await pg.goto(URL, { waitUntil: 'domcontentloaded' })
  for (let i = 1; i <= 12; i++) {
    await pg.waitForTimeout(1000)
    const st = await pg.evaluate(async () => {
      const r = await navigator.serviceWorker.getRegistration()
      return { w: !!r?.waiting, i: !!r?.installing, m: document.querySelector('[data-swtest]')?.textContent ?? null,
               p: !!document.querySelector('.update-pill') }
    }).catch(() => ({ nav: true }))
    console.log('   ', i + 's', JSON.stringify(st))
    if (st.m) break
  }
  const got = await markOf(pg)
  t('① 打开一次就拿到新版本', got === B, got ?? '还是旧的')

  // ---- ② 她正开着，我部署了 C。不许打断她，浮一条出来就行 ----
  const C = 'C_' + Date.now()
  await pg.locator('body').click({ position: { x: 200, y: 300 } })  // 她开始用了
  deploy(C)
  await pg.waitForTimeout(13000)  // 熬过 12s 宽限期：这之后就不许自作主张刷了
  await pg.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration(); await r?.update() })
  await pg.waitForTimeout(4000)

  const stillB = await markOf(pg)
  t('② 没有偷偷把她的页面刷掉', stillB === B, stillB ?? 'null')
  const pill = pg.locator('.update-pill')
  const shown = await pill.count() > 0
  t('② 浮出「有新版本」', shown, shown ? await pill.innerText().then(x => x.replace(/\n/g, ' ')) : '没出现')

  if (shown) {
    const box = await pill.boundingBox()
    t('② 那一条够大，走路上单手能点', box.height >= 44, `${Math.round(box.width)}×${Math.round(box.height)}`)

    // ---- ③ 点它，真的换过去 ----
    await pill.click()
    await pg.waitForTimeout(5000)
    const after = await markOf(pg)
    t('③ 点一下换到新版本', after === C, after ?? 'null')
  }

  const reg = await pg.evaluate(async () => {
    const r = await navigator.serviceWorker.getRegistration()
    return { active: !!r?.active, waiting: !!r?.waiting, installing: !!r?.installing }
  })
  t('换完之后没有残留在等的 SW', reg.waiting === false, JSON.stringify(reg))
} finally {
  // dist 必须还原成干净的版本，否则下一次跑测试的「基线」自带上一轮的标记，
  // 结果全是假的（踩过一次，白查了半小时）
  fs.writeFileSync(TODAY, orig)
  execSync('npm run build', { cwd: DESK, stdio: 'ignore' })
  await b.close()
}
console.log(fail ? `\n✗ ${fail} 条不过 —— 更新路径还是瘸的` : '\n✓ 更新路径通了：她打开一次就是最新的')
process.exit(fail ? 1 : 0)
