/**
 * 她贴进来的是客户的邮件、群里的聊天记录。在她自己拿去问 AI 之前，
 * 这些东西一个字都不该离开这台手机 —— 「不上传」是写在页面上的承诺，
 * 这条把它变成能失败的检查：把整条路走一遍，记下每一个请求，
 * 只要有一个不是自家域名就红。
 *
 * 「复制并打开 ChatGPT / Claude」是她主动点的外链，那是她自己要发出去的，
 * 不算；这里专门不点它们。
 */
import pkg from 'playwright'
import { SAMPLES } from './samples.mjs'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
// 这个文件里 URL 是字符串常量，把全局的 URL 类遮住了；用 globalThis.URL 拿回真的那个
const ORIGIN = new globalThis.URL(URL).origin
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const SECRET = '客户说预算砍到 30 万，这句话只该留在这台手机上'
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'] })
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
await pg.evaluate(() => localStorage.clear())
await pg.reload({ waitUntil: 'load' })

// 把会碰到她内容的每一条路径都走到
const text = SAMPLES.find((s) => s.name.startsWith('微信群聊')).text + '\n王总：' + SECRET
await pg.evaluate((x) => navigator.clipboard.writeText(x), text)
await pg.locator('.paste-btn').click(); await pg.waitForTimeout(300)
t('那句话确实贴进来了（这条路径真的走到了）', (await pg.locator('[data-material]').inputValue()).includes(SECRET))
for (const label of ['帮我回', '拆待办', '翻译']) {
  await pg.locator('.intent', { hasText: label }).click(); await pg.waitForTimeout(150)
}
await pg.locator('.note input').fill('语气客气点'); await pg.waitForTimeout(150)
await pg.locator('.copy').click(); await pg.waitForTimeout(150)
await pg.locator('.seg button', { hasText: 'Claude' }).click()
await pg.locator('.card').click({ position: { x: 40, y: 80 } }); await pg.waitForTimeout(150)
await pg.locator('.ghost', { hasText: '最近' }).click(); await pg.waitForTimeout(200)
await pg.keyboard.press('Escape')
await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(600)
t('复制过的进了「最近」（存储路径也真的走到了）',
  await pg.evaluate((s) => (localStorage.getItem('suishou.v1') || '').includes(s), SECRET))

const outside = [...seen].filter((o) => o !== ORIGIN)
t('全程没有任何一个请求出过自家域名', outside.length === 0, outside.join(' | ') || `${requests} 个请求，全在 ${ORIGIN}`)
t('确实记到了请求（不是因为什么都没监听到才「干净」）', requests > 0, String(requests))

// 页面代码里不许藏着能往外发东西的口子
const code = await pg.evaluate(async () => {
  const src = [...document.scripts].map((s) => s.src).filter(Boolean)
  const bodies = await Promise.all(src.map((u) => fetch(u).then((r) => r.text())))
  return bodies.join('\n')
})
const leaks = ['sendBeacon', 'XMLHttpRequest', 'WebSocket', 'google-analytics', 'gtag(', 'sentry']
  .filter((w) => code.includes(w))
t('打包后的代码里没有埋点 / 上报的口子', leaks.length === 0, leaks.join(', ') || `查了 ${(code.length / 1024) | 0}KB`)
await b.close()
process.exit(fail ? 1 : 0)
