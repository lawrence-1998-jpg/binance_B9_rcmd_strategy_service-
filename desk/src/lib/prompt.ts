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
    'Markdown。每个问题一个二级标题。',
    spec.depth === 'deep'
      ? '最后加一节「**还没搞清楚的**」，列出你认为最该进一步验证的 3 件事，按重要性排序。'
      : '最后用一句话说：这几个问题里哪个最值得先深挖。',
  ]

  return [
    ...head,
    ...(spec.depth === 'deep' ? structureDeep : structureQuick),
    ...guards,
    ...tools,
    ...tail,
  ].join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}
