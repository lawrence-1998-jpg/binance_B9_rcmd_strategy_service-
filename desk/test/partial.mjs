// 备份文件缺字段的时候，不许拿演示数据顶上。
//
// `merge()` 里好几项的兜底是**种子数据**：
//
//     const base = seed()
//     tasks:        arr(p.tasks, base.tasks)
//     engagements:  arr(p.engagements, base.engagements)
//     anniversaries: arr(p.anniversaries, base.anniversaries)
//     trip:         { ...base.trip, ...obj(p.trip) }
//
// 于是一份**缺字段**的存档（早于某个集合存在的老备份、被截断的文件）
// 恢复之后，「会员体系诊断 · 客户 A」「订往返机票」这些演示数据会**当成她的
// 数据**出现在屏幕上。不报错、不留空，而是凭空多出几个她从没建过的项目。
//
// 而这个兜底在**两个调用点上都是错的**：
//
//   load()        —— 读她自己存着的数据。少了个字段是她的老版本，不是「该来点演示」
//   importState() —— 恢复备份。同上，而且更严重
//
// 真正该出现种子数据的地方是全新安装，而那条路**根本不走 merge**：
// `load()` 在 `!raw` 时直接 `return seed()`。
//
// 所以 merge 的底座换成 `empty()`（已经有了，就是 seed 去掉全部用户内容）。
import pkg from 'playwright'
const { chromium, devices } = pkg
import fs from 'node:fs'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

// 种子里的几句话。它们出现在屏幕上就说明演示数据漏进来了
const DEMO = ['会员体系诊断', '增长策略陪跑', 'Q4 OKR 对齐', '订往返机票',
              '客户 A 周会', '一起去看一次日出', '推荐位改版需求文档过一遍']

// 一份「早期版本」的存档：有版本号、有她真实的一条日记，
// 但缺 engagements / tasks / notes / meetings / anniversaries / wishes / trip / logs
const THIN = {
  version: 1,
  seeded: true,
  focus: {},
  // DayEntry 的形状是 { date, lines: [三句], auto, updatedAt } —— 别自己编字段名
  entries: [{ date: '2026-09-01', lines: ['这是她真的写过的一句', '', ''], auto: false, updatedAt: 1756684800000 }],
  photos: [], moments: [], myPrompts: [], inquiries: [],
  promptUses: {}, promptParts: [], promptCat: null, hidden: [], kept: {},
}

const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'], acceptDownloads: true })

// ---- 路径一：她自己存着的数据就是这样（load → merge）----
{
  const pg = await ctx.newPage()
  await pg.goto(APP)
  await pg.evaluate((s) => localStorage.setItem('deskside.v1', JSON.stringify(s)), THIN)
  await pg.goto(APP + '#/work'); await pg.reload(); await pg.waitForTimeout(700)

  // ⚠️ 这里**不能**去读 localStorage 判断。
  // 迁移是惰性的：load() 只在内存里翻译，下次 update() 才落盘。
  // 所以这会儿 localStorage 里还是原样的 THIN，
  // `st.engagements?.length ?? 0` 稳稳等于 0 —— 一条**永远通过**的假断言。
  // 第一版就是这么写的，屏幕上明明摆着「会员体系诊断」，它照样绿。
  // 要看她眼睛看到的东西。
  const onWork = await pg.evaluate(() => document.body.innerText)
  await pg.goto(APP + '#/life'); await pg.reload(); await pg.waitForTimeout(700)
  const onLife = await pg.evaluate(() => document.body.innerText)
  await pg.goto(APP + '#/today'); await pg.reload(); await pg.waitForTimeout(700)
  const onToday = await pg.evaluate(() => document.body.innerText)

  const leaked = [...new Set(DEMO.filter((d) => (onWork + onLife + onToday).includes(d)))]
  t('缺字段的存档：三个屏上没有一句演示数据', leaked.length === 0, leaked.join(' / '))
  t('缺字段的存档：工作屏上没有凭空多出来的项目',
    !onWork.includes('会员体系诊断') && !onWork.includes('增长策略陪跑'))
  t('缺字段的存档：生活屏上没有种子里那个「国庆」行程',
    !onLife.includes('订往返机票'))

  // 她真有的那条不能被顺手清掉 —— 这条防止「全清空」式的过度修复
  // 时间轴那个 tab 是组件内部 state，不吃 URL 参数 —— 得去点它
  await pg.goto(APP + '#/review'); await pg.reload(); await pg.waitForTimeout(700)
  await pg.getByRole('button', { name: '时间轴' }).first().click()
  await pg.waitForTimeout(700)
  const onTl = await pg.evaluate(() => document.body.innerText)
  t('缺字段的存档：她自己那条日记还在', onTl.includes('她真的写过'), onTl.slice(0, 60))
  await pg.close()
}

// ---- 路径二：她从设置里导入这样一份文件（importState → merge）----
{
  const file = `${OUT}/thin-backup.json`
  fs.writeFileSync(file, JSON.stringify(THIN), 'utf8')

  const pg = await ctx.newPage()
  await pg.goto(APP + '#/review'); await pg.reload(); await pg.waitForTimeout(600)
  await pg.locator('button[aria-label=设置]').click(); await pg.waitForTimeout(400)
  await pg.locator('input[type=file]').setInputFiles(file)
  await pg.waitForTimeout(400)
  await pg.locator('button:has-text("确认导入")').click()
  await pg.waitForTimeout(1500)

  const st = await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')))
  t('导入缺字段的文件：engagements 留空',
    (st.engagements?.length ?? 0) === 0, `有 ${st.engagements?.length} 条`)
  t('导入缺字段的文件：trip 留空', !st.trip?.title, JSON.stringify(st.trip?.title))
  t('导入缺字段的文件：她那条日记进来了', st.entries?.length === 1 && st.entries[0].lines[0].includes('她真的写过'))

  await pg.goto(APP + '#/work'); await pg.reload(); await pg.waitForTimeout(700)
  const seen = await pg.evaluate(() => document.body.innerText)
  const leaked = DEMO.filter((d) => seen.includes(d))
  t('导入之后工作屏上没有一句演示数据', leaked.length === 0, leaked.join(' / '))
  await pg.close()
}

// ---- 对照：全新安装该有种子数据，别把这条一起改没了 ----
{
  const fresh = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
  const pg = await fresh.newPage()
  await pg.goto(APP + '#/work'); await pg.waitForTimeout(700)
  const seen = await pg.evaluate(() => document.body.innerText)
  t('全新安装（localStorage 空）仍然给种子数据，好让她看到这屏长什么样',
    seen.includes('会员体系诊断'), seen.slice(0, 40))
  await fresh.close()
}

await b.close()
console.log(fail ? `\n${fail} 条没过` : '\n全过')
process.exit(fail ? 1 : 0)
