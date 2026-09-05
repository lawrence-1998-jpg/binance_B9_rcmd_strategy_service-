/**
 * 提纲 → Prompt。
 *
 * 纯函数，不调用任何模型：好的调研 prompt 是一件手艺活，不是每次现生成的东西。
 * 模板里最要紧的一条是「不许编数字」——像「XX 的流量占比大概有多少」这类问题，
 * 模型极容易一本正经给一个看起来很专业的假百分比。宁可它说不知道。
 */

export type Target = 'tooled' | 'plain'
export type Depth = 'quick' | 'deep'

export interface PromptSpec {
  outline: string
  subject: string
  context: string
  target: Target
  depth: Depth
}

export const TARGETS: { key: Target; label: string; hint: string }[] = [
  { key: 'tooled', label: 'Claude Code', hint: '能联网、能跑工具' },
  { key: 'plain', label: 'GPT 对话', hint: '纯对话，可能没法联网' },
]

export const DEPTHS: { key: Depth; label: string; hint: string }[] = [
  { key: 'deep', label: '深度调研', hint: '要证据、要机制、要出处' },
  { key: 'quick', label: '快速摸底', hint: '先要个方向，十分钟看完' },
]

export function parseOutline(outline: string): string[] {
  return outline
    .split('\n')
    .map((l) => l.replace(/^\s*(?:\d+[.、)]|[-*·])\s*/, '').trim())
    .filter(Boolean)
}

export function buildPrompt(spec: PromptSpec): string {
  const items = parseOutline(spec.outline)
  if (items.length === 0) return ''

  const subject = spec.subject.trim()
  const context = spec.context.trim()
  const questions = items.map((q, i) => `${i + 1}. ${q}`).join('\n')

  const role = subject
    ? `你是一名熟悉${subject}所在赛道的产品与增长研究员`
    : '你是一名熟悉中文互联网内容平台产品与增长机制的研究员'

  const head = [
    '# 角色',
    `${role}。你最大的本事不是知道得多，而是**把「已证实的事实」「可合理推断的结论」「纯属猜测」严格分开**，并且敢说「这个我不知道」。`,
    '',
    ...(context ? ['# 我的处境', context, ''] : []),
    ...(subject ? ['# 调研对象', subject, ''] : []),
    '# 要回答的问题',
    questions,
    '',
  ]

  const guards = [
    '# 硬约束（违反任何一条，这次回答就算失败）',
    '',
    '**一、不许编数字。**',
    '凡是具体的百分比、量级、DAU、流量占比、增长率，只要没有公开来源，就必须先写「没有公开数据」，',
    '然后给一个**带推导过程的区间估算**，并明确标注「估算」。',
    '一个看起来很专业的假数字，比一句「不知道」有害得多——我会拿着它去跟客户讲。',
    '',
    '**二、标注每句话的性质。**',
    '每段结论前面用 `[事实]` / `[推断]` / `[猜测]` 标注。`[事实]` 必须配得上出处。',
    '',
    '**三、标注时间。**',
    '平台机制变得很快。说清你讲的是哪个时间段的情况；只知道旧做法就明说',
    '「这是 XX 年的做法，现在可能已经变了」，不要假装是当下。',
    '',
    '**四、不要泛泛而谈。**',
    '「加强创作者激励」这种话零价值。要具体到：什么位置、什么形式、给多少量、什么条件触发、什么节奏。',
    '',
  ]

  const structureDeep = [
    '# 每个问题按这个结构回答',
    '',
    '1. **一句话结论** —— 先给答案，不要铺垫',
    '2. **证据** —— 你依据的具体公开信息（产品版本变更 / 官方公告 / 公开演讲 / 媒体报道 / 创作者社区讨论），逐条给出处，能给链接就给链接',
    '3. **机制拆解** —— 这件事在产品上怎么运转：触发条件、作用对象、反馈形式、给多少量、什么节奏',
    '4. **置信度** —— 高 / 中 / 低，并说明为什么是这个档',
    '5. **对我的启发** —— 结合我的处境，这条结论意味着我该做什么、不该做什么',
    '',
  ]

  const structureQuick = [
    '# 每个问题按这个结构回答（控制在 200 字以内）',
    '',
    '1. **一句话结论**',
    '2. **依据** —— 一到两条，注明出处或说明「无公开来源」',
    '3. **置信度** —— 高 / 中 / 低',
    '4. **值得深挖的一个点**',
    '',
  ]

  const tools = spec.target === 'tooled'
    ? [
        '# 工具使用',
        '',
        '先联网检索，再回答。不要凭印象作答。',
        '- 每个关键结论至少找 **2 个独立来源**交叉验证',
        '- 把检索到的**原文关键句**摘录出来，不要只给链接',
        '- 中英文都搜；平台机制类问题优先找创作者社区、官方创作者学院、行业媒体的深度报道',
        '- 找不到就明确说找不到，**不要用常识补**',
        '',
      ]
    : [
        '# 关于你的能力边界',
        '',
        '如果你现在没有联网能力，那就**不要给任何具体数字**。',
        '把需要联网才能确认的地方，改成一份「该去哪查」的清单：',
        '查什么关键词、去哪个站点、大概能查到什么形态的证据。我自己去查。',
        '',
      ]

  const tail = [
    '# 输出格式',
    '',
    // 题号标题不是排版讲究，是接口：整段结果贴回 App 之后，
    // 要按这个标题把每道题的答案拆回对应的那条调研线上去。
    // 格式一乱，拆不开，她就得手工剪贴 —— 那正是这套东西要省掉的事
    '每个问题**必须**用二级标题开头，格式严格如下（题号对应上面的编号）：',
    '',
    '```',
    '## 1. 这里重复一遍问题原文',
    '```',
    '',
    '不要合并问题，不要改题号，不要在第一个 `## 1.` 之前写正文。',
    spec.depth === 'deep'
      ? '最后另起一节「## 还没搞清楚的」，列出你认为最该进一步验证的 3 件事，按重要性排序。'
      : '最后另起一节「## 先挖哪个」，一句话说明这几个问题里哪个最值得先深挖。',
  ]

  return [
    ...head,
    ...(spec.depth === 'deep' ? structureDeep : structureQuick),
    ...guards,
    ...tools,
    ...tail,
  ].join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}


/**
 * 把整段回答按题号拆回各条调研线。
 *
 * 她的实际动作是：复制一整套 prompt → 去问 → 拿回**一大段**答案。
 * 如果 App 只能一条一条地贴，她就得在手机上反复剪贴 n 次 ——
 * 那正是「它只是个备忘录」的那种活。所以整段贴回来，这里负责分发。
 *
 * 只认 `## 1.` 这种题号标题（prompt 里已经把格式定死了）。
 * 认不出来就返回 null，让调用方老实说「拆不开，你自己贴」，
 * 而不是瞎猜着把内容塞错地方 —— 塞错比不塞更糟。
 */
export interface SplitResult {
  /** 按题号归位的答案，长度等于题数；没归到的位置是空串 */
  parts: string[]
  /** 没归到任何一题的部分：开头的前言、结尾的「还没搞清楚的」等等 */
  rest: string
}

export function splitAnswer(text: string, count: number): SplitResult | null {
  if (!text.trim() || count <= 0) return null

  // 先找出所有标题的位置。一道题的正文，止于**下一个标题**（不管它有没有题号）——
  // 不然结尾那节「还没搞清楚的」会被粘到最后一题的材料里。
  // 那节是整套的产出，不是某一题的答案，混进去等于悄悄污染她的材料
  const heads: { at: number; end: number; n: number | null }[] = []
  const re = /^[ \t]*#{1,4}[ \t]*(?:(?:第)?(\d+)[.、)．]?)?[^\n]*$/gm
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m[0].trim() === '') continue
    heads.push({ at: m.index, end: re.lastIndex, n: m[1] ? Number(m[1]) : null })
  }
  const numbered = heads.filter((h) => h.n !== null && h.n >= 1 && h.n <= count)
  if (numbered.length === 0) return null

  const parts: string[] = Array.from({ length: count }, () => '')
  const claimed: [number, number][] = []
  for (const h of numbered) {
    const next = heads.find((x) => x.at > h.at)
    const stop = next ? next.at : text.length
    const body = text.slice(h.at, stop).trim()
    const i = h.n! - 1
    parts[i] = parts[i] ? `${parts[i]}\n\n${body}` : body
    claimed.push([h.at, stop])
  }

  // 剩下的原样交回去，由调用方摆到她看得见的地方。悄悄扔掉是不行的
  claimed.sort((a, b) => a[0] - b[0])
  const left: string[] = []
  let cur = 0
  for (const [a, b] of claimed) {
    if (a > cur) left.push(text.slice(cur, a))
    cur = Math.max(cur, b)
  }
  if (cur < text.length) left.push(text.slice(cur))

  return { parts, rest: left.join('\n').trim() }
}

/**
 * 访谈提纲。
 *
 * 她的活儿有两条路：一条是拿去问 AI，一条是拿去问人（约访）。
 * 走的是同一条流水线，但第二站产出的东西完全不同 ——
 * 给人的问题不能像给模型的那样堆约束，得是能照着念的、
 * 带追问的、有开场和收尾的。
 */
export function buildInterviewGuide(spec: PromptSpec): string {
  const items = parseOutline(spec.outline)
  if (items.length === 0) return ''
  const who = spec.subject.trim()
  const context = spec.context.trim()

  const head = [
    `# 访谈提纲${who ? ` · ${who}` : ''}`,
    '',
    ...(context ? ['> 背景：' + context, ''] : []),
    '## 开场（2 分钟）',
    '',
    '- 说明来意和大概时长，说清会不会记录',
    '- 先请对方用自己的话讲一遍他负责什么、一天大概怎么过',
    '  （别急着进正题：这段决定了后面他愿不愿意说实话）',
    '',
    '## 正题',
    '',
  ]

  const body = items.flatMap((q, i) => [
    `### ${i + 1}. ${q}`,
    '',
    '- 先问事实：**最近一次**是什么时候？当时具体发生了什么？',
    '- 再问动作：那你怎么做的？为什么这么做？',
    '- 追问反例：有没有过不是这样的时候？那次有什么不一样？',
    '- 追问量级：大概多少 / 多久一次？（对方给不出就记「说不上来」，别替他圆）',
    '',
    '记录：',
    '',
    '',
  ])

  const tail = [
    '## 收尾（3 分钟）',
    '',
    '- 「还有什么我没问到、但你觉得我该知道的？」——这一句经常问出最有价值的东西',
    '- 确认可否引用、可否署名',
    '- 问他还建议我找谁聊',
    '',
    '## 访谈后 10 分钟内补的',
    '',
    '- 最意外的一件事：',
    '- 他反复提到的词：',
    '- 我原来的假设被推翻了吗：',
  ]

  return [...head, ...body, ...tail].join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}
