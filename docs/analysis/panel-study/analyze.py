import json, statistics as st, math, collections
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","PEPEUSDT","LINKUSDT"]
COIN={s:s.replace("USDT","") for s in SYMS}
COL={ "BTC":1,"ETH":2,"SOL":3,"BNB":4,"XRP":5,"DOGE":6,"PEPE":7,"LINK":8 }

# ── 1. 载入 ──
cohort=json.load(open('cohort.json'))
# user -> {coin: usd}, 总额, 币数
users={}
for r in cohort:
    uid=str(r[0]); h={c: float(r[i]) for c,i in COL.items() if float(r[i])>0}
    users[uid]=dict(hold=h, total=float(r[9]), ncoin=int(r[10]))
holders=collections.defaultdict(set)          # coin -> set(uid)
for uid,u in users.items():
    for c in u['hold']: holders[c].add(uid)

shocks={}                                      # (sym,date) -> row
for l in open('../shocks_bj.tsv').read().strip().split('\n')[1:]:
    p=l.split('\t'); shocks[(p[0],p[1])]=dict(ret=float(p[2]),rng=float(p[3]),shock=int(p[4]),vr=float(p[5]))

panel=[]                                       # (date,sym,uid,am_o,pm_o,am_v,pm_v)
for f in ['seg1','seg2','seg3','seg4']:
    for r in json.load(open(f+'.json')):
        panel.append((str(r[0]),r[1],str(r[2]),int(r[3]),int(r[4]),int(r[5]),int(r[6]),int(r[7]),int(r[8])))
DATES=sorted({p[0] for p in panel})
beh=collections.defaultdict(lambda:(0,0,0,0,0,0))  # (date,sym,uid)->counts
for d,s,u,a,b,c,e,x,y in panel: beh[(d,s,u)]=(a,b,c,e,x,y)

R={}   # 结果容器

# ── 2. Treatment 效应：shock 档 × 持有者行动率（user×day 口径）──
def rates(pred):
    """pred(sym,date)->bool，返回 (n, P_view%, P_trade%)（仅统计持有者）"""
    n=v=t=0
    for s in SYMS:
        c=COIN[s]; hs=holders[c]
        for d in DATES:
            if (s,d) not in shocks or not pred(s,d): continue
            for uid in hs:
                n+=1
                a,b,cc,e,x,y=beh.get((d,s,uid),(0,0,0,0,0,0))
                if cc+e>0: v+=1
                if a+b>0: t+=1
    return n, 100*v/n if n else 0, 100*t/n if n else 0
R['shock_effect']=[]
for lvl,name in [(0,'正常日'),(1,'中度异动'),(2,'极端异动')]:
    n,pv,pt=rates(lambda s,d,l=lvl: shocks[(s,d)]['shock']==l)
    R['shock_effect'].append(dict(lvl=lvl,name=name,n=n,p_view=round(pv,3),p_trade=round(pt,3)))

# ── 3. 剂量反应曲线：振幅桶 × 行动率 ──
BUCKETS=[(0,1),(1,2),(2,3),(3,5),(5,10),(10,99)]
R['dose']=[]
for lo,hi in BUCKETS:
    n,pv,pt=rates(lambda s,d,lo=lo,hi=hi: lo<=shocks[(s,d)]['rng']<hi)
    R['dose'].append(dict(b=f"{lo}-{hi if hi<99 else '∞'}%",n=n,p_view=round(pv,3),p_trade=round(pt,3)))

# ── 4. 异质性：特征 × (正常日 vs 极端日) uplift ──
def rates_users(uids_pred, shock_lvls):
    n=v=t=0
    for s in SYMS:
        c=COIN[s]
        hs=[u for u in holders[c] if uids_pred(u,c)]
        for d in DATES:
            if (s,d) not in shocks or shocks[(s,d)]['shock'] not in shock_lvls: continue
            for uid in hs:
                n+=1
                a,b,cc,e,x,y=beh.get((d,s,uid),(0,0,0,0,0,0))
                if cc+e>0: v+=1
                if a+b>0: t+=1
    return n, 100*v/n if n else 0, 100*t/n if n else 0
def seg_row(name,pred):
    n0,v0,t0=rates_users(pred,{0})
    n2,v2,t2=rates_users(pred,{2})
    return dict(seg=name, n_base=n0, view0=round(v0,2), view2=round(v2,2),
                lift_view=round(v2-v0,2), rl_view=round(v2/v0,2) if v0 else None,
                trade0=round(t0,2), trade2=round(t2,2),
                lift_trade=round(t2-t0,2), rl_trade=round(t2/t0,2) if t0 else None)
R['hetero_size']=[seg_row(nm, (lambda lo,hi: lambda u,c: lo<=users[u]['hold'].get(c,0)<hi)(lo,hi))
   for nm,lo,hi in [("$100-1k",100,1000),("$1k-10k",1000,10000),("$10k+",10000,1e18)]]
R['hetero_ncoin']=[seg_row(nm, (lambda a,b: lambda u,c: a<=users[u]['ncoin']<=b)(a,b))
   for nm,a,b in [("持1币",1,1),("持2币",2,2),("持3+币",3,8)]]

# ── 5. 时序错位：0819(pm异动) 的 am/pm 结构 vs 正常日 ──
def ampm(pred):
    n=av=pv_=at=pt=ax=px=0
    for s in SYMS:
        for d in DATES:
            if (s,d) not in shocks or not pred(s,d): continue
            for uid in holders[COIN[s]]:
                n+=1
                a,b,cc,e,x,y=beh.get((d,s,uid),(0,0,0,0,0,0))
                if cc>0: av+=1
                if e>0: pv_+=1
                if a>0: at+=1
                if b>0: pt+=1
                if x>0: ax+=1
                if y>0: px+=1
    z=lambda x:100*x/n if n else 0
    return n,z(av),z(pv_),z(at),z(pt),z(ax),z(px)
n,a1,p1,a2,p2,a3,p3=ampm(lambda s,d: shocks[(s,d)]['shock']==0)
R['timing_normal']=dict(n=n,am_view=round(a1,3),pm_view=round(p1,3),am_trade=round(a2,3),pm_trade=round(p2,3),am_exp=round(a3,3),pm_exp=round(p3,3))
n,a1,p1,a2,p2,a3,p3=ampm(lambda s,d: d=='20260819')
R['timing_0819']=dict(n=n,am_view=round(a1,3),pm_view=round(p1,3),am_trade=round(a2,3),pm_trade=round(p2,3),am_exp=round(a3,3),pm_exp=round(p3,3))

# ── 6. 个体敏感度：每用户 极端日行动率-正常日行动率 ──
per=collections.defaultdict(lambda: [0,0,0,0])   # uid -> [act_days_sh, n_sh, act_days_norm, n_norm]
for s in SYMS:
    c=COIN[s]
    for d in DATES:
        if (s,d) not in shocks: continue
        lvl=shocks[(s,d)]['shock']
        if lvl==1: continue
        for uid in holders[c]:
            a,b,cc,e,x,y=beh.get((d,s,uid),(0,0,0,0,0,0))
            act=1 if (a+b+cc+e)>0 else 0
            if lvl==2: per[uid][0]+=act; per[uid][1]+=1
            else:      per[uid][2]+=act; per[uid][3]+=1
ups=[]
for uid,(as_,ns,an,nn) in per.items():
    if ns>=1 and nn>=10:
        ups.append(dict(uid=uid, up=as_/ns-an/nn, base=an/nn, total=users[uid]['total'], ncoin=users[uid]['ncoin']))
R['indiv_n']=len(ups)
hist=collections.Counter()
for u in ups:
    x=u['up']
    k=("<-10%" if x<-.10 else "-10~0%" if x<0 else "0%" if x==0 else "0~10%" if x<=.10 else
       "10~30%" if x<=.30 else "30~60%" if x<=.60 else ">60%")
    hist[k]+=1
R['indiv_hist']=[(k,hist.get(k,0)) for k in ["<-10%","-10~0%","0%","0~10%","10~30%","30~60%",">60%"]]
sens=[u for u in ups if u['up']>.30]; mild=[u for u in ups if 0<u['up']<=.30]
flat=[u for u in ups if u['up']<=0]
R['seg_share']=dict(sensitive=len(sens), mild=len(mild), flat=len(flat))
def med(xs): return st.median(xs) if xs else 0
R['seg_profile']=dict(
  sensitive=dict(n=len(sens), med_total=round(med([u['total'] for u in sens])), med_base=round(100*med([u['base'] for u in sens]),1), med_ncoin=med([u['ncoin'] for u in sens])),
  flat=dict(n=len(flat), med_total=round(med([u['total'] for u in flat])), med_base=round(100*med([u['base'] for u in flat]),1), med_ncoin=med([u['ncoin'] for u in flat])))

# ── 7. 按币 0819 对比 ──
R['coin_0819']=[]
for s in SYMS:
    c=COIN[s]; hs=holders[c]
    n0=v0=n1=v1=t0=t1=0
    for d in DATES:
        if (s,d) not in shocks: continue
        for uid in hs:
            a,b,cc,e,x,y=beh.get((d,s,uid),(0,0,0,0,0,0))
            if d=='20260819':
                n1+=1; v1+=1 if cc+e>0 else 0; t1+=1 if a+b>0 else 0
            elif shocks[(s,d)]['shock']==0:
                n0+=1; v0+=1 if cc+e>0 else 0; t0+=1 if a+b>0 else 0
    R['coin_0819'].append(dict(coin=c, holders=len(hs), rng=shocks[(s,'20260819')]['rng'],
        view0=round(100*v0/n0,2), view1=round(100*v1/n1,2),
        trade0=round(100*t0/n0,2), trade1=round(100*t1/n1,2)))

json.dump(R, open('results.json','w'), ensure_ascii=False, indent=1)
print("=== Treatment 效应 ===")
for r in R['shock_effect']: print(f"  {r['name']:<6} n={r['n']:>7,}  看={r['p_view']}%  买={r['p_trade']}%")
print("=== 剂量反应 ===")
for r in R['dose']: print(f"  振幅{r['b']:<7} n={r['n']:>7,}  看={r['p_view']}%  买={r['p_trade']}%")
print("=== 时序（正常日 vs 0819）===")
print(f"  正常日: am看{R['timing_normal']['am_view']}% pm看{R['timing_normal']['pm_view']}% | am买{R['timing_normal']['am_trade']}% pm买{R['timing_normal']['pm_trade']}%")
print(f"  0819  : am看{R['timing_0819']['am_view']}% pm看{R['timing_0819']['pm_view']}% | am买{R['timing_0819']['am_trade']}% pm买{R['timing_0819']['pm_trade']}%")
print(f"=== 个体级 n={R['indiv_n']} ===")
print("  uplift直方:", R['indiv_hist'])
print("  分群:", R['seg_share'])
print("  画像:", R['seg_profile'])
