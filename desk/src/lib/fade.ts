/**
 * 荒掉的东西该有个体面的退路。
 *
 * 让个人工作台死掉的头号原因不是功能少，是维护成本 —— 业内给的经验阈值是
 * 每周维护超过 30 分钟这个系统就太重了。而案头有十几个要手填的入口，
 * 其中几个注定会先荒掉：不是因为你懒，是因为它们本来就不该天天填。
 *
 * 问题不在「荒了」，在于**荒了之后它一点反应都没有**：那块地方会一直占着
 * 屏幕，看起来像还在用，于是每次翻过去都要重新确认一遍「这个我还要吗」。
 * 那一下一下的确认，就是维护成本本身。
 *
 * 所以这里做的事只有一件：**替你把那句话问出来，然后闭嘴。**
 *
 * 三条自己给自己定的规矩：
 *
 * ① **只问「流」，不问「档案」。**
 *    纪念日填一次就不动了，那是健康的，问它等于添乱。只有那些本来就该
 *    不断进新东西的分区才会被问。
 *
 * ② **每个分区按自己的节奏。**
 *    「想对他说」两周不动是真荒了；「想一起做的事」是个愿望清单，两个月
 *    不动很正常。用同一个天数去卡所有分区，等于假装它们节奏一样。
 *
 * ③ **说了「留着」就要真的闭嘴一整轮。**
 *    一个问完还接着问的提示，就是新的维护成本 —— 那正是这整件事要消灭的
 *    东西。所以「留着」会把计时清零，下一次要重新数够天数才会再开口。
 */

export interface FadeSpec {
  /** 存进 state 用的 key */
  key: string
  /** 问她的时候怎么称呼这块 */
  label: string
  /** 多少天不动才开口。按这块内容自己的节奏定，不是一个统一数 */
  days: number
  /** 为什么是这个天数 —— 写下来，免得以后有人随手改成一个整数 */
  why: string
}

export const FADES: FadeSpec[] = [
  { key: 'moments', label: '想对他说', days: 14,
    why: '本来就是天天可以写一句的东西，两周一句没有，就是真的停了' },
  { key: 'heard', label: '他提过的', days: 21,
    why: '要在他说的当下想起来打开 App，本来就偶发；三周才算信号' },
  { key: 'photos', label: '照片', days: 30,
    why: '照片是一阵一阵的，出去玩一次能加一批，然后空很久，一个月才算停' },
  { key: 'wishes', label: '想一起做的事', days: 60,
    why: '愿望清单天生就是慢的，两个月不动完全正常，只有更久才值得一问' },
]

export const FADE_KEYS = FADES.map((f) => f.key)

/**
 * 这块该不该开口问。
 *
 * 返回「已经多少天没动了」，或者 null（不问）。
 * 空的分区一律不问 —— 她一次都没用过的东西，替她收起来是自作主张。
 */
export function fadedDays(
  spec: FadeSpec,
  lastAt: number | null,
  keptAt: number | undefined,
  now: number,
): number | null {
  if (lastAt == null) return null              // 一条都没有：不问
  // 说过「留着」之后，从那一刻重新数。不重新数就是接着唠叨
  const since = Math.max(lastAt, keptAt ?? 0)
  const days = Math.floor((now - since) / 86400000)
  return days >= spec.days ? Math.floor((now - lastAt) / 86400000) : null
}

/** 行程是另一回事：它不是荒了，是过期了。国庆过完，那份行程就是死数据 */
export function tripOver(end: string, now: number): boolean {
  if (!end) return false
  const t = Date.parse(`${end}T23:59:59`)
  return Number.isFinite(t) && now > t
}
