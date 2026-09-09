import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
const URL='http://127.0.0.1:8765/index.html'
const today=new Date().toISOString().slice(0,10)
const b=await chromium.launch()
for (const scheme of ['light','dark']) {
  const ctx=await b.newContext({viewport:{width:430,height:932},deviceScaleFactor:2,colorScheme:scheme})
  await ctx.route('**fonts.g**', r=>r.abort())
  const pg=await ctx.newPage()
  await pg.goto(URL)
  await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
  await pg.goto(URL+'#/life'); await pg.reload(); await pg.waitForTimeout(500)
  await pg.locator('.tap-del').first().click()
  await pg.waitForTimeout(1500)   // 让 pop 动画彻底跑完
  const box = await pg.locator('.dialog').boundingBox()
  await pg.screenshot({path:`${new globalThis.URL('./shots', import.meta.url).pathname}/dlg-${scheme}.png`, clip:{x:box.x-8,y:box.y-8,width:box.width+16,height:box.height+16}})
  const m = await pg.evaluate(()=>{
    const d=document.querySelector('.dialog')
    const cs=getComputedStyle(d)
    const btns=[...d.querySelectorAll('button')].map(b=>{const r=b.getBoundingClientRect();return `${b.textContent.trim()} ${Math.round(r.width)}×${Math.round(r.height)}`})
    return { transform: cs.transform, opacity: cs.opacity, btns }
  })
  console.log(scheme, JSON.stringify(m))
  await ctx.close()
}
await b.close()
