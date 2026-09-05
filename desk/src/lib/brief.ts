import type { Engagement, Inquiry } from './types'
import { stageOf } from './types'
import * as D from './date'

/**
 * 从调研线出材料 —— 这条流水线的出口。
 *
 * 提纲进去，材料出来。中间那些贴回来的 AI 原文**不进材料**：
 * 那是过程，不是产物。进材料的只有她自己写的那一句结论，
 * 加上「还没搞清楚的」——因为按她自己定的规矩，
 * 「局限和没做到的地方如实写，不要粉饰」。
 *
 * 格式照她给老板/客户看材料的那套要求：结论先行，一条一段，
 * 没查完的单独列出来而不是藏起来。
 */
export function buildBrief(eng: Engagement, all: Inquiry[]): string {
  const mine = all.filter((q) => q.engagementId === eng.id)
  const done = mine.filter((q) => stageOf(q) === 'concluded')
  const open = mine.filter((q) => stageOf(q) !== 'concluded')

  const head = [
    `# ${eng.name}${eng.client ? ` · ${eng.client}` : ''}`,
    '',
    `${D.longCN()}　已有结论 ${done.length} / ${mine.length} 条`,
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
        ]),
      ]
    : ['## 结论', '', '（还没有一条走到结论）', '']

  // 没查完的必须写出来。藏起来的话，看材料的人会以为这就是全部
  const tail = open.length
    ? [
        '## 还没搞清楚的',
        '',
        ...open.map((q) => {
          const st = stageOf(q)
          const note = st === 'found' ? '材料齐了，还没提炼'
            : st === 'prompted' ? 'Prompt 备好了，还没去问'
            : '还没开始'
          return `- ${q.question.trim()}　——　${note}`
        }),
        '',
      ]
    : []

  return [...head, ...body, ...tail].join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}
