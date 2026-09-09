import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const today = new Date().toISOString().slice(0, 10)
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
let fail = 0
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
await ctx.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort())
const pg = await ctx.newPage()
const errs = []; pg.on('pageerror', (e) => errs.push(e.message))
await pg.goto(URL, { waitUntil: 'load' })
await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), makeState(today))
await pg.reload({ waitUntil: 'load' }); await pg.waitForTimeout(700)
const n = pg.locator('.install button'); if (await n.count()) { await n.first().click(); await pg.waitForTimeout(300) }

const tabs = await pg.locator('.tab span').allInnerTexts()
console.log('底栏:', tabs.join(' / '))
t('Prompt 上了底栏', tabs.includes('Prompt'), tabs.join('/'))
t('生活还在底栏（没动她的东西）', tabs.includes('生活'))
t('还是四个 tab + 速记键', tabs.length === 4 && await pg.locator('.cap').count() === 1)

// 从任意一屏一步就能到 Prompt
for (const [name, hash] of [['今日', '#/today'], ['工作', '#/work'], ['生活', '#/life'], ['复盘', '#/review']]) {
  await pg.goto(URL + hash, { waitUntil: 'load' }); await pg.reload(); await pg.waitForTimeout(500)
  const nn = pg.locator('.install button'); if (await nn.count()) { await nn.first().click(); await pg.waitForTimeout(200) }
  await pg.locator('.tab:has-text("Prompt")').click(); await pg.waitForTimeout(500)
  const open = await pg.locator('.sheet[aria-label="Prompt 管理器"]').count() === 1
  t(`从「${name}」一步到 Prompt`, open)
  if (open) { await pg.locator('.sheet .icon-btn').last().click(); await pg.waitForTimeout(300) }
}

// 复盘没被弄丢
await pg.goto(URL + '#/today', { waitUntil: 'load' }); await pg.reload(); await pg.waitForTimeout(600)
const n2 = pg.locator('.install button'); if (await n2.count()) { await n2.first().click(); await pg.waitForTimeout(200) }
const rev = pg.locator('button:has-text("去复盘")')
t('首页有常驻的复盘入口（不再只在傍晚出现）', await rev.count() === 1)
await rev.click(); await pg.waitForTimeout(600)
t('点进去真的是复盘', (await pg.locator('.screen').innerText()).includes('这三句'), (await pg.locator('.screen .eyebrow').allInnerTexts()).join('/'))

t('无页面错误', errs.length === 0, errs.slice(0, 2).join(' | '))
await pg.goto(URL + '#/today', { waitUntil: 'load' }); await pg.reload(); await pg.waitForTimeout(600)
await pg.screenshot({ path: OUT + '/tabs-home.png', fullPage: true })
await b.close()
console.log(fail ? `\n✗ ${fail} 条不过` : '\n✓ Prompt 全局一步可达，复盘没丢')
process.exit(fail ? 1 : 0)
