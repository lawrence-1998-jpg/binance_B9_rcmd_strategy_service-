const CN_NUM = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

export function key(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * `YYYY-MM-DD` → Date（本地时区的当天零点）。
 *
 * 输入不合法时返回今天，而不是 Invalid Date：坏日期往下游一传，
 * 界面上出现的是「NaN/NaN undefined」这种东西，人完全看不懂发生了什么。
 * 日期会从三个地方进来——手填的 <input type="date">、导入的备份、
 * 被剥过 EXIF 的照片——都可能是空的或畸形的。
 */
export function parse(k: string): Date {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(k ?? ''))
  if (!m) return new Date()
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Number.isNaN(d.getTime()) ? new Date() : d
}

/** 这个字符串是不是一个能用的日期 */
export function isDateKey(k: unknown): boolean {
  if (typeof k !== 'string') return false
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(k)
  if (!m) return false
  const y = Number(m[1]), mo = Number(m[2]), d = Number(m[3])
  if (y < 1900 || y > 2200 || mo < 1 || mo > 12 || d < 1 || d > 31) return false
  const dt = new Date(y, mo - 1, d)
  return dt.getMonth() === mo - 1 && dt.getDate() === d
}

/** 12 → 十二；21 → 二十一 */
function cn(n: number): string {
  if (!Number.isFinite(n) || n < 0 || n > 99) return String(n)
  if (n <= 10) return CN_NUM[n]
  if (n < 20) return '十' + CN_NUM[n - 10]
  const t = Math.floor(n / 10)
  const o = n % 10
  return CN_NUM[t] + '十' + (o ? CN_NUM[o] : '')
}

/** 九月二日 · 周二 */
export function longCN(d = new Date()): string {
  return `${cn(d.getMonth() + 1)}月${cn(d.getDate())}日 · ${WEEK[d.getDay()]}`
}

/** 10/01 周四 */
export function shortCN(k: string): string {
  const d = parse(k)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${WEEK[d.getDay()]}`
}

/**
 * 照片墙/时间轴的日期标题：`08/30 周六`，跨年时补上年份 `2024/08/30 周五`。
 *
 * shortCN 不带年份，对「今天前后几天」的场景是对的。但照片会一直攒下去，
 * 两年前的 8 月 30 和今年的 8 月 30 在标题上长得一模一样，
 * 相册就分不出哪趟是哪趟了。只在不是今年时才补年份，
 * 平时不让年份占地方。
 */
export function archiveCN(k: string, now = new Date()): string {
  const d = parse(k)
  const p = (n: number) => String(n).padStart(2, '0')
  const md = `${p(d.getMonth() + 1)}/${p(d.getDate())} ${WEEK[d.getDay()]}`
  return d.getFullYear() === now.getFullYear() ? md : `${d.getFullYear()}/${md}`
}

export function daysBetween(from: Date, to: Date): number {
  const a = new Date(from.getFullYear(), from.getMonth(), from.getDate()).getTime()
  const b = new Date(to.getFullYear(), to.getMonth(), to.getDate()).getTime()
  return Math.round((b - a) / 86400000)
}

export function daysUntil(k: string, now = new Date()): number {
  return daysBetween(now, parse(k))
}

/** 每年重复的纪念日：下一次是什么时候、还有几天、已经过了几周年 */
export function nextAnniversary(k: string, now = new Date()) {
  const src = parse(k)
  let next = new Date(now.getFullYear(), src.getMonth(), src.getDate())
  if (daysBetween(now, next) < 0) next = new Date(now.getFullYear() + 1, src.getMonth(), src.getDate())
  return {
    date: next,
    days: daysBetween(now, next),
    nth: next.getFullYear() - src.getFullYear(),
  }
}

/** HH:MM 距现在还有多久，返回分钟（可为负） */
export function minutesUntil(dateK: string, hhmm: string, now = new Date()): number {
  const t = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm ?? ''))
  const h = t ? Number(t[1]) : 0
  const m = t ? Number(t[2]) : 0
  const d = parse(dateK)
  d.setHours(h, m, 0, 0)
  return Math.round((d.getTime() - now.getTime()) / 60000)
}

export function humanMinutes(mins: number): string {
  const a = Math.abs(mins)
  if (a < 60) return `${a} 分钟`
  const h = Math.floor(a / 60)
  const m = a % 60
  return m ? `${h} 小时 ${m} 分` : `${h} 小时`
}

export function relTime(ts: number, now = Date.now()): string {
  const s = Math.round((now - ts) / 1000)
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`
  const d = daysBetween(new Date(ts), new Date(now))
  if (d === 0) return `${Math.floor(s / 3600)} 小时前`
  if (d === 1) return '昨天'
  if (d < 30) return `${d} 天前`
  return shortCN(key(new Date(ts)))
}

export function hhmm(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 早上 / 下午 / 晚上 —— 只按时间做确定性切换，不猜用户意图 */
export function greeting(d = new Date()): string {
  const h = d.getHours()
  if (h < 5) return '还没睡'
  if (h < 11) return '早安'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

export function isEvening(d = new Date()): boolean {
  return d.getHours() >= 18 || d.getHours() < 5
}
