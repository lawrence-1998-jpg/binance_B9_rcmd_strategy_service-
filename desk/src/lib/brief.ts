import type { Engagement, Fact, Inquiry } from './types'
import { CONFIDENCE, isLive, stageOf } from './types'
import * as D from './date'

/**
 * 从调研线出材料 —— 这条流水线的出口。
 *
 * 提纲进去，材料出来。中间那些贴回来的 AI 原文**不进材料**：
 * 那是过程，不是产物。进材料的是她自己写的那句结论，
 * 加上她亲手抄下来的数据（连着出处和置信度一起），
 * 再加上「还没搞清楚的」——因为按她自己定的规矩，
 * 「局限和没做到的地方如实写，不要粉饰」。
 *
 * 数据必须带着出处一起出现。这两样分开过一次，就会有人拿着一个
 * 没出处的百分比去跟客户讲 —— 而那个人就是她。
 */
function factLine(f: Fact): string {
  const conf = CONFIDENCE.find((c) => c.key === f.confidence)?.label ?? '中'
  const src = f.source.trim() || '**没有出处**'
  return `- \`${f.value.trim()}\` —— ${f.what.trim()}　｜　出处：${src}　｜　置信 ${conf}`
}

export function buildBrief(eng: Engagement, all: Inquiry[]): string {
  const mine = all.filter((q) => q.engagementId === eng.id)
  const live = mine.filter(isLive)
  const done = live.filter((q) => stageOf(q) === 'concluded')
  const open = live.filter((q) => stageOf(q) !== 'concluded')
  const closed = mine.filter((q) => q.closed)

  const head = [
    `# ${eng.name}${eng.client ? ` · ${eng.client}` : ''}`,
    '',
    `${D.longCN()}　已有结论 ${done.length} / ${live.length} 条`,
    '',
  ]

  const body = done.length
    ? [
        '## 结论',
        '',
        ...done.flatMap((q, i) => [
          `**${i + 1}. ${q.question.trim()}**`,
          '',
          q.conclusion!.trim(),
          '',
          ...(q.facts?.length ? ['依据的数据：', '', ...q.facts.map(factLine), ''] : []),
        ]),
      ]
    : ['## 结论', '', '（还没有一条走到结论）', '']

  // 还没走到结论、但已经攒了数据的，也要列出来 —— 那些数字是真金白银查来的，
  // 不该因为「这条还没写完」就整段消失
  const loose = open.filter((q) => q.facts?.length)
  const evidence = loose.length
    ? [
        '## 已经查到、但还没下结论的数据',
        '',
        ...loose.flatMap((q) => [`**${q.question.trim()}**`, '', ...q.facts!.map(factLine), '']),
      ]
    : []

  // 没查完的必须写出来。藏起来的话，看材料的人会以为这就是全部
  const note = (q: Inquiry) => {
    if (q.closed === 'parked') return '先搁置了'
    if (q.closed === 'dropped') return '决定不查了'
    const st = stageOf(q)
    return st === 'found' ? '材料齐了，还没提炼'
      : st === 'prompted' ? (q.kind === 'interview' ? '提纲备好了，还没约到人' : 'Prompt 备好了，还没去问')
      : '还没开始'
  }
  const rest = [...open, ...closed]
  const tail = rest.length
    ? ['## 还没搞清楚的', '', ...rest.map((q) => `- ${q.question.trim()}　——　${note(q)}`), '']
    : []

  return [...head, ...body, ...evidence, ...tail].join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}
