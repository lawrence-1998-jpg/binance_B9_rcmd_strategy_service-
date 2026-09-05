import { key } from './date'
import type { State } from './types'

const id = () => Math.random().toString(36).slice(2, 10)

/**
 * 首次打开时的示例数据。
 * 都是「形状对、内容假」——为的是让你一眼看懂每块放什么，
 * 而不是替你决定内容。设置里有「清空示例数据」。
 * 纪念日故意留空：填错的日子比空着更糟。
 */
export function seed(): State {
  const today = key()
  return {
    version: 1,
    seeded: true,
    focus: {},
    tasks: [
      { id: id(), title: '客户 A 的诊断报告写完第三章', domain: 'consult', est: 90, done: false, date: today },
      { id: id(), title: '推荐位改版需求文档过一遍', domain: 'byte', est: 45, done: false, date: today },
      { id: id(), title: '订国庆的往返票', domain: 'us', est: 20, done: false, date: today },
    ],
    notes: [
      { id: id(), text: '示例：想到一个客户访谈的切入问法', kind: 'idea', createdAt: Date.now() - 7200000, handled: false },
      { id: id(), text: '示例：他说想要那台咖啡机', kind: 'us', createdAt: Date.now() - 86400000, handled: false },
    ],
    engagements: [
      {
        id: id(), name: '会员体系诊断', domain: 'consult', client: '客户 A',
        stage: '访谈完成 · 正在写报告', blocker: '等客户给数据口径', status: 'warn',
        progress: 62, next: '交初稿', nextDate: addDays(today, 4), updatedAt: Date.now() - 3600000,
      },
      {
        id: id(), name: '增长策略陪跑', domain: 'consult', client: '客户 B',
        stage: '第 3 次工作坊', blocker: '', status: 'ok',
        progress: 45, next: '出工作坊纪要', nextDate: addDays(today, 1), updatedAt: Date.now() - 172800000,
      },
      {
        id: id(), name: '推荐位改版', domain: 'byte', client: '增长方向',
        stage: '需求评审中', blocker: '等设计终稿', status: 'warn',
        progress: 40, next: '评审会', nextDate: addDays(today, 2), updatedAt: Date.now() - 5400000,
      },
      {
        id: id(), name: 'Q4 OKR 对齐', domain: 'byte', client: '团队',
        stage: '草稿已发', blocker: '', status: 'ok',
        progress: 75, next: '和 leader 一对一', nextDate: addDays(today, 3), updatedAt: Date.now() - 86400000,
      },
    ],
    inquiries: [],
    meetings: [
      { id: id(), title: '客户 A 周会', date: today, start: '15:00', end: '16:00', domain: 'consult', note: '带上诊断中期结论' },
      { id: id(), title: '需求评审', date: addDays(today, 2), start: '10:30', end: '11:30', domain: 'byte' },
    ],
    anniversaries: [],
    wishes: [
      { id: id(), text: '一起去看一次日出', who: 'both', done: false, createdAt: Date.now() },
      { id: id(), text: '学会做他最爱吃的那道菜', who: 'me', done: false, createdAt: Date.now() },
      { id: id(), text: '拍一组两个人的照片', who: 'both', done: false, createdAt: Date.now() },
    ],
    trip: {
      title: '国庆',
      start: '2026-10-01',
      end: '2026-10-08',
      budget: 0,
      days: [],
      todos: [
        { id: id(), text: '订往返机票', kind: 'book', owner: 'me', done: false },
        { id: id(), text: '订住宿', kind: 'book', owner: 'both', done: false },
        { id: id(), text: '请假 / 工作交接报备', kind: 'plan', owner: 'me', done: false },
        { id: id(), text: '定一顿好的', kind: 'plan', owner: 'him', done: false },
        { id: id(), text: '充电宝、转换头、常备药', kind: 'pack', owner: 'both', done: false },
      ],
    },
    logs: [],
    promptDraft: {
      outline: [
        'UGC 投稿用户的流量下滑导致投稿流失，抖音有没有出现过，怎么解决的',
        '抖音现在做作者流量反馈的流量占比大概有多少，是怎么做的',
      ].join('\n'),
      subject: '抖音',
      context: '我在给一个 UGC 内容社区做投稿量下滑的诊断，要找可借鉴的做法。',
      target: 'tooled',
      depth: 'deep',
    },
    photos: [],
    moments: [],
    entries: [],
    myPrompts: [],
    promptUses: {},
    promptParts: [],
  }
}

export function empty(): State {
  const s = seed()
  return {
    ...s,
    tasks: [], notes: [], engagements: [], meetings: [],
    anniversaries: [], wishes: [],
    // 连同标题和日期一起清。留着 seed 里的「国庆 10/01–10/08」，
    // 用户就会在「清空全部数据」之后仍然看到一个自己从没设过的假期在倒数
    trip: { title: '', start: '', end: '', budget: 0, days: [], todos: [] },
    logs: [],
    promptDraft: {
      outline: [
        'UGC 投稿用户的流量下滑导致投稿流失，抖音有没有出现过，怎么解决的',
        '抖音现在做作者流量反馈的流量占比大概有多少，是怎么做的',
      ].join('\n'),
      subject: '抖音',
      context: '我在给一个 UGC 内容社区做投稿量下滑的诊断，要找可借鉴的做法。',
      target: 'tooled',
      depth: 'deep',
    },
    photos: [],
    moments: [],
    entries: [],
    myPrompts: [],
    promptUses: {},
    promptParts: [],
  }
}

function addDays(k: string, n: number): string {
  const [y, m, d] = k.split('-').map(Number)
  const dt = new Date(y, m - 1, d + n)
  return key(dt)
}
