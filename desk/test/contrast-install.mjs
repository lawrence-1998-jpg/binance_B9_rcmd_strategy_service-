import pkg from 'playwright'
const { chromium, devices } = pkg
const URL=process.env.DESK_URL ?? 'http://127.0.0.1:8765/index.html'
const b=await chromium.launch()
for (const scheme of ['light','dark']) {
  const ctx=await b.newContext({...devices['iPhone 13 Pro Max'], colorScheme:scheme})
  await ctx.route(/fonts\.(googleapis|gstatic)\.com/, r=>r.abort())
  const pg=await ctx.newPage()
  await pg.goto(URL); await pg.waitForTimeout(700)
  const r=await pg.evaluate(()=>{
    const lum=(c)=>{const f=(x)=>{x/=255;return x<=0.03928?x/12.92:Math.pow((x+0.055)/1.055,2.4)};return .2126*f(c[0])+.7152*f(c[1])+.0722*f(c[2])}
    const ratio=(a,bg)=>{const la=lum(a),lb=lum(bg),hi=Math.max(la,lb),lo=Math.min(la,lb);return (hi+.05)/(lo+.05)}
    const parse=(s)=>{const m=s.match(/rgba?\(([^)]+)\)/);if(!m)return null;const p=m[1].split(',').map(Number);return {rgb:[p[0],p[1],p[2]],a:p.length>3?p[3]:1}}
    const box=document.querySelector('.install'); if(!box) return null
    const bg=parse(getComputedStyle(box).backgroundColor).rgb
    const out=[]
    for (const sel of ['.install-t','.install-s','.install button']) {
      const el=box.querySelector(sel); if(!el) continue
      const cs=getComputedStyle(el)
      const fgp=parse(cs.color)
      let op=1,e=el; while(e&&e!==document.body){op*=parseFloat(getComputedStyle(e).opacity||'1');e=e.parentElement}
      const eff=fgp.a*op
      const ownBg = parse(cs.backgroundColor)
      const useBg = ownBg && ownBg.a>0.9 ? ownBg.rgb : bg
      const fg = eff<1 ? fgp.rgb.map((c,i)=>c*eff+useBg[i]*(1-eff)) : fgp.rgb
      const r=el.getBoundingClientRect()
      out.push({sel, size:+parseFloat(cs.fontSize).toFixed(1), weight:cs.fontWeight,
                ratio:+ratio(fg,useBg).toFixed(2), h:Math.round(r.height)})
    }
    return {bg:bg.join(','), out}
  })
  console.log(`[${scheme}] 底色 rgb(${r.bg})`)
  for (const x of r.out) {
    const large = x.size>=24 || (x.size>=18.66 && Number(x.weight)>=700)
    const need = large?3:4.5
    console.log(`  ${x.ratio>=need?'✓':'✗'} ${x.sel.padEnd(18)} ${x.size}px w${x.weight} → ${x.ratio}:1 (需 ${need}) 高 ${x.h}px`)
  }
  await ctx.close()
}
await b.close()
