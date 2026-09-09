// 一份"内容够多"的测试数据。空屏看不出版式问题。
export function makeState (todayKey) {
  const t = todayKey
  const d = (n) => { const x = new Date(t); x.setDate(x.getDate() + n); return x.toISOString().slice(0,10) }
  const id = (p,i) => `${p}${i}`
  return {
    version: 1, seeded: false,
    focus: { [t]: '把客户 A 的诊断报告第三章写完，别的都可以往后放' },
    tasks: [
      { id:'t1', title:'客户 A 的诊断报告写完第三章', domain:'consult', est:90, done:false, date:t },
      { id:'t2', title:'推荐位改版需求文档过一遍', domain:'byte', est:45, done:true, date:t },
      { id:'t3', title:'订国庆的往返票', domain:'us', est:20, done:false, date:t },
      { id:'t4', title:'一个特别特别长的任务标题用来测试换行和截断到底会不会把布局撑坏比如这样一直写下去', domain:'me', est:15, done:false, date:d(1) },
      ...Array.from({length:26},(_,i)=>({ id:id('tx',i), title:`历史任务 ${i+1}`, domain:['consult','byte','us','me'][i%4], est:30, done:i%3===0, date:d(-(i%14)-1) })),
    ],
    notes: [
      { id:'n1', text:'想到一个客户访谈的切入问法：先问他们最近一次改版是被什么逼的', kind:'idea', createdAt:Date.now()-7200000, handled:false },
      { id:'n2', text:'他说想要那台咖啡机', kind:'us', createdAt:Date.now()-86400000, handled:false },
      { id:'n3', text:'还没归类的一条', kind:null, createdAt:Date.now()-600000, handled:false },
    ],
    engagements: [
      { id:'e1', name:'会员体系诊断', domain:'consult', client:'客户 A', stage:'访谈完成 · 正在写报告', blocker:'等客户给数据口径', status:'warn', progress:62, next:'交初稿', nextDate:d(4), updatedAt:Date.now()-3600000 },
      { id:'e2', name:'增长策略陪跑', domain:'consult', client:'客户 B', stage:'第 3 次工作坊', blocker:'', status:'ok', progress:45, next:'出工作坊纪要', nextDate:d(1), updatedAt:Date.now()-172800000 },
      { id:'e3', name:'推荐位改版', domain:'byte', client:'增长方向', stage:'需求评审中', blocker:'等设计终稿', status:'bad', progress:40, next:'评审会', nextDate:d(2), updatedAt:Date.now()-5400000 },
      { id:'e4', name:'Q4 OKR 对齐', domain:'byte', client:'团队', stage:'草稿已发', blocker:'', status:'ok', progress:75, next:'和 leader 一对一', nextDate:d(3), updatedAt:Date.now()-86400000 },
    ],
    meetings: [
      { id:'m1', title:'客户 A 周会', date:t, start:'15:00', end:'16:00', domain:'consult', note:'带上诊断中期结论' },
      { id:'m2', title:'需求评审', date:d(2), start:'10:30', end:'11:30', domain:'byte' },
    ],
    anniversaries: [
      { id:'a1', label:'在一起', date:'2019-05-20', recurring:true },
      { id:'a2', label:'结婚', date:'2023-10-01', recurring:true },
    ],
    wishes: [
      { id:'w1', text:'一起去看一次日出', who:'both', done:false, createdAt:Date.now() },
      { id:'w2', text:'学会做他最爱吃的那道菜', who:'me', done:true, createdAt:Date.now() },
    ],
    trip: { title:'国庆', start:'2026-10-01', end:'2026-10-08', budget:12000,
      days:[ {id:'d1',date:'2026-10-01',title:'出发',detail:'早班机'}, {id:'d2',date:'2026-10-02',title:'海边',detail:'看日出'} ],
      todos:[ {id:'td1',text:'订往返机票',kind:'book',owner:'me',done:true}, {id:'td2',text:'订住宿',kind:'book',owner:'both',done:false}, {id:'td3',text:'充电宝、转换头、常备药',kind:'pack',owner:'both',done:false} ] },
    inquiries: [
      // 一条走到底的：有关键词、有数据（含一条没出处的）、有结论
      { id:'q1', engagementId:'e1', question:'高价值会员的续费，到底是被什么驱动的',
        kind:'ai',
        prompt:'你是内容社区增长顾问……（此处是一整套已备好的 prompt）',
        findings:'## 1. 抖音有没有出现过\n2021 年中出现过一轮腰部作者投稿量下滑……\n\n## 还没搞清楚的\n具体的流量分配比例没有公开口径。',
        conclusion:'出现过，抖音的解法是把流量反馈前置到发布后 2 小时内，先给一个确定性的小曝光。',
        keywords:['作者流失','流量反馈','冷启动曝光','腰部作者'],
        facts:[
          { value:'约 15%', what:'2021 年腰部作者季度投稿量环比降幅', source:'抖音创作者生态报告 2021Q3', confidence:'mid' },
          { value:'2 小时', what:'发布后首次流量反馈的时间窗', source:'', confidence:'low' },
          { value:'2021 年 9 月', what:'创作者激励改版上线时间', source:'公开发布会实录', confidence:'high' },
        ],
        createdAt:Date.now()-86400000*3, updatedAt:Date.now()-3600000 },
      // 访谈那条路，走到一半
      { id:'q2', engagementId:'e1', question:'会员权益的边际成本怎么算才不虚',
        kind:'interview',
        prompt:'访谈提纲：\n1. 你们现在怎么定义低频……',
        keywords:['低频召回','会员分层'],
        facts:[],
        createdAt:Date.now()-86400000*2, updatedAt:Date.now()-7200000 },
      // 刚拆出来，什么都没有
      { id:'q3', engagementId:'e1', question:'同类平台的会员定价梯度是怎么设计的',
        kind:'ai', keywords:[], facts:[],
        createdAt:Date.now()-86400000*2, updatedAt:Date.now()-86400000*2 },
      // 被搁置的 —— 收口状态要能显示
      { id:'q4', engagementId:'e1', question:'竞品的会员权益定价带是怎么切的',
        kind:'ai', closed:'parked', keywords:['定价带'], facts:[],
        createdAt:Date.now()-86400000*5, updatedAt:Date.now()-86400000*4 },
      // 另一条线上的，验证按 engagement 过滤
      { id:'q5', engagementId:'e3', question:'推荐位改版前后，曝光分布会怎么变',
        kind:'ai', keywords:[], facts:[],
        createdAt:Date.now()-86400000, updatedAt:Date.now()-86400000 },
    ],
    logs: [],
    promptDraft: { outline:'UGC 投稿用户的流量下滑导致投稿流失，抖音有没有出现过，怎么解决的\n抖音现在做作者流量反馈的流量占比大概有多少', subject:'抖音', context:'我在给一个 UGC 内容社区做投稿量下滑的诊断。', target:'tooled', depth:'deep' },
    photos: [],
    moments: [ {id:'mo1', text:'今天他记得我说过想吃那家的桂花糕', createdAt:Date.now()-3600000} ],
    entries: [
      { date:t, lines:['做完了推荐位改版需求文档过一遍。','力气主要花在字节产品。','明天先做「订国庆的往返票」。'], auto:true, updatedAt:Date.now() },
      { date:d(-1), lines:['做完了三件事。','一整天都在咨询顾问上。','明天还没定。'], auto:false, updatedAt:Date.now()-86400000 },
      { date:'2025-12-31', lines:['去年最后一天。','',''], auto:false, updatedAt:Date.now()-86400000*300 },
      { date:'2024-08-30', lines:['两年前的这天。','',''], auto:false, updatedAt:Date.now()-86400000*700 },
    ],
    myPrompts: [ {id:'mp1', title:'我自己加的一条', body:'这是自定义 prompt 的正文\n第二行', createdAt:Date.now()} ],
    promptUses: { A1: 5, C1: 3 },
  }
}
