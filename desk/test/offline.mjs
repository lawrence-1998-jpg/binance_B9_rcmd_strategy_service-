/**
 * 断网（飞机上、地铁里）：本地版照样能收、能整理、能复制、能导出备份。
 * 开着 Claude 的时候断网：卡照样收下，本地整理的留着，说清楚「没连上网」，有网了点一下补上。
 */
import pkg from 'playwright'
import { mockAnthropic, presetKey } from './mock-anthropic.mjs'
const { chromium, devices } = pkg
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }

const b = await chromium.launch()
const errs = []

// ---------------------------------------------------------------- 没开 Claude
{
  const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'], acceptDownloads: true })
  const pg = await ctx.newPage()
  pg.on('pageerror', (e) => errs.push(e.message))
  await pg.goto(URL, { waitUntil: 'load' }); await pg.waitForTimeout(500)
  await ctx.setOffline(true)
  await pg.evaluate(() => navigator.clipboard.writeText('明天下午 3 点跟 Lily 通电话 138 1234 5678，聊报价 ¥36,000'))
  await pg.locator('#capture').focus()
  await pg.keyboard.press('Control+V'); await pg.waitForTimeout(300)
  const c = pg.locator('.card.open')
  t('断网：粘贴照样收下', (await pg.locator('.list article.card').count()) === 1)
  const vals = await c.locator('.row-v').allInnerTexts()
  t('……本地认出了时间、电话、金额', vals.includes('明天下午 3 点') && vals.includes('138 1234 5678') && vals.some((v) => v.includes('36,000')), JSON.stringify(vals))
  await c.locator('.row', { hasText: '电话' }).click(); await pg.waitForTimeout(200)
  t('……点一格复制', (await pg.evaluate(() => navigator.clipboard.readText())) === '138 1234 5678')
  await pg.locator('.ghost[aria-label="设置"]').click()
  const [dl] = await Promise.all([pg.waitForEvent('download'), pg.locator('.sheet .btn', { hasText: '导出备份' }).click()])
  t('……导出备份', !!(await dl.path()))
  await ctx.close()
}

// ---------------------------------------------------------------- 开着 Claude 时断网
{
  const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'] })
  await presetKey(ctx)
  // 断网这段不装假接口：Playwright 的 route 会绕过断网模拟，那就测不到真的「连不上」了。
  // 断着网，请求在浏览器里就失败，碰不到真的 api.anthropic.com
  const pg = await ctx.newPage()
  pg.on('pageerror', (e) => errs.push(e.message))
  await pg.goto(URL, { waitUntil: 'load' }); await pg.waitForTimeout(500)
  t('开着 Claude', (await pg.locator('.cap-hint').innerText()).includes('Claude 帮你整理'))
  await ctx.setOffline(true)
  await pg.locator('#capture').fill('周五上午 10 点国贸见，王总 138 1234 5678')
  await pg.locator('.take').click()
  await pg.waitForTimeout(3500)
  const c = pg.locator('.card.open')
  t('断网时收下：卡在，本地认出来的留着', (await c.locator('.row-v', { hasText: '138 1234 5678' }).count()) === 1)
  t('……说清楚没连上网，不一直转圈', (await c.locator('.note').innerText().catch(() => '')).includes('没连上网') && (await c.locator('.busy-t').count()) === 0,
    await c.locator('.note').innerText().catch(() => '（没有提示）'))
  const api = await mockAnthropic(ctx)
  await ctx.setOffline(false)
  await c.locator('.acts button', { hasText: '重新整理' }).click(); await pg.waitForTimeout(1000)
  t('有网了点「重新整理」：Claude 补上', (await c.getAttribute('data-status')) === 'done' && (await c.locator('h3').innerText()) === '王总的会改到周五', `${api.calls.length} 个请求`)
  await ctx.close()
}

t('没有页面报错', errs.length === 0, errs.join(' | '))
await b.close()
process.exit(fail ? 1 : 0)
