/**
 * 她贴进来的是客户的消息、名片、报价。「只存在这台设备」要变成能失败的检查：
 *
 *   ① 没开 Claude：全程一个请求都不出这个网站 —— 连 Claude 的 SDK 都不下载
 *   ② 开了 Claude：出去的请求只到 api.anthropic.com；Key 只出现在发给它的请求头里，
 *      不进网址、不进卡片、不进导出的备份
 *   ③ 关掉之后：Key 从这台设备上删干净，之后一个请求都不再发
 *   ④ 打包后的代码里没有埋点 / 上报 / 外链字体
 */
import pkg from 'playwright'
import { readFileSync, readdirSync } from 'node:fs'
import { mockAnthropic, TEST_KEY } from './mock-anthropic.mjs'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const ORIGIN = new globalThis.URL(URL).origin
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const SECRET = '客户说预算砍到 30 万，这句话只该她自己看得到'
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'], acceptDownloads: true })
const api = await mockAnthropic(ctx)
const reqs = []
ctx.on('request', (r) => {
  const u = r.url()
  if (u.startsWith('data:') || u.startsWith('blob:')) return
  reqs.push({ url: u, headers: r.headers(), body: r.postData() ?? '' })
})
const pg = await ctx.newPage()
const wait = (ms = 250) => pg.waitForTimeout(ms)
const outside = () => reqs.filter((r) => !r.url.startsWith(ORIGIN))
const paste = async (text) => { await pg.evaluate((x) => navigator.clipboard.writeText(x), text); await pg.locator('#capture').focus(); await pg.keyboard.press('Control+V'); await wait(500) }

await pg.goto(URL, { waitUntil: 'load' })
await wait(500)

// ---------------------------------------------------------------- ① 没开 Claude
// 把会碰到她内容的路径都走一遍：收、勾待办、置顶、复制、删、撤销、截图、搜索、导出
await paste('王总：周五上午 10 点国贸见，记得带合同。' + SECRET)
const c = pg.locator('.card.open')
await c.locator('.todo').first().click()
await c.locator('.acts button', { hasText: '置顶' }).click()
await c.locator('.ask').click()
await wait()
await c.locator('.acts .danger').click(); await wait(200)
await pg.locator('.toast button', { hasText: '撤销' }).click(); await wait(300)
await pg.evaluate(async () => {
  const cv = document.createElement('canvas'); cv.width = 300; cv.height = 300
  const blob = await new Promise((r) => cv.toBlob(r, 'image/png'))
  const dt = new DataTransfer(); dt.items.add(new File([blob], 's.png', { type: 'image/png' }))
  document.querySelector('#capture').dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
})
await wait(400)
await pg.locator('.ghost[aria-label="搜索"]').click()
await pg.locator('#search').fill('预算'); await wait()
await pg.locator('.ghost[aria-label="搜索"]').click()
await pg.locator('.ghost[aria-label="设置"]').click()
const [dl] = await Promise.all([pg.waitForEvent('download'), pg.locator('.sheet .btn', { hasText: '导出备份' }).click()])
const backup1 = readFileSync(await dl.path(), 'utf8')

t('那句话真的存进去了（这条路径确实走到了）', backup1.includes(SECRET))
t('没开 Claude：全程没有任何一个请求出过这个网站', outside().length === 0, outside().map((r) => r.url).join(' | ') || `${reqs.length} 个请求，全在 ${ORIGIN}`)
t('确实记到了请求（不是什么都没监听到才「干净」）', reqs.length > 0, String(reqs.length))
// Claude SDK 单独打成一块，只在真要用时才加载。认出是哪一块：它里面有直连浏览器的那个请求头
const ASSETS = new globalThis.URL('../dist/assets/', import.meta.url).pathname
const SDK = readdirSync(ASSETS).find((f) => f.endsWith('.js') && readFileSync(ASSETS + f, 'utf8').includes('anthropic-dangerous-direct-browser-access'))
const sdkFetched = () => reqs.some((r) => SDK && r.url.endsWith('/assets/' + SDK))
t('没开 Claude：连 Claude 的 SDK 都没下载', !!SDK && !sdkFetched(), SDK ?? '没找到 SDK 那一块')

// ---------------------------------------------------------------- ② 开了 Claude
await pg.locator('#apikey').fill(TEST_KEY)
await pg.locator('.sheet .btn', { hasText: '保存并开启' }).click(); await wait(700)
await pg.locator('.sheet .ghost[aria-label="关闭设置"]').click()
const mark = reqs.length
await paste('第二段也只该她看到：' + SECRET + ' 电话 138 1234 5678')
await wait(600)
await pg.locator('.ghost[aria-label="搜索"]').click()
await pg.locator('#search').fill('预算多少')
await pg.locator('.ask-go').click(); await wait(900)
await pg.locator('.ghost[aria-label="搜索"]').click()

t('……开了之后才下载 SDK（上面那条不是因为认错了文件才绿）', sdkFetched())
const after = reqs.slice(mark)
const hosts = [...new Set(after.filter((r) => !r.url.startsWith(ORIGIN)).map((r) => new globalThis.URL(r.url).origin))]
t('开了 Claude：出去的请求只到 api.anthropic.com', hosts.length === 1 && hosts[0] === 'https://api.anthropic.com', hosts.join(' | '))
t('……确实发出去了（整理 + 提问）', api.calls.filter((x) => x.path === '/v1/messages').length >= 2)
const withKey = reqs.filter((r) => JSON.stringify(r.headers).includes(TEST_KEY) || r.body.includes(TEST_KEY) || r.url.includes(TEST_KEY))
t('Key 只出现在发给 api.anthropic.com 的请求头里（不进网址、不进请求正文）',
  withKey.length > 0 && withKey.every((r) => r.url.startsWith('https://api.anthropic.com/') && r.headers['x-api-key'] === TEST_KEY && !r.url.includes(TEST_KEY) && !r.body.includes(TEST_KEY)),
  `${withKey.length} 个请求带着 Key`)
const [dl2] = await Promise.all([pg.waitForEvent('download'), (async () => { await pg.locator('.ghost[aria-label="设置"]').click(); await pg.locator('.sheet .btn', { hasText: '导出备份' }).click() })()])
const backup2 = readFileSync(await dl2.path(), 'utf8')
const idb = await pg.evaluate(() => new Promise((ok) => {
  const r = indexedDB.open('suishou')
  r.onsuccess = () => { const q = r.result.transaction('items').objectStore('items').getAll(); q.onsuccess = () => { ok(JSON.stringify(q.result)); r.result.close() } }
}))
t('Key 不进卡片、不进导出的备份（备份发给别人也不会漏 Key）', !backup2.includes(TEST_KEY) && !idb.includes(TEST_KEY) && backup2.includes('第二段也只该她看到'))

// ---------------------------------------------------------------- ③ 关掉
await pg.locator('.sheet .btn', { hasText: '关掉并删除 Key' }).click(); await wait(200)
await pg.locator('.sheet .ghost[aria-label="关闭设置"]').click()
const store = await pg.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }))
t('关掉之后：这台设备上找不到 Key 了', !store.includes(TEST_KEY))
const mark2 = reqs.length
await paste('关掉之后收的：' + SECRET + ' 再来一次')
t('关掉之后：一个请求都不再往外发', reqs.slice(mark2).filter((r) => !r.url.startsWith(ORIGIN)).length === 0)

// ---------------------------------------------------------------- ④ 打包后的代码
const code = readdirSync(ASSETS).filter((f) => f.endsWith('.js')).map((f) => readFileSync(ASSETS + f, 'utf8')).join('\n')
const leaks = ['sendBeacon', 'XMLHttpRequest', 'new WebSocket', 'google-analytics', 'gtag(', 'sentry', 'fonts.googleapis']
  .filter((w) => code.includes(w))
t('打包后的代码（含 Claude SDK）里没有上报 / 埋点 / 外链字体', code.length > 100_000 && leaks.length === 0, leaks.join(', ') || `查了 ${(code.length / 1024) | 0}KB`)
await b.close()
process.exit(fail ? 1 : 0)
