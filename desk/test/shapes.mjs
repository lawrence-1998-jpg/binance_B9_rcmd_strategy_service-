// 模型回来的题号长什么样，逐个试。
// 提纲里写死了「## 1.」，但换个模型、换次对话就会漂。
// 漂到认不出来 = 她得自己手动切，那这一步就白做了。
import pkg from 'playwright'
const { chromium, devices } = pkg
import { makeState } from './seed.mjs'
const APP = process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today = new Date().toISOString().slice(0,10)
const b = await chromium.launch()
const ctx = await b.newContext({ ...devices['iPhone 13 Pro Max'] })
const pg = await ctx.newPage()
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

const SHAPES = {
  '## 1.  （提纲里要求的）': '## 1. 定价\n按人头三档。\n\n## 2. 续费\n六成到七成五。',
  '### 1.  （多一级）':      '### 1. 定价\n按人头三档。\n\n### 2. 续费\n六成到七成五。',
  '## 第1题':               '## 第1题 定价\n按人头三档。\n\n## 第2题 续费\n六成到七成五。',
  '## 1、（中文顿号）':      '## 1、定价\n按人头三档。\n\n## 2、续费\n六成到七成五。',
  '1.  （没有井号）':        '1. 定价\n按人头三档。\n\n2. 续费\n六成到七成五。',
  '**1.**（加粗，没井号）':  '**1. 定价**\n按人头三档。\n\n**2. 续费**\n六成到七成五。',
  '问题 1：（没井号）':      '问题 1：定价\n按人头三档。\n\n问题 2：续费\n六成到七成五。',
}

// 这些**不该**被认成题号 —— 认错了就是把材料塞进错的调研线，比不塞更糟
const TRAPS = {
  '正文里的编号列表（没有真题号）':
    '关于定价，他们的做法是：\n1. 按人头分三档\n2. 年付打七折\n3. 教育行业另有折扣\n这些都来自官网价目表。',
  '题号不齐（只有 1，缺 2）':
    '1. 定价\n按人头三档。\n\n另外续费率没查到。',
  '题号乱序（2 在 1 前面）':
    '2. 续费\n六成到七成五。\n\n1. 定价\n按人头三档。',
  '号超出题数（有 1 2 3，只有两条线）':
    '1. 定价\n三档。\n\n2. 续费\n六成。\n\n3. 别的\n没了。',
}

for (const [label, answer] of Object.entries(SHAPES)) {
  await pg.goto(APP); await pg.evaluate((s)=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
  await pg.goto(APP+'#/work'); await pg.reload(); await pg.waitForTimeout(600)
  const card = pg.locator('.card', { has: pg.locator('button:has-text("增长策略陪跑")') }).first()
  await card.locator('button:has-text("贴提纲")').first().click(); await pg.waitForTimeout(350)
  await pg.locator('.sheet textarea').first().fill('1、他们怎么定价\n2、续费率一般多少')
  await pg.locator('button:has-text("拆开")').click(); await pg.waitForTimeout(600)
  await card.locator('button:has-text("贴回整套结果")').click(); await pg.waitForTimeout(350)
  await pg.locator('.sheet textarea').first().fill(answer)
  await pg.waitForTimeout(150)
  await pg.locator('button:has-text("按题号分到各条")').click(); await pg.waitForTimeout(600)
  const got = await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')).inquiries
    .filter(q => q.engagementId==='e2').map(q => (q.findings||'').replace(/\n/g,' ').slice(0,22)))
  const ok = got.length === 2 && got[0].includes('按人头三档') && got[1].includes('六成')
  t(`认得出：${label}`, ok, JSON.stringify(got))
}
console.log('--- 下面这些不该被认成题号 ---')
for (const [label, answer] of Object.entries(TRAPS)) {
  await pg.goto(APP); await pg.evaluate((s)=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
  await pg.goto(APP+'#/work'); await pg.reload(); await pg.waitForTimeout(600)
  const card = pg.locator('.card', { has: pg.locator('button:has-text("增长策略陪跑")') }).first()
  await card.locator('button:has-text("贴提纲")').first().click(); await pg.waitForTimeout(350)
  await pg.locator('.sheet textarea').first().fill('1、他们怎么定价\n2、续费率一般多少')
  await pg.locator('button:has-text("拆开")').click(); await pg.waitForTimeout(600)
  await card.locator('button:has-text("贴回整套结果")').click(); await pg.waitForTimeout(350)
  await pg.locator('.sheet textarea').first().fill(answer)
  await pg.waitForTimeout(150)
  await pg.locator('button:has-text("按题号分到各条")').click(); await pg.waitForTimeout(600)
  const got = await pg.evaluate(() => JSON.parse(localStorage.getItem('deskside.v1')).inquiries
    .filter(q => q.engagementId==='e2').map(q => (q.findings||'').replace(/\n/g,' ').slice(0,20)))
  const kept = await pg.locator('.sheet textarea').first().inputValue().catch(() => '')
  const untouched = got.every(g => !g)
  t(`不乱塞：${label}`, untouched, JSON.stringify(got))
  t(`  └ 原文还在框里`, !!kept, kept ? `${kept.length} 字` : '⚠️ 丢了')
}
await b.close()
process.exit(fail ? 1 : 0)
