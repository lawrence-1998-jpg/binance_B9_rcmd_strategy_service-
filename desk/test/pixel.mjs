import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
const URL='http://127.0.0.1:8765/index.html'
const today=new Date().toISOString().slice(0,10)
const b=await chromium.launch()
for (const scheme of ['light','dark']) {
  const ctx=await b.newContext({viewport:{width:430,height:932},colorScheme:scheme})
  await ctx.route('**fonts.g**', r=>r.abort())
  const pg=await ctx.newPage()
  await pg.goto(URL)
  await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
  await pg.goto(URL+'#/today'); await pg.reload(); await pg.waitForTimeout(600)
  const r = await pg.evaluate(()=>{
    const g=(sel,prop='color')=>{const e=document.querySelector(sel); return e?getComputedStyle(e)[prop]:null}
    return {
      'body bg': g('body','backgroundColor'),
      '.focus bg': g('.focus','backgroundColor'),
      '.focus color': g('.focus'),
      '.focus-v color': g('.focus-v'),
      '.focus-k color': g('.focus-k'),
      '.focus-k opacity': g('.focus-k','opacity'),
      '.big color': g('.big'),
      '.card bg': g('.card','backgroundColor'),
      '--ground': getComputedStyle(document.documentElement).getPropertyValue('--ground').trim(),
      '--night': getComputedStyle(document.documentElement).getPropertyValue('--night').trim(),
    }
  })
  console.log(`\n=== ${scheme} ===`)
  for (const [k,v] of Object.entries(r)) console.log(` ${k.padEnd(18)} ${v}`)
  await ctx.close()
}
await b.close()
