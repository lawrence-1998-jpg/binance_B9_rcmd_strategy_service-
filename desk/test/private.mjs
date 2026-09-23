/**
 * 她贴进来的是客户的消息、名片、报价。这条把「只有你看得到」变成能失败的检查：
 *
 *   ① 全程没有一个请求出过自家域名（没有埋点、没有第三方字体、没有上报）
 *   ② 在 claude.ai 里，每一笔写入都落在她自己那一格 data/users/<她的 id>/ 下 ——
 *      平台保证那一格连 artifact 的主人、被分享的人都读不到。写到别处就等于公开给同事
 *   ③ 打包后的代码里没有能往外发东西的口子
 */
import pkg from 'playwright'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const ORIGIN = new globalThis.URL(URL).origin
const MOCK = new globalThis.URL('./mock-claude.js', import.meta.url).pathname
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const SECRET = '客户说预算砍到 30 万，这句话只该她自己看得到'
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'] })
await ctx.addInitScript({ path: MOCK })
const seen = new Set()
let requests = 0
ctx.on('request', (r) => {
  const u = r.url()
  if (u.startsWith('data:') || u.startsWith('blob:')) return
  requests++
  try { seen.add(new globalThis.URL(u).origin) } catch { seen.add('解析不了:' + u.slice(0, 60)) }
})
const pg = await ctx.newPage()
await pg.goto(URL, { waitUntil: 'load' })
await pg.waitForTimeout(500)

// 把会碰到她内容的路径都走到：收、整理、勾待办、置顶、改标题、删除、撤销
await pg.evaluate((x) => navigator.clipboard.writeText(x), '王总：周五上午 10 点国贸见。' + SECRET)
await pg.locator('#capture').focus()
await pg.keyboard.press('Control+V')
await pg.waitForTimeout(800)
const c = pg.locator('.card.open')
await c.locator('.todo').first().click()
await c.locator('.acts button', { hasText: '置顶' }).click()
await c.locator('.copies .btn', { hasText: '复制给 AI' }).click()
await pg.waitForTimeout(300)
await c.locator('.acts .danger').click()
await pg.waitForTimeout(200)
await pg.locator('.toast button', { hasText: '撤销' }).click()
await pg.waitForTimeout(400)

const writes = await pg.evaluate(() => window.__mock.writes)
const stored = await pg.evaluate(() => sessionStorage.getItem('__mockdb') || '')
t('那句话真的存进去了（这条路径确实走到了）', stored.includes(SECRET))
t('写了好几笔（收、整理、勾、置顶、删、撤销）', writes.length >= 6, `${writes.length} 笔`)
const stray = writes.filter(([, p]) => !p.startsWith('data/users/u_test/'))
t('每一笔都写在她自己那一格 data/users/<她的 id>/ 下', stray.length === 0, stray.map(([op, p]) => `${op} ${p}`).join(' | ') || '全在她自己那一格')

const outside = [...seen].filter((o) => o !== ORIGIN)
t('全程没有任何一个请求出过自家域名', outside.length === 0, outside.join(' | ') || `${requests} 个请求，全在 ${ORIGIN}`)
t('确实记到了请求（不是什么都没监听到才「干净」）', requests > 0, String(requests))

const code = await pg.evaluate(async () => {
  const src = [...document.scripts].map((s) => s.src).filter(Boolean)
  return (await Promise.all(src.map((u) => fetch(u).then((r) => r.text())))).join('\n')
})
const leaks = ['sendBeacon', 'XMLHttpRequest', 'new WebSocket', 'google-analytics', 'gtag(', 'sentry', 'fonts.googleapis']
  .filter((w) => code.includes(w))
t('打包后的代码里没有上报 / 埋点 / 外链字体', code.length > 50_000 && leaks.length === 0, leaks.join(', ') || `查了 ${(code.length / 1024) | 0}KB`)
await b.close()
process.exit(fail ? 1 : 0)
