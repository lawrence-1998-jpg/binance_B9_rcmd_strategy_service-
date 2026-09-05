import { useEffect, useState } from 'react'

/**
 * 新版本怎么到她手上。
 *
 * 实测过一遍才发现这条路是瘸的：装着旧版的手机，**打开一次拿到的还是旧版**，
 * 要开第二次才换过来。也就是说我这边每修一个 bug，对她都是隐形的——
 * 她看到的还是坏的，而我这边显示「已部署」。这比 bug 本身更糟：
 * 它让所有修复都不算数。
 *
 * 所以改成自己接管：
 *   1. Service Worker 用 prompt 模式装（新版装好后**等着**，不抢），
 *      什么时候换由这里说了算，不会出现「新 SW 已经在服务新资源，
 *      页面还跑着旧代码」的半截状态。
 *   2. 刚打开就发现新版 → 直接换，不问。她刚点开图标，页面还没开始用，
 *      白一下就好了，问她「要不要更新」是把我的实现细节推给她。
 *   3. 用着用着才发现（比如从后台切回来）→ 只在底下浮一条，她点了才换。
 *      正在打字的时候把页面刷掉是不可接受的。
 *   4. 从后台切回前台时主动查一次。iOS 主屏 PWA 被挂起再恢复**不产生导航**，
 *      不主动查的话，她可能好几天都碰不到一次更新检查。
 *
 * 没有 Service Worker 的环境（单文件版、file:// 双击打开）整个模块是空转。
 */

/** 刚打开这段时间内发现的新版，直接换掉不打扰 */
const GRACE_MS = 12_000
/**
 * 自动换版最多试这么多次，之后只浮那一条让她点。
 *
 * 这个上限不是保守，是踩出来的：旧 SW 手上挂着几个永远回不来的请求
 * （网差的时候拉 Google 字体就是这样）时，新的那个迟迟上不了位，
 * 而我原本写的是「过一会儿没动静就自己刷」——于是页面每两秒刷一次，
 * 永远刷不出新版本，也永远停不下来。宁可让她多点一下
 */
const MAX_AUTO = 2
const TRY_KEY = 'deskside.sw-try'
/** 长时间挂在前台时也定期查一次 */
const POLL_MS = 30 * 60 * 1000

let reg: ServiceWorkerRegistration | null = null
let waiting: ServiceWorker | null = null
let reloading = false
/** 已经在换了：消息发出去了，等新的那个接管 */
let applying = false
let started = 0
let hadController = false
/** 她动过这个页面没有。没动过 = 现在刷掉，她什么都不会察觉 */
let touched = false

const subs = new Set<() => void>()
const emit = () => subs.forEach((f) => f())

/** 有没有一版已经装好、就等着换 */
export function updateReady(): boolean {
  return waiting !== null
}

export interface UpdateState {
  /** 有新版本等着 */
  ready: boolean
  /** 正在换 —— 换一次要几秒，这几秒必须有话说，不然像是点了没反应 */
  applying: boolean
}

export function useUpdate(): UpdateState {
  const [, bump] = useState(0)
  useEffect(() => {
    const f = () => bump((n) => n + 1)
    subs.add(f)
    return () => { subs.delete(f) }
  }, [])
  return { ready: waiting !== null, applying }
}

/** 焦点在输入框里 —— 这时候刷新页面等于把她写的东西打断 */
function typing(): boolean {
  const el = document.activeElement
  return !!el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)
}

function tries(): number {
  try { return Number(sessionStorage.getItem(TRY_KEY)) || 0 } catch { return 0 }
}
function noteTry(n: number) {
  try { sessionStorage.setItem(TRY_KEY, String(n)) } catch { /* 无痕模式，算了 */ }
}
function clearTries() {
  try { sessionStorage.removeItem(TRY_KEY) } catch { /* 同上 */ }
}

function reload() {
  if (reloading) return
  reloading = true
  location.reload()
}

/**
 * 换到新版：叫等着的那个 SW 上位，它接管页面之后才刷。
 *
 * 这里**没有**「过几秒没动静就自己刷」的兜底，这是想清楚了才拿掉的：
 * 旧 SW 让位实测要四秒左右，定时器一到就刷的话，刷回来的还是旧版本，
 * 于是又发现一次新版、又刷一次——我写过那一版，页面每几秒刷一次，
 * 永远刷不到新的，也永远停不下来。
 *
 * 唯一算数的信号是 controllerchange：新的那个真的接管了。它不来，
 * 就把那一条放回去让她再点一次——停在一个说得清的状态，
 * 好过刷一个永远收敛不了的循环。
 */
export function applyUpdate(): void {
  if (reloading || applying) return
  if (!waiting) { reload(); return }
  applying = true
  noteTry(tries() + 1)
  emit()
  waiting.postMessage({ type: 'SKIP_WAITING' })
  setTimeout(() => {
    if (reloading) return
    applying = false
    emit()
  }, 20_000)
}

function found(sw: ServiceWorker) {
  if (waiting === sw) return
  waiting = sw
  // 「她还没开始用」比「打开不到十几秒」是更准的判断：刚点开图标还没碰过的
  // 页面，刷掉等于没发生；已经在翻、在写的页面，刷掉就是打断
  const quiet = !touched || Date.now() - started < GRACE_MS
  // 试过两回还没换成功就不再自己刷了，浮一条出来让她点
  if (quiet && !typing() && tries() < MAX_AUTO) applyUpdate()
  else emit()
}

function track(r: ServiceWorkerRegistration) {
  reg = r
  // 上次开着的时候就装好了、一直等到现在的
  if (r.waiting && navigator.serviceWorker.controller) found(r.waiting)
  // 必须自己催一下。register() 自带的那次检查是「有空再说」——实测过，
  // 打开后十几秒才想起来去查，而那时候宽限期早过了，她就只能看到一条
  // 「有新版本」而不是打开就是新的
  void r.update().then(() => {
    // 查完了也没有人在等 = 已经是最新的，把「试了几次」清掉
    if (!r.waiting && !r.installing) clearTries()
  }).catch(() => {})
  r.addEventListener('updatefound', () => {
    const sw = r.installing
    if (!sw) return
    sw.addEventListener('statechange', () => {
      // 没有 controller = 这是第一次装 SW，不是更新，不要刷
      if (sw.state === 'installed' && navigator.serviceWorker.controller) found(sw)
    })
  })
}

/**
 * 手动查一次，等到装完为止。设置页那个按钮要能给准话：
 * 「已经是最新的」和「有新版，正在换」是两句不同的话。
 */
export async function checkForUpdate(waitMs = 8000): Promise<boolean> {
  if (!reg) return false
  try { await reg.update() } catch { return updateReady() }
  const until = Date.now() + waitMs
  while (Date.now() < until) {
    if (updateReady()) return true
    if (!reg.installing && !reg.waiting) break
    await new Promise((r) => setTimeout(r, 250))
  }
  return updateReady()
}

export function initUpdates(): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  // file:// 下没有 SW，单文件版走的就是这条
  if (!location.protocol.startsWith('http')) return

  started = Date.now()
  hadController = !!navigator.serviceWorker.controller

  const mark = () => { touched = true }
  addEventListener('pointerdown', mark, { once: true, passive: true })
  addEventListener('keydown', mark, { once: true })

  navigator.serviceWorker.addEventListener('controllerchange', () => {
    // 第一次装 SW 也会触发一次，那次不能刷
    if (!hadController) return
    reload()
  })

  // updateViaCache: 'none' 是必须的。sw.js 本身也是一个普通文件，服务器给它
  // 发了 max-age——浏览器就会拿 HTTP 缓存里的旧 sw.js 来「检查更新」，
  // 于是永远检查不出更新。实测：不加这个，发现新版要等十几秒；
  // 缓存没过期的话根本发现不了
  navigator.serviceWorker
    .register('./sw.js', { scope: './', updateViaCache: 'none' })
    .then(track)
    .catch(() => {})

  // 从后台切回来时查一次。主屏 PWA 恢复不产生导航，这是唯一的机会
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void reg?.update().catch(() => {})
  })
  setInterval(() => { void reg?.update().catch(() => {}) }, POLL_MS)
}
