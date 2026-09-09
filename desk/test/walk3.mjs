import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
import fs from 'node:fs'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const URL=process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today=new Date().toISOString().slice(0,10)
const log=[]
const say=(s)=>{ log.push(s); fs.writeFileSync(`${OUT}/walk3.txt`, log.join('\n')) }

const b=await chromium.launch()
const ctx=await b.newContext({viewport:{width:430,height:932}})
await ctx.route('**fonts.g**', r=>r.abort())
await ctx.addInitScript(()=>{const st=document.createElement('style');st.textContent='*,*::before,*::after{animation:none!important;transition:none!important}';document.addEventListener('DOMContentLoaded',()=>document.head.appendChild(st))})
const pg=await ctx.newPage()
const errs=[]
pg.on('pageerror',e=>errs.push('PAGEERROR: '+e.message))
pg.on('console',m=>{ if(m.type()==='error' && !/ERR_(FAILED|CONNECTION|BLOCKED)/.test(m.text())) errs.push('console.error: '+m.text().slice(0,120)) })

await pg.goto(URL)
await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))

let clicked=0, dead=[], unclickable=[]
for (const [hash,name] of [['#/life','生活'],['#/review','复盘']]) {
  await pg.goto(URL+hash); await pg.reload(); await pg.waitForTimeout(300)
  // .sr 是刻意视觉隐藏的读屏按钮，点不到是对的
  const SEL = 'main button:visible:not(.sr)'
  const n = await pg.locator(SEL).count()
  say(`\n=== ${name}：${n} 个按钮 ===`)
  for (let i=0;i<n;i++){
    // 每个按钮点完就重置回同一状态，但只重载一次页面（不重灌数据）
    const all = await pg.locator(SEL).all()
    if (i>=all.length) break
    const el = all[i]
    const label = ((await el.getAttribute('aria-label'))||(await el.innerText().catch(()=>''))||'?').trim().replace(/\s+/g,' ').slice(0,20)
    const b4 = await pg.evaluate(()=>({s:localStorage.getItem('deskside.v1'), d:document.body.innerText.length, dlg:!!document.querySelector('.dialog'), sh:!!document.querySelector('.sheet')}))
    let err=null
    try { await el.click({timeout:2000}) } catch(e){ err=String(e.message).split('\n')[0].slice(0,50) }
    await pg.waitForTimeout(150)
    const af = await pg.evaluate(()=>({s:localStorage.getItem('deskside.v1'), d:document.body.innerText.length, dlg:!!document.querySelector('.dialog'), sh:!!document.querySelector('.sheet')}))
    clicked++
    const moved = b4.s!==af.s || b4.d!==af.d || af.dlg!==b4.dlg || af.sh!==b4.sh
    if (err) unclickable.push(`${name} [${i}] ${label} — ${err}`)
    else if (!moved) dead.push(`${name} [${i}] ${label}`)
    say(`  ${err?'✗':moved?'✓':'·'} [${i}] ${label}${af.dlg?' 弹确认':''}${af.sh?' 开sheet':''}`)
    // 收拾现场
    if (af.dlg) { await pg.locator('.dialog .btn.quiet').click().catch(()=>{}); await pg.waitForTimeout(120) }
    if (af.sh) { await pg.goBack().catch(()=>{}); await pg.waitForTimeout(200) }
    await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
    await pg.goto(URL+hash); await pg.reload(); await pg.waitForTimeout(200)
  }
}
say(`\n点了 ${clicked} 个按钮`)
say(`没反应的 ${dead.length} 个:`); dead.forEach(d=>say('  '+d))
say(`点不到的 ${unclickable.length} 个:`); unclickable.forEach(d=>say('  '+d))
say(`页面错误: ${errs.length? errs.slice(0,8).join(' | ') : '无'}`)
await b.close()
