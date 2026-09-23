import type { Item } from './lib/card'

/**
 * 库还是空的时候摆出来的几张示例卡：让她一打开就看到「贴进来会变成什么」。
 * 明确标着「示例」，不进她的库；她收下第一条就消失。
 */
const base = { status: 'done' as const, pinned: false, createdAt: 0, updatedAt: 0 }

export const EXAMPLES: Item[] = [
  {
    ...base,
    id: 'ex-event',
    kind: 'event',
    raw: '王总：周四下午的会挪到周五上午 10 点吧，地点还是国贸三期 B 座 1208。记得带上次那版竞品分析，财务的 Linda 也会来。',
    title: '王总的会改到周五',
    summary: '会议改到周五上午 10 点，地点不变，要带竞品分析，财务 Linda 参加。',
    fields: [
      { label: '时间', value: '周五 10:00' },
      { label: '地点', value: '国贸三期 B 座 1208' },
      { label: '参会', value: '王总、Linda（财务）' },
    ],
    todos: [{ text: '带上一版竞品分析', done: false }, { text: '回复王总确认时间', done: false }],
    tags: ['客户会议'],
    prompt: '帮我回复王总：确认改到周五上午 10 点，并说明会带上竞品分析。语气简洁客气。',
  },
  {
    ...base,
    id: 'ex-contact',
    kind: 'contact',
    raw: 'Lily Chen｜增长策略负责人\n手机 138 1234 5678\n邮箱 lily.chen@example.com\n微信同手机号',
    title: 'Lily Chen · 增长策略',
    summary: '增长策略负责人，手机与微信同号。',
    fields: [
      { label: '姓名', value: 'Lily Chen' },
      { label: '职位', value: '增长策略负责人' },
      { label: '手机', value: '138 1234 5678' },
      { label: '邮箱', value: 'lily.chen@example.com' },
    ],
    todos: [],
    tags: ['人脉'],
    prompt: '帮我给 Lily Chen 写一条初次联系的微信，说明我想约 20 分钟聊增长策略合作。',
  },
  {
    ...base,
    id: 'ex-data',
    kind: 'data',
    raw: '报价：年费版 ¥36,000/年（含 20 个席位），超出部分每席 ¥1,500/年；首年 8 折。报价有效期至 10 月 15 日。',
    title: 'SaaS 年费报价',
    summary: '20 席年费 3.6 万，加席每席 1500，首年 8 折，10 月 15 日前有效。',
    fields: [
      { label: '年费', value: '¥36,000/年（含 20 席）' },
      { label: '加席', value: '¥1,500/席/年' },
      { label: '折扣', value: '首年 8 折' },
      { label: '有效期', value: '10 月 15 日' },
    ],
    todos: [{ text: '10 月 15 日前决定是否签', done: false }],
    tags: ['采购', '报价'],
    prompt: '帮我算一下：团队 26 人时这份报价首年和第二年各要多少钱，并列出可以去谈的点。',
  },
]
