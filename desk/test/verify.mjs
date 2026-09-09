import pkg from 'playwright'
const { chromium } = pkg
import { readFileSync } from 'node:fs'
import { makeState } from './seed.mjs'
const URL='http://127.0.0.1:8765/index.html'
const OUT=new globalThis.URL('./shots', import.meta.url).pathname
const today=new Date().toISOString().slice(0,10)
const b=await chromium.launch()
const pass=[], fail=[]
const t=(name,ok,note='')=>{ (ok?pass:fail).push(name+(note?` — ${note}`:'')); console.log(`${ok?'✓':'✗'} ${name}${note?' — '+note:''}`) }

async function fresh(dark=false){
  const ctx=await b.newContext({viewport:{width:430,height:932},deviceScaleFactor:2,colorScheme:dark?'dark':'light',acceptDownloads:true})
  await ctx.route('**fonts.g**', r=>r.abort())
  const pg=await ctx.newPage()
  pg.on('pageerror',e=>fail.push('PAGEERROR: '+e.message))
  await pg.goto(URL)
  await pg.evaluate(s=>localStorage.setItem('deskside.v1',JSON.stringify(s)), makeState(today))
  return {ctx,pg}
}

// ---- 1. 删除确认真的挡住了 ----
{
  const {ctx,pg}=await fresh()
  await pg.goto(URL+'#/life'); await pg.reload(); await pg.waitForTimeout(400)
  const before=await pg.evaluate(()=>JSON.parse(localStorage.getItem('deskside.v1')).anniversaries.length)
  await pg.locator('.tap-del').first().click(); await pg.waitForTimeout(300)
  const dialogUp=await pg.evaluate(()=>!!document.querySelector('.dialog'))
  const afterOpen=await pg.evaluate(()=>JSON.parse(localStorage.getItem('deskside.v1')).anniversaries.length)
  t('纪念日删除：先弹确认框', dialogUp)
  t('纪念日删除：确认前没动数据', before===afterOpen, `${before}→${afterOpen}`)
  await pg.screenshot({path:OUT+'/v-confirm.png'})
  // 点「算了」
  await pg.locator('.dialog .btn.quiet').click(); await pg.waitForTimeout(250)
  const afterCancel=await pg.evaluate(()=>JSON.parse(localStorage.getItem('deskside.v1')).anniversaries.length)
  t('纪念日删除：点「算了」不删', before===afterCancel, `${before}→${afterCancel}`)
  // 再来一次，点确认
  await pg.locator('.tap-del').first().click(); await pg.waitForTimeout(250)
  await pg.locator('.dialog .btn.danger').click(); await pg.waitForTimeout(300)
  const afterYes=await pg.evaluate(()=>JSON.parse(localStorage.getItem('deskside.v1')).anniversaries.length)
  t('纪念日删除：点确认才真删', afterYes===before-1, `${before}→${afterYes}`)
  await ctx.close()
}

// ---- 2. sheet 手势返回 ----
{
  const {ctx,pg}=await fresh()
  await pg.goto(URL+'#/today'); await pg.reload(); await pg.waitForTimeout(400)
  await pg.locator('.cap').click(); await pg.waitForTimeout(350)
  const opened=await pg.evaluate(()=>({sheet:!!document.querySelector('.sheet'), hash:location.hash}))
  t('速记 sheet 打开并写进 hash', opened.sheet && opened.hash.includes('sheet='), opened.hash)
  await pg.goBack(); await pg.waitForTimeout(400)
  const back=await pg.evaluate(()=>({sheet:!!document.querySelector('.sheet'), hash:location.hash}))
  t('手势返回：关掉 sheet 且留在今日', !back.sheet && back.hash==='#/today', `sheet=${back.sheet} hash=${back.hash}`)
  const oversc=await pg.evaluate(()=>{
    const el=document.createElement('div'); el.className='sheet'; document.body.appendChild(el)
    const v=getComputedStyle(el).overscrollBehavior; el.remove(); return v })
  t('sheet 有 overscroll contain', oversc.includes('contain'), oversc)
  await ctx.close()
}

// ---- 3. 备份真的带上照片 ----
{
  const {ctx,pg}=await fresh()
  await pg.goto(URL); await pg.waitForTimeout(400)
  // 造两张图塞进 IndexedDB + 元数据
  const made=await pg.evaluate(async ()=>{
    async function mk(color){
      const c=document.createElement('canvas'); c.width=c.height=64
      const x=c.getContext('2d'); x.fillStyle=color; x.fillRect(0,0,64,64)
      return await new Promise(r=>c.toBlob(r,'image/jpeg',0.9))
    }
    const db=await new Promise((res,rej)=>{const q=indexedDB.open('deskside-media',1)
      q.onupgradeneeded=()=>{if(!q.result.objectStoreNames.contains('photos'))q.result.createObjectStore('photos')}
      q.onsuccess=()=>res(q.result); q.onerror=()=>rej(q.error)})
    for (const [id,c] of [['p1','#c67139'],['p2','#7a8a5e']]) {
      const blob=await mk(c)
      await new Promise((res,rej)=>{const t=db.transaction('photos','readwrite')
        const r=t.objectStore('photos').put(blob,id); r.onsuccess=()=>res(); r.onerror=()=>rej()})
    }
    const st=JSON.parse(localStorage.getItem('deskside.v1'))
    st.photos=[{id:'p1',caption:'第一张',date:'2026-08-30',createdAt:Date.now()},
               {id:'p2',caption:'第二张',date:'2026-08-31',createdAt:Date.now()}]
    localStorage.setItem('deskside.v1',JSON.stringify(st))
    return 2
  })
  await pg.reload(); await pg.waitForTimeout(500)
  // 直接调 buildBackup（页面里没导出模块，改用点导出后读 manual textarea）
  await pg.goto(URL+'#/review'); await pg.reload(); await pg.waitForTimeout(400)
  await pg.locator('button[aria-label=设置]').click(); await pg.waitForTimeout(400)
  // 真的把下载接下来读。
  // 以前这里只会去找 sheet 里那个 readonly textarea —— 那是个降级路径，
  // 正常情况下导出走的是 blob 下载，于是这条断言常年是红的，
  // 而「她的照片到底有没有进备份」这个真问题一次都没被回答过：
  // 照片本体在 IndexedDB 里，不在 localStorage 里，只序列化 state 是带不走的。
  const waitDl = pg.waitForEvent('download', { timeout: 8000 }).catch(() => null)
  await pg.locator('button:has-text("导出备份")').click()
  const download = await waitDl
  let dl = null
  if (download) {
    const path = await download.path()
    if (path) dl = readFileSync(path, 'utf8')
  }
  if (!dl) {
    await pg.waitForTimeout(1200)
    dl = await pg.evaluate(()=>{
      const ta=document.querySelector('.sheet textarea[readonly]')
      return ta ? ta.value : null
    })
  }
  if (!dl) { t('导出备份包含照片', false, '既没接到下载，也没有降级的文本框') }
  else {
    let j=null; try{ j=JSON.parse(dl) }catch{}
    const pd=j && j.photoData
    const n=pd?Object.keys(pd).length:0
    const isDataURL=pd && Object.values(pd).every(v=>String(v).startsWith('data:image'))
    t('导出备份包含照片本体', n===made && isDataURL, `photoData 里 ${n} 张，data URL=${isDataURL}，${Math.round(dl.length/1024)}KB`)
  }
  await pg.screenshot({path:OUT+'/v-settings.png',fullPage:true})
  await ctx.close()
}

// ---- 4. 深色模式 ----
{
  const {ctx,pg}=await fresh(true)
  for (const [h,name] of [['#/today','today'],['#/life','life'],['#/review','review']]) {
    await pg.goto(URL+h); await pg.reload(); await pg.waitForTimeout(450)
    await pg.screenshot({path:`${OUT}/v-dark-${name}.png`,fullPage:true})
  }
  const c=await pg.evaluate(()=>({
    body:getComputedStyle(document.body).backgroundColor,
    card:document.querySelector('.card')?getComputedStyle(document.querySelector('.card')).backgroundColor:null,
    ink:getComputedStyle(document.body).color,
  }))
  const dark=c.body.match(/\d+/g).slice(0,3).map(Number).reduce((a,b)=>a+b,0) < 200
  t('深色模式：底色确实变暗', dark, JSON.stringify(c))
  await ctx.close()
}

// ---- 5. 写盘失败会告诉用户 ----
{
  const {ctx,pg}=await fresh()
  await pg.goto(URL+'#/today'); await pg.reload(); await pg.waitForTimeout(400)
  await pg.evaluate(()=>{
    // 模拟配额写满
    const orig=Storage.prototype.setItem
    Storage.prototype.setItem=function(){ throw new DOMException('QuotaExceededError','QuotaExceededError') }
    window.__restore=()=>{Storage.prototype.setItem=orig}
  })
  // 触发一次写：勾一个任务
  await pg.locator('.check').first().click(); await pg.waitForTimeout(400)
  const warn=await pg.evaluate(()=>{const w=document.querySelector('.storage-warn'); return w?w.textContent.trim().slice(0,40):null})
  t('localStorage 写不进去时有警告条', !!warn, warn||'没有出现')
  await pg.screenshot({path:OUT+'/v-storagewarn.png'})
  await ctx.close()
}

console.log(`\n通过 ${pass.length} / 失败 ${fail.length}`)
if (fail.length) { console.log('失败项:'); fail.forEach(f=>console.log('  - '+f)) }
await b.close()
process.exit(fail.length?1:0)
