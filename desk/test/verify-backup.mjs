import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
import fs from 'node:fs'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const URL='http://127.0.0.1:8765/index.html'
const today=new Date().toISOString().slice(0,10)
const b=await chromium.launch()
const ctx=await b.newContext({viewport:{width:430,height:932}, acceptDownloads:true})
await ctx.route('**fonts.g**', r=>r.abort())
const pg=await ctx.newPage()
pg.on('pageerror',e=>console.log('PAGEERROR:',e.message))

await pg.goto(URL)
await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))

// 造 3 张真图进 IndexedDB
const n = await pg.evaluate(async ()=>{
  const mk=async(color,w,h)=>{const c=document.createElement('canvas');c.width=w;c.height=h
    const x=c.getContext('2d');x.fillStyle=color;x.fillRect(0,0,w,h)
    x.fillStyle='#fff';x.font='40px sans-serif';x.fillText(color.slice(1,4),10,60)
    return await new Promise(r=>c.toBlob(r,'image/jpeg',0.85))}
  const db=await new Promise((res,rej)=>{const q=indexedDB.open('deskside-media',1)
    q.onupgradeneeded=()=>{if(!q.result.objectStoreNames.contains('photos'))q.result.createObjectStore('photos')}
    q.onsuccess=()=>res(q.result);q.onerror=()=>rej(q.error)})
  const specs=[['p1','#c67139',400,300],['p2','#7a8a5e',300,400],['p3','#a8697c',500,500]]
  for (const [id,c,w,h] of specs){
    const blob=await mk(c,w,h)
    await new Promise((res,rej)=>{const t=db.transaction('photos','readwrite')
      const r=t.objectStore('photos').put(blob,id);r.onsuccess=()=>res();r.onerror=()=>rej()})
  }
  const st=JSON.parse(localStorage.getItem('deskside.v1'))
  st.photos=specs.map(([id],i)=>({id,caption:`第${i+1}张`,date:`2026-08-3${i}`,createdAt:Date.now()}))
  localStorage.setItem('deskside.v1',JSON.stringify(st))
  return specs.length
})
console.log(`造了 ${n} 张照片`)

await pg.goto(URL+'#/review'); await pg.reload(); await pg.waitForTimeout(500)
await pg.locator('button[aria-label=设置]').click(); await pg.waitForTimeout(400)

const [dl] = await Promise.all([
  pg.waitForEvent('download', {timeout:15000}),
  pg.locator('button:has-text("导出备份")').click(),
])
const path = `${OUT}/backup.json`
await dl.saveAs(path)
const raw = fs.readFileSync(path,'utf8')
const j = JSON.parse(raw)
const pd = j.photoData || {}
const ids = Object.keys(pd)
console.log(`文件名: ${dl.suggestedFilename()}`)
console.log(`大小: ${Math.round(raw.length/1024)}KB`)
console.log(`photoData 里的照片: ${ids.length} 张 [${ids.join(', ')}]`)
console.log(`都是 data URL: ${ids.every(k=>pd[k].startsWith('data:image/'))}`)
console.log(`元数据 photos: ${j.photos.length} 条`)
console.log(`日记 entries: ${j.entries.length} 天，纪念日: ${j.anniversaries.length} 个`)

// ---- 关键一步：换个"新设备"，导入这个文件，看照片回不回来 ----
const ctx2 = await b.newContext({viewport:{width:430,height:932}})
await ctx2.route('**fonts.g**', r=>r.abort())
const pg2 = await ctx2.newPage()
pg2.on('pageerror',e=>console.log('PAGEERROR2:',e.message))
await pg2.goto(URL)
const emptyBefore = await pg2.evaluate(()=>({ls: !!localStorage.getItem('deskside.v1')}))
console.log(`\n新设备初始状态: localStorage 有数据=${emptyBefore.ls}`)

await pg2.goto(URL+'#/review'); await pg2.reload(); await pg2.waitForTimeout(500)
await pg2.locator('button[aria-label=设置]').click(); await pg2.waitForTimeout(400)
await pg2.locator('input[type=file]').setInputFiles(path)
await pg2.waitForTimeout(400)
const confirmShown = await pg2.evaluate(()=>!!document.querySelector('.warn'))
console.log(`导入前弹了覆盖确认: ${confirmShown}`)
await pg2.locator('button:has-text("确认导入")').click()
await pg2.waitForTimeout(2500)

const restored = await pg2.evaluate(async ()=>{
  const st = JSON.parse(localStorage.getItem('deskside.v1'))
  const db=await new Promise((res,rej)=>{const q=indexedDB.open('deskside-media',1)
    q.onupgradeneeded=()=>{if(!q.result.objectStoreNames.contains('photos'))q.result.createObjectStore('photos')}
    q.onsuccess=()=>res(q.result);q.onerror=()=>rej(q.error)})
  const sizes={}
  for (const p of st.photos){
    const blob=await new Promise((res)=>{const t=db.transaction('photos','readonly')
      const r=t.objectStore('photos').get(p.id); r.onsuccess=()=>res(r.result); r.onerror=()=>res(null)})
    sizes[p.id]= blob ? blob.size : null
  }
  return { photos: st.photos.length, entries: st.entries.length, anniv: st.anniversaries.length,
           blobSizes: sizes, hasPhotoData: 'photoData' in st }
})
console.log('还原后:', JSON.stringify(restored))
const allBack = restored.photos===n && Object.values(restored.blobSizes).every(v=>v && v>0)
console.log(`\n${allBack ? '✓' : '✗'} 照片在新设备上全部还原（${Object.values(restored.blobSizes).filter(Boolean).length}/${n} 张有真实字节）`)
console.log(`${!restored.hasPhotoData ? '✓' : '✗'} photoData 没被塞进 localStorage（塞进去会直接撑爆 5MB）`)

// 视觉确认照片真的能显示
await pg2.goto(URL+'#/life'); await pg2.reload(); await pg2.waitForTimeout(1200)
const shown = await pg2.evaluate(()=>{
  const imgs=[...document.querySelectorAll('.ptile img')]
  return imgs.map(i=>({src:i.src.slice(0,12), w:i.naturalWidth, h:i.naturalHeight}))
})
console.log('照片墙实际渲染:', JSON.stringify(shown))
await pg2.screenshot({path:`${OUT}/v-restored.png`,fullPage:true})
await b.close()
process.exit(allBack && !restored.hasPhotoData ? 0 : 1)
