// 她一天开好几次 Prompt 管理器，而且多半是奔着同一类去的（调研 / 写东西）。
// 问题很具体：关掉再开，它还记得我刚才在哪一类吗？还是每次都从 40 条的顶上重来？
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const URL = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const pg = await ctx.newPage()
await pg.goto(URL)
await pg.evaluate((s)=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
await pg.goto(URL+'#/today'); await pg.reload(); await pg.waitForTimeout(600)

const open = async () => { await pg.locator('.tabbar button:has-text("Prompt")').click(); await pg.waitForTimeout(600) }
const close = async () => { await pg.locator('.sheet .icon-btn').first().click(); await pg.waitForTimeout(500) }
const cur = () => pg.locator('.sheet .chip.on').first().innerText()
const count = () => pg.locator('.sheet .plist .pitem').count()

await open()
t('默认落在「全部」', (await cur()).includes('全部'), await cur())
const all = await count()
await pg.locator('.sheet button.chip:has-text("调研")').click(); await pg.waitForTimeout(400)
const few = await count()
t('选「调研」之后列表变短了', few < all, `${all} → ${few}`)
await close()
await open()
const after = await cur()
t('关掉再开，还记得停在「调研」', after.includes('调研'), `实际停在「${after}」`)

// 搜过的词呢
await pg.locator('.sheet input.field.pill').fill('成本')
await pg.waitForTimeout(400)
const searched = await count()
t('搜「成本」能搜到', searched > 0 && searched < all, `${searched} 条`)
await close(); await open()
const kept = await pg.locator('.sheet input.field.pill').inputValue()
t('关掉再开，搜索框清空了（这个该清）', kept === '', `实际「${kept}」`)
// 记住了，也得能改回去
await pg.locator('.sheet button.chip:has-text("全部")').click(); await pg.waitForTimeout(400)
await close(); await open()
t('切回「全部」也记得住', (await cur()).includes('全部'), await cur())
t('回到「全部」时 40 条都在', (await count()) === all, `${await count()} 条`)

// 整页刷新之后（她把 App 关掉重开）
await pg.locator('.sheet button.chip:has-text("写东西")').click(); await pg.waitForTimeout(400)
await close()
await pg.reload(); await pg.waitForTimeout(800)
await open()
t('把 App 关掉重开，也还记得', (await cur()).includes('写东西'), await cur())
await b.close()
process.exit(fail ? 1 : 0)
