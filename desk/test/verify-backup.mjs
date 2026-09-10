// 备份 → 换台设备 → 恢复。这条路是这个 App 唯一的数据保险。
//
// 没有后端，设置页明写着「换设备、清缓存都会没，所以每周导出一次」。
// 她照做。所以这条路一旦悄悄丢东西，是不可逆的。
//
// ## 这套以前几乎什么都没验
//
// 它算出并打印了一大堆事实（日记几天、纪念日几个、弹没弹覆盖确认、
// 是不是 data URL、照片墙渲染成什么样），但**一条都没断言** ——
// 只有两行以 ✓ 开头，退出码也只看照片。
//
// 验过：把恢复改成「把 entries 和 anniversaries 全扔掉」，
// 这套照样 `✓2 · 全绿`。**她的日记和纪念日整个消失，测试不吭声。**
//
// 现在的规矩：**导出文件是真相，恢复出来的必须跟它一模一样。**
// 逐个集合比条数是数据驱动的（照着导出文件里的 key 走），
// 以后加了新集合会自动被盖住，不用记得回来改这里。
import pkg from 'playwright'
const { chromium } = pkg
import { makeState } from './seed.mjs'
import fs from 'node:fs'
const OUT = new globalThis.URL('./shots', import.meta.url).pathname
const URL=process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const today=new Date().toISOString().slice(0,10)
let fail = 0
const t = (n, ok, note='') => { console.log(`${ok?'✓':'✗'} ${n}${note?' — '+note:''}`); if(!ok) fail++ }

const b=await chromium.launch()
const ctx=await b.newContext({viewport:{width:430,height:932}, acceptDownloads:true})
await ctx.route('**fonts.g**', r=>r.abort())
const pg=await ctx.newPage()
const errs=[]; pg.on('pageerror',e=>errs.push(e.message))

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

// ---- 导出 ----
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

t('导出文件名带 .json', /\.json$/.test(dl.suggestedFilename()), dl.suggestedFilename())
t('照片的二进制真的进了导出文件', ids.length === n, `${ids.length}/${n} 张`)
t('照片全是 data URL，不是空串或路径',
  ids.length > 0 && ids.every(k=>pd[k].startsWith('data:image/')))
// 备份里必须有真内容，否则下面「导出=恢复」比的是两个空
t('导出文件里有日记', (j.entries?.length ?? 0) > 0, `${j.entries?.length} 天`)
t('导出文件里有纪念日', (j.anniversaries?.length ?? 0) > 0, `${j.anniversaries?.length} 个`)

// ---- 换台"新设备"，导入 ----
const ctx2 = await b.newContext({viewport:{width:430,height:932}})
await ctx2.route('**fonts.g**', r=>r.abort())
const pg2 = await ctx2.newPage()
const errs2=[]; pg2.on('pageerror',e=>errs2.push(e.message))
await pg2.goto(URL)
const emptyBefore = await pg2.evaluate(()=>!!localStorage.getItem('deskside.v1'))
// 这条不是走形式：新设备要是本来就有数据，下面比中的可能是残留，不是导入的结果
t('新设备在导入前是空的（否则这套测的就不是导入）', emptyBefore === false)

await pg2.goto(URL+'#/review'); await pg2.reload(); await pg2.waitForTimeout(500)
await pg2.locator('button[aria-label=设置]').click(); await pg2.waitForTimeout(400)
await pg2.locator('input[type=file]').setInputFiles(path)
await pg2.waitForTimeout(400)
t('导入前先弹覆盖确认（这一步挡着她一键抹掉现有数据）',
  await pg2.evaluate(()=>!!document.querySelector('.warn')))
await pg2.locator('button:has-text("确认导入")').click()
await pg2.waitForTimeout(2500)

const restored = await pg2.evaluate(async ()=>{
  const st = JSON.parse(localStorage.getItem('deskside.v1'))
  const db=await new Promise((res,rej)=>{const q=indexedDB.open('deskside-media',1)
    q.onupgradeneeded=()=>{if(!q.result.objectStoreNames.contains('photos'))q.result.createObjectStore('photos')}
    q.onsuccess=()=>res(q.result);q.onerror=()=>rej(q.error)})
  const sizes={}
  for (const p of st.photos){
    const blob=await new Promise((res)=>{const tx=db.transaction('photos','readonly')
      const r=tx.objectStore('photos').get(p.id); r.onsuccess=()=>res(r.result); r.onerror=()=>res(null)})
    sizes[p.id]= blob ? blob.size : null
  }
  return { state: st, blobSizes: sizes, hasPhotoData: 'photoData' in st }
})

// ---- 主角：导出文件里有什么，恢复之后就得有什么 ----
//
// 照着导出文件里的 key 走，不写死清单 —— 以后加了新集合自动被盖住。
const collections = Object.keys(j).filter((k) => k !== 'photoData' && Array.isArray(j[k]))
t('导出文件里的集合数量对得上（不是只剩一两个）', collections.length >= 8, collections.join(','))
for (const k of collections) {
  t(`「${k}」恢复后条数跟导出文件一致`,
    (restored.state[k]?.length ?? -1) === j[k].length,
    `导出 ${j[k].length} → 恢复 ${restored.state[k]?.length ?? '没有这个字段'}`)
}

// 条数对得上、内容变了也是丢数据，所以逐个 key 再深比一次。
// 逐个比而不是整体比一次：整体只会告诉你「不一样」，逐个能指出是哪一项。
const SKIP = new Set([
  'photoData',   // 照片二进制单独验，不塞进 state
  'version',     // merge 强制写成 1
  'exportedAt',  // 导出时间戳，恢复后没有意义
])
const diffs = []
for (const k of Object.keys(j)) {
  if (SKIP.has(k)) continue
  if (JSON.stringify(restored.state[k]) !== JSON.stringify(j[k])) diffs.push(k)
}
t('每一项内容都跟导出文件一致（不只是条数对）', diffs.length === 0, `对不上的：${diffs.join(', ')}`)

// ---- 照片 ----
t(`照片在新设备上全部还原（有真实字节）`,
  restored.state.photos.length === n && Object.values(restored.blobSizes).every(v=>v && v>0),
  `${Object.values(restored.blobSizes).filter(Boolean).length}/${n} 张`)
t('photoData 没被塞进 localStorage（塞进去会直接撑爆 5MB）', !restored.hasPhotoData)

// 字节在、但渲染成破图也不算还原
await pg2.goto(URL+'#/life'); await pg2.reload(); await pg2.waitForTimeout(1200)
const shown = await pg2.evaluate(()=>[...document.querySelectorAll('.ptile img')]
  .map(i=>({w:i.naturalWidth, h:i.naturalHeight})))
t('照片墙上真的渲染出了图，不是破图',
  shown.length === n && shown.every(s=>s.w>0 && s.h>0), JSON.stringify(shown))
await pg2.screenshot({path:`${OUT}/v-restored.png`,fullPage:true})

t('导出这一侧没有 JS 报错', errs.length===0, errs.join(' | '))
t('导入这一侧没有 JS 报错', errs2.length===0, errs2.join(' | '))

await b.close()
console.log(fail ? `\n${fail} 条没过` : '\n全过')
process.exit(fail ? 1 : 0)
