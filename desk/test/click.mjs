import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
const URL='http://127.0.0.1:8765/index.html'
const today=new Date().toISOString().slice(0,10)
const b=await chromium.launch()
const ctx=await b.newContext({viewport:{width:430,height:932}})
await ctx.addInitScript(()=>{const st=document.createElement('style');st.textContent='*,*::before,*::after{animation:none!important;transition:none!important}';document.addEventListener('DOMContentLoaded',()=>document.head.appendChild(st))})
await ctx.route('**fonts.googleapis.com**', r=>r.abort())
await ctx.route('**fonts.gstatic.com**', r=>r.abort())
const pg=await ctx.newPage()
const errs=[]
pg.on('pageerror',e=>errs.push('PAGEERROR: '+e.message))

const snap = () => pg.evaluate(()=>localStorage.getItem('deskside.v1')||'')
async function seed(){ await pg.goto(URL); await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today)) }

const results=[]
async function walk(hash, name){
  await seed()
  await pg.goto(URL+hash); await pg.reload(); await pg.waitForTimeout(250)
  const btns = await pg.locator('main button:visible').all()
  console.log(`\n=== ${name} (${btns.length} 个按钮) ===`)
  for (let i=0;i<btns.length;i++){
    // 每次都重新拿一遍（DOM 会变）
    await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
    await pg.reload(); await pg.waitForTimeout(160)
    const all = await pg.locator('main button:visible').all()
    if (i>=all.length) break
    const el = all[i]
    const label = ((await el.getAttribute('aria-label'))||(await el.innerText().catch(()=>''))||'?').trim().replace(/\s+/g,' ').slice(0,22)
    const before = await snap()
    const beforeDom = await pg.evaluate(()=>document.querySelector('main').innerText.length)
    let err=null
    try { await el.click({timeout:2500}) } catch(e){ err='点不到: '+String(e.message).split('\n')[0].slice(0,60) }
    await pg.waitForTimeout(200)
    const after = await snap()
    const afterDom = await pg.evaluate(()=>document.querySelector('main')?document.querySelector('main').innerText.length:-1)
    const sheet = await pg.evaluate(()=>!!document.querySelector('.sheet'))
    const changed = before!==after
    const domChanged = beforeDom!==afterDom
    results.push({screen:name,i,label,changed,domChanged,sheet,err})
    const mark = err ? '✗' : (changed||domChanged||sheet) ? '✓' : '·'
    console.log(`  ${mark} [${i}] ${label.padEnd(22)} 存储${changed?'变':'不变'} DOM${domChanged?'变':'不变'}${sheet?' 开sheet':''}${err?' '+err:''}`)
  }
}
await walk('#/today','今日')
await walk('#/work','工作')
await walk('#/life','生活')
await walk('#/review','复盘')
console.log('\n=== 无反应的按钮（存储、DOM 都没变、也没开 sheet）===')
const dead = results.filter(r=>!r.err && !r.changed && !r.domChanged && !r.sheet)
dead.forEach(r=>console.log(`  ${r.screen} [${r.i}] ${r.label}`))
console.log('\n=== 点不到的 ===')
results.filter(r=>r.err).forEach(r=>console.log(`  ${r.screen} [${r.i}] ${r.label} — ${r.err}`))
console.log('\n页面错误:', errs.length?errs:'none')
await b.close()
