/**
 * 她日常真会复制过来的东西。每条带上「应该认成什么」和「应该先推荐什么」。
 *
 * 这份样本同时喂给 unit.mjs（识别对不对）和 flow.mjs（界面上认出来的
 * 是不是同一个结论），所以改识别规则之前先往这里加一条会被改坏的样本。
 */
export const SAMPLES = [
  {
    name: '微信群聊（名字：内容）',
    kind: 'chat', first: 'summary',
    text: `王总：下周三之前能把方案初稿给到吗？
Lily：可以，但数据那块要等财务给口径
王总：财务那边我去催
张三：我这边竞品分析周一能出
Lily：好的，那我周二先出一版框架，周三合稿
王总：行，周三下午碰一下`,
  },
  {
    name: '微信多选复制（名字+时间单独一行）',
    kind: 'chat', first: 'summary',
    text: `陈晨 10:21
明天的客户会改到下午三点了
我 10:22
收到，材料要调整吗
陈晨 10:25
不用，但他们加了一个 CFO 进来，可能会问 ROI
我 10:26
那我补一页投入产出的测算`,
  },
  {
    name: '纯英文 Slack',
    kind: 'chat', first: 'summary',
    text: `Mike: are we still on for the launch next Tuesday?
Priya: yes, but legal hasn't signed off the copy yet
Mike: can you ping them today?
Priya: already did, waiting
Mike: ok let's give them until EOD Thursday`,
  },
  {
    name: '带信头的邮件',
    kind: 'email', first: 'reply',
    text: `发件人: 刘明 <liuming@example.com>
收件人: 我
主题: 关于二期合同的几个问题

你好，

二期合同我们内部过了一遍，有两点想确认：
1. 付款节点能否从 3/3/4 调整为 3/4/3？
2. 验收标准里的「系统稳定运行」需要量化。

麻烦本周内回复，谢谢！

刘明`,
  },
  {
    name: '没有信头的英文邮件',
    kind: 'message', first: 'reply',
    text: `Hi Lawrence,

Thanks for the deck yesterday. The team liked the segmentation work, but we're not convinced about the pricing tiers — the mid tier feels too close to premium. Could you share the underlying willingness-to-pay data before our Friday call?

Best,
Sarah`,
  },
  {
    name: 'Python 报错',
    kind: 'error', first: 'explain',
    text: `Traceback (most recent call last):
  File "/app/run_pipeline.py", line 42, in <module>
    main()
  File "/app/run_pipeline.py", line 37, in main
    rows = fetch(cfg["source"])
KeyError: 'source'`,
  },
  {
    name: '前端报错',
    kind: 'error', first: 'explain',
    text: `Uncaught TypeError: Cannot read properties of undefined (reading 'map')
    at ProductList (ProductList.tsx:23:18)
    at renderWithHooks (react-dom.development.js:16305:18)`,
  },
  {
    name: 'npm 构建失败',
    kind: 'error', first: 'explain',
    text: `npm ERR! code ERESOLVE
npm ERR! ERESOLVE unable to resolve dependency tree
npm ERR! Found: react@18.3.1`,
  },
  {
    name: '一段 SQL',
    kind: 'code', first: 'explain',
    text: `SELECT user_id, COUNT(*) AS orders
FROM orders
WHERE created_at >= '2026-01-01'
GROUP BY user_id
HAVING COUNT(*) > 3
ORDER BY orders DESC;`,
  },
  {
    name: '一段 JS',
    kind: 'code', first: 'explain',
    text: `function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}`,
  },
  {
    name: 'JSON',
    kind: 'code', first: 'explain',
    text: `{"user": {"id": 42, "tier": "gold"}, "orders": [1, 2, 3]}`,
  },
  {
    name: '从表格复制的（制表符）',
    kind: 'table', first: 'points',
    text: `月份\tGMV\t订单数\t客单价
1月\t1200\t300\t4.0
2月\t980\t260\t3.8
3月\t1500\t340\t4.4
4月\t1620\t350\t4.6`,
  },
  {
    name: 'Markdown 表格',
    kind: 'table', first: 'points',
    text: `| 渠道 | 获客成本 | 次留 |
|---|---|---|
| 抖音 | 32 | 41% |
| 小红书 | 45 | 52% |
| 搜索 | 28 | 38% |`,
  },
  {
    name: '会议纪要',
    kind: 'notes', first: 'todo',
    text: `会员体系诊断 周会纪要
参会：王总、Lily、张三、我

1. 数据口径：以财务月报为准，Lily 负责对齐
2. 竞品分析：张三周一交初稿
3. 方案框架：我周二出，周三合稿
4. 待定：是否把积分体系纳入本期范围`,
  },
  {
    name: '调研提纲（一串问题）',
    kind: 'questions', first: 'research',
    text: `1. 国内头部电商的会员体系，付费会员渗透率大概是多少？
2. 付费会员对复购的提升有多少，有没有公开的数据？
3. 积分体系和付费会员同时存在时，用户会不会混淆？
4. 有哪些失败案例？`,
  },
  {
    name: '一个问题',
    kind: 'ask', first: 'answer',
    text: '怎么在 Excel 里按两列同时去重？',
  },
  {
    name: '英文问题',
    kind: 'ask', first: 'answer',
    text: 'What is the difference between retention and engagement metrics?',
  },
  {
    name: '一个链接',
    kind: 'url', first: 'summary',
    text: 'https://www.example.com/reports/2026-ai-adoption',
  },
  {
    name: '待办清单',
    kind: 'list', first: 'todo',
    text: `- 周一前把竞品表发给王总
- 跟财务确认 GMV 口径
- 下周约 CFO 过一遍 ROI
- 更新项目周报`,
  },
  {
    name: '要点清单（不是待办）',
    kind: 'list', first: 'points',
    text: `· 用户对价格不敏感，对配送时效很敏感
· 复购主要来自 30 岁以上女性
· 新客首单转化率明显低于行业
· 退货率集中在服装类目`,
  },
  {
    name: '中文长文',
    kind: 'article', first: 'summary',
    text: ('过去一年，生成式 AI 在企业里的落地速度远超预期。但真正跑出规模化价值的场景仍然集中在客服、营销内容生产和代码辅助三类。' +
      '原因并不复杂：这三类场景有清晰的输入输出、可以量化的效率指标，以及出了错也能被人工兜底的流程。' +
      '相比之下，需要跨系统取数、跨部门协作的决策类场景，推进要慢得多。').repeat(3),
  },
  {
    name: '英文长文',
    kind: 'article', first: 'summary',
    text: ('Retail media networks have become the fastest growing slice of digital advertising. ' +
      'Retailers own first-party purchase data, which lets brands target shoppers at the moment of intent and measure closed-loop sales. ' +
      'But the market is fragmented, measurement standards differ between networks, and many brands struggle to compare returns. ').repeat(4),
  },
  {
    name: '一句话',
    kind: 'short', first: 'rewrite',
    text: '本季度我们将持续赋能业务增长',
  },
  {
    name: '文档里的「标签：内容」不是聊天',
    kind: 'text', first: 'summary',
    notKind: 'chat',
    text: `背景：客户会员复购率连续两个季度下滑
目标：半年内把复购率拉回 35%
现状：积分体系形同虚设，付费会员只有 2%
建议：先做分层权益，再考虑付费会员`,
  },
  {
    // 标签还成对重复出现 —— 光靠「至少有人说了两次」挡不住，得靠标签词表
    name: '重复出现的「问题 / 原因 / 方案」不是三个人在聊天',
    kind: 'text', first: 'summary',
    notKind: 'chat',
    text: `问题：新客首单转化低
原因：落地页加载慢，首屏没有价格
方案：压缩首屏图片，价格上移
问题：复购率下滑
原因：积分没有兑换出口
方案：上线积分商城`,
  },
]
