import { type Item } from './card'

/**
 * 放到别处：日程 → 手机日历（.ics），名片 → 手机通讯录（.vcf）。
 * 手机上点开这两种文件，系统会直接弹出「添加到日历」「新建联系人」。
 * 全在本地算，不联网。纯函数，test/unit.mjs 直接跑。
 */

// ---------------------------------------------------------------- 读时间：「周五上午 10 点」→ 哪一天几点

const CN: Record<string, number> = { 零: 0, 〇: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 }
/** 「十一」「二十」「八」→ 数字；阿拉伯数字原样 */
function num(s: string): number {
  if (/^\d+$/.test(s)) return Number(s)
  if (s === '十') return 10
  const [a, b] = s.split('十')
  if (b === undefined) return CN[a] ?? NaN
  return (a ? CN[a] : 1) * 10 + (b ? CN[b] : 0)
}
const WD: Record<string, number> = { 日: 0, 天: 0, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6 }
const N = '(\\d{1,2}|[零〇一二两三四五六七八九十]{1,3})'

export interface When { start: Date; allDay: boolean }

/**
 * 从一段话里读出最像「约的那个时间」的时刻。读不出就给 null（不瞎猜）。
 * 只给了星期几：取今天起最近的那一天（周三说「周五」是这周五，周六说「周五」是下周五）。
 * 只给了月日：离今天已经过去一个多月的，算明年。
 */
export function when(text: string, now = new Date()): When | null {
  const t = text.replace(/\s+/g, '')
  const day0 = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  let date: Date | null = null
  let m: RegExpMatchArray | null

  if ((m = t.match(/(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})/))) date = new Date(+m[1], +m[2] - 1, +m[3])
  else if ((m = t.match(new RegExp(`${N}月${N}[日号]?`)))) {
    date = new Date(now.getFullYear(), num(m[1]) - 1, num(m[2]))
    if (day0.getTime() - date.getTime() > 31 * 86_400_000) date.setFullYear(date.getFullYear() + 1)
  } else if ((m = t.match(/(大后天|后天|明天|明早|明晚|今天|今早|今晚)/))) {
    const add = { 今天: 0, 今早: 0, 今晚: 0, 明天: 1, 明早: 1, 明晚: 1, 后天: 2, 大后天: 3 }[m[1]] ?? 0
    date = new Date(day0.getTime()); date.setDate(date.getDate() + add)
  } else if ((m = t.match(/(下下|下|本|这)?(?:周|星期|礼拜)([一二三四五六日天])/))) {
    const want = WD[m[2]]
    // 以周一为一周的开头
    const mon = new Date(day0.getTime()); mon.setDate(mon.getDate() - ((day0.getDay() + 6) % 7))
    const offset = (want + 6) % 7
    if (m[1] === '下' || m[1] === '下下') {
      date = new Date(mon.getTime()); date.setDate(mon.getDate() + (m[1] === '下' ? 7 : 14) + offset)
    } else if (m[1]) {
      date = new Date(mon.getTime()); date.setDate(mon.getDate() + offset)
    } else {
      date = new Date(day0.getTime()); date.setDate(date.getDate() + ((want - day0.getDay() + 7) % 7))
    }
  } else if (/月底/.test(t)) date = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  else if ((m = t.match(/(today|tonight|tomorrow)/i))) {
    date = new Date(day0.getTime()); date.setDate(date.getDate() + (/tomorrow/i.test(m[1]) ? 1 : 0))
  } else if ((m = text.match(/\b(next\s+)?(sun|mon|tue|wed|thu|fri|sat)[a-z]*\b/i))) {
    const want = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'].indexOf(m[2].toLowerCase())
    date = new Date(day0.getTime()); date.setDate(date.getDate() + ((want - day0.getDay() + 7) % 7) + (m[1] ? 7 : 0))
  }

  let hour: number | null = null
  let min = 0
  const PART = '(凌晨|早上|早晨|上午|中午|下午|傍晚|晚上|今晚|明晚|晚)'
  // 阿拉伯数字的钟点可以不带「上午 / 下午」；汉字的必须带 —— 不然「快一点」就成了凌晨 1 点
  const tm = t.match(new RegExp(`${PART}?(\\d{1,2})(?:[:：](\\d{2})|点(半|(\\d{1,2})分?|钟)?)`))
    ?? t.match(new RegExp(`${PART}([零〇一二两三四五六七八九十]{1,3})点(半|([零〇一二两三四五六七八九十]{1,3})分?|钟)?`))
  if (tm) {
    const zh = !/^\d/.test(tm[2])
    hour = num(tm[2])
    min = zh ? (tm[3] === '半' ? 30 : tm[4] ? num(tm[4]) : 0) : tm[3] ? Number(tm[3]) : tm[4] === '半' ? 30 : tm[5] ? Number(tm[5]) : 0
    const part = tm[1] ?? (/今晚|明晚/.test(t) ? '晚' : '')
    if (/下午|傍晚|晚/.test(part) && hour < 12) hour += 12
    else if (part === '中午' && hour < 11) hour += 12
  }
  // 「3pm」「10:30am」
  const ap = hour === null ? t.match(/(\d{1,2})(?::(\d{2}))?(am|pm)/i) : null
  if (ap) {
    hour = Number(ap[1]) % 12 + (/pm/i.test(ap[3]) ? 12 : 0)
    min = ap[2] ? Number(ap[2]) : 0
  }
  if (hour !== null && (hour > 23 || min > 59 || Number.isNaN(hour))) hour = null

  if (!date && hour === null) return null
  const d = date ?? new Date(day0.getTime())
  if (Number.isNaN(d.getTime())) return null
  if (hour === null) return { start: d, allDay: true }
  d.setHours(hour, min, 0, 0)
  return { start: d, allDay: false }
}

/** 卡片上的时间：先看「时间」那一格，再看「截止」，再看标题和原文 */
export function eventOf(it: Item, now = new Date()): { when: When; place?: string; due: boolean } | null {
  if (it.kind === 'data' && it.fields.some((f) => f.label === '验证码')) return null
  const pick = (re: RegExp) => it.fields.filter((f) => re.test(f.label)).map((f) => when(f.value, now)).find(Boolean) ?? null
  const at = pick(/时间|日期|开始/)
  const due = at ? null : pick(/截止|期限|到期|有效期/)
  const w = at ?? due ?? (it.kind === 'event' ? when(`${it.title} ${it.raw}`, now) : null)
  if (!w) return null
  const place = it.fields.find((f) => /地点|地址|位置|会议室/.test(f.label))?.value
  return { when: w, place, due: !at && !!due }
}

// ---------------------------------------------------------------- .ics

/** 按规范折行：每行不超过 75 个字节，不把一个汉字劈开 */
function fold(line: string): string {
  const enc = new TextEncoder()
  const out: string[] = []
  let cur = ''
  for (const ch of line) {
    if (enc.encode(cur + ch).length > (out.length ? 74 : 75)) { out.push(cur); cur = '' }
    cur += ch
  }
  out.push(cur)
  return out.join('\r\n ')
}
const esc = (s: string) => s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')
const p2 = (n: number) => String(n).padStart(2, '0')
const ymd = (d: Date) => `${d.getFullYear()}${p2(d.getMonth() + 1)}${p2(d.getDate())}`
const hms = (d: Date) => `T${p2(d.getHours())}${p2(d.getMinutes())}00`
const utc = (d: Date) => d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')

export function toIcs(it: Item, ev: { when: When; place?: string; due: boolean }, now = new Date()): string {
  const { start, allDay } = ev.when
  const end = new Date(start.getTime())
  if (allDay) end.setDate(end.getDate() + 1); else end.setHours(end.getHours() + 1)
  const note = [it.summary, it.raw].filter(Boolean).join('\n\n')
  const lines = [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//suishou//zh-CN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${it.id}@suishou`,
    `DTSTAMP:${utc(now)}`,
    // 不带时区的「本地时间」：她说的周五 10 点，在她手机上就是周五 10 点
    allDay ? `DTSTART;VALUE=DATE:${ymd(start)}` : `DTSTART:${ymd(start)}${hms(start)}`,
    allDay ? `DTEND;VALUE=DATE:${ymd(end)}` : `DTEND:${ymd(end)}${hms(end)}`,
    `SUMMARY:${esc((ev.due ? '截止：' : '') + it.title)}`,
    ...(ev.place ? [`LOCATION:${esc(ev.place)}`] : []),
    ...(note ? [`DESCRIPTION:${esc(note)}`] : []),
    // 提前一刻钟提醒（全天的截止：当天早上 9 点）
    'BEGIN:VALARM', 'ACTION:DISPLAY', `DESCRIPTION:${esc(it.title)}`, allDay ? 'TRIGGER:PT9H' : 'TRIGGER:-PT15M', 'END:VALARM',
    'END:VEVENT', 'END:VCALENDAR',
  ]
  return lines.map(fold).join('\r\n') + '\r\n'
}

// ---------------------------------------------------------------- .vcf

export interface Person { name: string; title?: string; phones: string[]; emails: string[]; urls: string[] }

/** 卡片里有电话或邮箱，就能存成一个联系人 */
export function personOf(it: Item): Person | null {
  const vals = (re: RegExp) => it.fields.filter((f) => re.test(f.label)).map((f) => f.value)
  const phones = vals(/电话|手机|座机|tel|phone|微信同/i).filter((v) => v.replace(/\D/g, '').length >= 7)
  const emails = vals(/邮箱|email|mail/i).filter((v) => v.includes('@'))
  if (!phones.length && !emails.length) return null
  if (it.kind !== 'contact' && !phones.length) return null
  const [first, ...rest] = it.title.split(/\s*[｜|/·，,]\s*/)
  const name = vals(/姓名|名字|联系人/)[0] ?? vals(/来自/)[0] ?? first ?? it.title
  const role = vals(/职位|头衔|title/i)[0] ?? (rest.join(' ') || undefined)
  return { name: name.trim(), title: role, phones, emails, urls: vals(/链接|网址|主页/) }
}

export function toVcf(p: Person, it: Item): string {
  const e = (s: string) => s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n')
  const lines = [
    'BEGIN:VCARD', 'VERSION:3.0',
    `FN:${e(p.name)}`,
    `N:;${e(p.name)};;;`,
    ...(p.title ? [`TITLE:${e(p.title)}`] : []),
    ...p.phones.map((t) => `TEL;TYPE=CELL:${t.replace(/[^\d+]/g, '')}`),
    ...p.emails.map((m) => `EMAIL;TYPE=INTERNET:${m}`),
    ...p.urls.map((u) => `URL:${u}`),
    `NOTE:${e(it.raw)}`,
    'END:VCARD',
  ]
  return lines.map(fold).join('\r\n') + '\r\n'
}
