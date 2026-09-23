/**
 * 整条路走一遍：贴进来 → 换用途 → 补一句 → 复制 → 撤销 → 最近 → 再打开。
 *
 * 每一步都去**读真的剪贴板**，而不是看按钮上写了什么 ——
 * 按钮写着「已复制」而剪贴板里是旧的那版，恰恰是这个工具最不能出的错。
 */
import pkg from 'playwright'
import { SAMPLES } from './samples.mjs'
const { chromium, devices } = pkg

const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
let fail = 0
const t = (n, ok, note = '') => { console.log(`${ok ? '✓' : '✗'} ${n}${note ? ' — ' + note : ''}`); if (!ok) fail++ }
const CHAT = SAMPLES.find((s) => s.name.startsWith('微信群聊')).text
const ERR = SAMPLES.find((s) => s.name === 'Python 报错').text

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13'], permissions: ['clipboard-read', 'clipboard-write'] })
// 「去 ChatGPT / Claude」是外链，这里不真出网
const opened = []
await ctx.route(/^https:\/\/(?!127\.0\.0\.1)/, (r) => { opened.push(r.request().url()); return r.abort() })
const pg = await ctx.newPage()
const errs = []
pg.on('pageerror', (e) => errs.push(e.message))

const clip = () => pg.evaluate(() => navigator.clipboard.readText())
const setClip = (s) => pg.evaluate((x) => navigator.clipboard.writeText(x), s)
const mat = () => pg.locator('[data-material]').inputValue()
const bar = () => pg.locator('.copy').innerText().then((x) => x.replace(/\s+/g, ' '))
const toast = () => pg.locator('.toast').innerText().catch(() => '')
const settle = () => pg.waitForTimeout(250)

try {
  await pg.goto(URL, { waitUntil: 'load' })
  await pg.evaluate(() => localStorage.clear())
  await pg.reload({ waitUntil: 'load' })

  // ---------------------------------------------------------------- 空着
  const pb = pg.locator('.paste-btn')
  const box = await pb.boundingBox()
  t('空着的时候：「从剪贴板贴入」是一整条大按钮', !!box && box.height >= 64 && box.width >= 300, box ? `${Math.round(box.width)}×${Math.round(box.height)}` : '没找到')
  t('空着的时候：没有底栏（没东西可复制）', (await pg.locator('.bar').count()) === 0)

  // ---------------------------------------------------------------- 贴进来 = 已经复制好了
  await setClip(CHAT)
  await pb.click(); await settle()
  t('贴进来了', (await mat()) === CHAT)
  t('认出来是聊天记录', (await pg.locator('.kind').innerText()).includes('聊天记录'))
  const c1 = await clip()
  t('贴进来那一下，剪贴板里就已经是 Prompt 了（一下都不用多点）', c1.startsWith('你是') && c1.includes(CHAT), c1.slice(0, 30))
  t('底栏说「已复制」', (await bar()).includes('已复制'), await bar())
  t('推荐的那个用途标着 ✓', (await pg.locator('.intent.done').innerText()).includes('总结'))
  t('Prompt 卡片右上角也说「已复制」', (await pg.locator('.card-hint').innerText()).includes('已复制'))

  // ---------------------------------------------------------------- 点用途 = 复制那一版
  await pg.locator('.intent', { hasText: '帮我回' }).click(); await settle()
  const c2 = await clip()
  t('点「帮我回」：剪贴板换成回复那一版', c2.includes('帮我回复') && c2 !== c1)
  t('✓ 跟着挪到「帮我回」', (await pg.locator('.intent.done').innerText()).includes('帮我回'))

  // ---------------------------------------------------------------- 改了一个字，就不能再说「已复制」
  await pg.locator('.note input').fill('婉拒但留余地'); await settle()
  t('补了一句之后，底栏不再说「已复制」（剪贴板里还是旧的）', !(await bar()).includes('已复制'), await bar())
  t('……而是提醒「复制新版本」', (await bar()).includes('复制新版本'))
  t('剪贴板确实还是旧的（没有偷偷变）', (await clip()) === c2)
  await pg.locator('.copy').click(); await settle()
  t('点底栏：剪贴板里带上了补的那句', (await clip()).includes('婉拒但留余地'))
  t('底栏回到「已复制」', (await bar()).includes('已复制'))

  // ---------------------------------------------------------------- 整张卡片都能点
  await pg.locator('.seg button', { hasText: 'Claude' }).click(); await settle()
  t('换成 Claude 格式：底栏又变回「复制」', !(await bar()).includes('已复制'))
  await pg.locator('.card').click({ position: { x: 60, y: 120 } }); await settle()
  const c3 = await clip()
  t('点卡片中间任意一处：复制了 Claude 格式的全文', c3.startsWith('<material') && c3.includes('</task>'), c3.slice(0, 24))

  // 拖选了几行、只想要那几行的时候，松手不能把整段 Prompt 顶进剪贴板
  await setClip('SENTINEL')
  await pg.evaluate(() => {
    const pre = document.querySelector('.pv')
    const r = document.createRange()
    r.selectNodeContents(pre.firstElementChild)
    const s = getSelection(); s.removeAllRanges(); s.addRange(r)
    document.querySelector('.card').click()
  })
  await settle()
  t('卡片上选中了一段文字时，点它不会整段复制', (await clip()) === 'SENTINEL')
  await pg.evaluate(() => getSelection().removeAllRanges())

  // ---------------------------------------------------------------- 键盘
  await pg.locator('.note input').fill('只要结论'); await settle()
  await pg.locator('.note input').press('Control+Enter'); await settle()
  t('Ctrl+↵（在输入框里也行）：复制', (await clip()).includes('只要结论'))
  await pg.locator('.note input').blur()
  await pg.keyboard.press('3'); await settle()
  const third = await pg.locator('.intent').nth(2).innerText()
  t('按数字 3：选第三个用途并复制', (await pg.locator('.intent.done').innerText()) === third, third.replace(/\s+/g, ''))

  // ---------------------------------------------------------------- 手改
  await pg.locator('.mini', { hasText: '手改' }).click()
  await pg.locator('.out-edit').press('End')
  await pg.locator('.out-edit').pressSequentially('——我自己加的一行')
  await pg.locator('.mini', { hasText: '改好了' }).click(); await settle()
  t('手改之后标着「手改过」', (await pg.locator('.out-t').innerText()).includes('手改过'))
  await pg.locator('.copy').click(); await settle()
  t('复制的是手改的那版', (await clip()).includes('——我自己加的一行'))
  await pg.locator('.intent', { hasText: '总结' }).click(); await settle()
  t('换用途会覆盖手改 —— 但给「撤销」', (await toast()).includes('撤销'), await toast())
  await pg.locator('.toast button').click(); await settle()
  t('撤销：手改的那版回来了', (await pg.locator('.pv').innerText()).includes('——我自己加的一行'))

  // ---------------------------------------------------------------- 页面任何地方 Ctrl+V = 换一段
  await pg.locator('.seg button', { hasText: '通用' }).click()
  await setClip(ERR)
  await pg.locator('.kind').click()
  await pg.keyboard.press('Control+V'); await settle()
  t('在页面空白处 Ctrl+V：换成了新贴的', (await mat()) === ERR)
  t('认出来是报错，推荐「排查」', (await pg.locator('.intent').first().innerText()).includes('排查'))
  const c4 = await clip()
  t('新贴的这段也自动复制好了', c4.includes('帮我排查') && c4.includes('KeyError'))
  t('换掉旧的有「撤销」', (await toast()).includes('撤销'))
  await pg.locator('.toast button').click(); await settle()
  t('撤销：群聊回来了，连补的那句都在', (await mat()) === CHAT && (await pg.locator('.note input').inputValue()) === '只要结论')

  // 在框里正常编辑时插一段，是编辑，不是换
  await setClip('（补一行）')
  const ta = pg.locator('[data-material]')
  await ta.click()
  await ta.evaluate((el) => el.setSelectionRange(el.value.length, el.value.length))
  await pg.keyboard.press('Control+V'); await settle()
  t('在框里光标处粘贴：是插进去，不是整段换掉', (await mat()) === CHAT + '（补一行）', (await mat()).slice(-12))
  await ta.fill(CHAT); await ta.blur()

  // ---------------------------------------------------------------- 复制并打开
  await setClip('SENTINEL')
  const href = await pg.locator('.go-a', { hasText: 'ChatGPT' }).getAttribute('href')
  t('去 ChatGPT：网址里预填了 Prompt', href.startsWith('https://chatgpt.com/?q=') && decodeURIComponent(href.split('?q=')[1]).includes(CHAT))
  const popup = ctx.waitForEvent('page', { timeout: 3000 }).catch(() => null)
  await pg.locator('.go-a', { hasText: 'Claude' }).click()
  const p2 = await popup
  await settle()
  t('点「Claude」：先复制', (await clip()).startsWith('你是'))
  const went = opened.find((u) => u.startsWith('https://claude.ai/new'))
  t('……再在新标签页打开 Claude（带着预填）', !!p2 && !!went && went.includes('?q='), (went ?? opened.join(' ')).slice(0, 40))
  await p2?.close()

  const long = CHAT + '\n' + '很长的一段补充材料。'.repeat(2600)
  await pg.locator('[data-material]').fill(long); await settle()
  const href2 = await pg.locator('.go-a', { hasText: 'ChatGPT' }).getAttribute('href')
  t('太长放不进网址时，只打开、不预填（靠剪贴板）', href2 === 'https://chatgpt.com/', href2.slice(0, 40))
  t('太长时提醒：有的 AI 一次装不下', (await pg.locator('.warn').count()) === 1)
  await pg.locator('[data-material]').fill(CHAT); await settle()

  // ---------------------------------------------------------------- 最近
  await pg.locator('.ghost', { hasText: '最近' }).click(); await settle()
  const items = pg.locator('.hist li')
  const n = await items.count()
  t('「最近」里有刚才复制过的（同一段材料只留一条）', n === 2, `${n} 条`)
  await pg.keyboard.press('Escape'); await settle()
  t('Esc 关掉', (await pg.locator('.sheet').count()) === 0)
  await pg.locator('.ghost', { hasText: '最近' }).click(); await settle()
  await items.filter({ hasText: 'Traceback' }).locator('.hist-b').click(); await settle()
  t('点一条：那段材料回来了', (await mat()) === ERR)
  t('……用途也回来了', (await pg.locator('.intent.on').innerText()).includes('排查'))
  await pg.locator('.ghost', { hasText: '最近' }).click(); await settle()
  await items.first().locator('.mini.x').click(); await settle()
  t('删掉一条', (await items.count()) === n - 1)
  await pg.locator('.toast button').click(); await settle()
  t('删了也能撤销', (await items.count()) === n)
  await pg.locator('.scrim').click({ position: { x: 10, y: 10 } }); await settle()
  t('点外面关掉', (await pg.locator('.sheet').count()) === 0)

  // ---------------------------------------------------------------- 切走再回来
  await pg.locator('.note input').fill('切走前写的'); await settle()
  await pg.evaluate(() => { Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true }); document.dispatchEvent(new Event('visibilitychange')) })
  await pg.reload({ waitUntil: 'load' }); await settle()
  t('刷新之后，正在弄的那条还在', (await mat()) === ERR && (await pg.locator('.note input').inputValue()) === '切走前写的')

  // ---------------------------------------------------------------- 清空 + 撤销
  await pg.locator('.mini.x[aria-label="清空"]').click(); await settle()
  t('清空：回到「贴进来」', (await pg.locator('.paste-btn').count()) === 1)
  await pg.locator('.toast button').click(); await settle()
  t('清空也能撤销', (await mat()) === ERR)

  // ---------------------------------------------------------------- 关掉自动复制
  await pg.locator('.ghost', { hasText: '新的' }).click(); await settle()
  await pg.locator('.switch').click()
  await setClip(CHAT)
  await pg.locator('.paste-btn').click(); await settle()
  t('关掉「自动复制」后：贴进来不动剪贴板', (await clip()) === CHAT)
  t('……底栏说「复制 Prompt」等她点', (await bar()).includes('复制 Prompt'))
  await pg.locator('.ghost', { hasText: '新的' }).click(); await settle()
  await pg.locator('.switch').click()

  // ---------------------------------------------------------------- 剪贴板是空的
  await setClip('   ')
  await pg.locator('.paste-btn').click(); await settle()
  t('剪贴板是空的：说一声，不假装贴进来了', (await toast()).includes('没有文字') && (await pg.locator('.paste-btn').count()) === 1)

  // ---------------------------------------------------------------- 从别的 App 分享进来
  await pg.goto(URL + '?text=' + encodeURIComponent('看看这篇 https://example.com/a') + '&url=' + encodeURIComponent('https://example.com/a'), { waitUntil: 'load' })
  await settle()
  t('分享进来的内容直接就位（链接不重复）', (await mat()) === '看看这篇 https://example.com/a', JSON.stringify(await mat()))
  t('网址上的参数清掉了（刷新不会再贴一次）', !pg.url().includes('?'))

  t('全程没有页面报错', errs.length === 0, errs.slice(0, 2).join(' | '))
} finally {
  await b.close()
}

// ---------------------------------------------------------------- 读不了剪贴板的设备
{
  const b2 = await chromium.launch()
  const c2 = await b2.newContext({ ...devices['iPhone 13'] })
  const p = await c2.newPage()
  await p.goto(URL, { waitUntil: 'load' })
  await p.evaluate(() => localStorage.clear())
  await p.reload({ waitUntil: 'load' })
  await p.evaluate(() => { navigator.clipboard.readText = () => Promise.reject(new Error('NotAllowed')) })
  await p.locator('.paste-btn').click(); await p.waitForTimeout(250)
  const msg = await p.locator('.toast').innerText().catch(() => '')
  t('读不了剪贴板：告诉她长按输入框粘贴', msg.includes('长按') && msg.includes('粘贴'), msg)
  t('……并且把光标放进输入框', await p.evaluate(() => document.activeElement?.hasAttribute('data-material')))
  await b2.close()
}

process.exit(fail ? 1 : 0)
