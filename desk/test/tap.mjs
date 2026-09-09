import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
const URL='http://127.0.0.1:8765/index.html'
const today=new Date().toISOString().slice(0,10)
const b=await chromium.launch()
const ctx=await b.newContext({viewport:{width:430,height:932}})
await ctx.route('**fonts.g**', r=>r.abort())
const pg=await ctx.newPage()
await pg.goto(URL)
await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
await pg.goto(URL+'#/today'); await pg.reload(); await pg.waitForTimeout(500)
const r = await pg.evaluate(()=>{
  const out=[]
  document.querySelectorAll('label.check, .more, .tap-del, .chip.tap, .icon-btn, .btn, .tab, .cap, .padd').forEach(el=>{
    const b=el.getBoundingClientRect()
    if (b.width<1) return
    out.push({cls:(typeof el.className==='string'?el.className:el.tagName).slice(0,22), w:Math.round(b.width), h:Math.round(b.height)})
  })
  return out
})
const small = r.filter(x=>x.w<44||x.h<44)
console.log(`可点元素 ${r.length} 个，其中小于 44pt 的 ${small.length} 个`)
small.forEach(x=>console.log(`  ✗ ${x.cls} ${x.w}×${x.h}`))
console.log('样本:')
;[...new Map(r.map(x=>[x.cls,x])).values()].slice(0,10).forEach(x=>console.log(`  ${x.cls.padEnd(24)} ${x.w}×${x.h}`))

// 整行点击是否仍然能完成勾选
const before = await pg.evaluate(()=>JSON.parse(localStorage.getItem('deskside.v1')).tasks.filter(t=>t.done).length)
await pg.locator('label.check').first().click({position:{x:300,y:20}})   // 点行的右半边，不是复选框
await pg.waitForTimeout(300)
const after = await pg.evaluate(()=>JSON.parse(localStorage.getItem('deskside.v1')).tasks.filter(t=>t.done).length)
console.log(`\n整行右半边点击 → 完成数 ${before} → ${after}  ${after!==before?'✓ 整行可勾':'✗ 整行点了没反应'}`)
await b.close()
