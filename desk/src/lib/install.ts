/**
 * 装到主屏幕这件事，在 iOS 上不是「锦上添花」，而是数据能不能活下来的前提。
 *
 * 两条查实的规则（来源见下），合起来构成一个很容易踩的坑：
 *
 * 1. **Safari 标签页和主屏 App 是两份完全隔离的存储。**
 *    localStorage / IndexedDB / Service Worker 都不共享。在 Safari 里用了三天
 *    写的日记、存的照片，添加到主屏幕之后一条都看不到——那不是 bug，
 *    是 WebKit 刻意的隔离（「the website data of home screen web applications
 *    is kept isolated from Safari」）。
 *
 * 2. **只在 Safari 里用的话，7 天不打开就会被系统清掉。**
 *    ITP 的 7 天 script-writable storage 上限覆盖 localStorage 和 IndexedDB。
 *    主屏 App 有明确豁免（WebKit 为主屏 App 的一方域名在数据清除算法里加了
 *    例外），Safari 标签页没有。
 *
 * 而她只能先在 Safari 里打开这个链接——也就是说，**默认路径就是错的那条**。
 * 所以这个提示必须在她开始往里写东西之前出现，而不是出问题之后。
 *
 * 参考：
 * - WebKit「Full Third-Party Cookie Blocking and More」（7 天上限 + 主屏例外）
 * - WebKit「Updates to Storage Policy」
 */

/** 是不是从主屏幕图标启动的（而不是浏览器标签页） */
export function isStandalone(): boolean {
  try {
    if (window.matchMedia?.('(display-mode: standalone)').matches) return true
    // iOS Safari 用的是这个非标准属性，至今没有换
    return (navigator as unknown as { standalone?: boolean }).standalone === true
  } catch {
    return false
  }
}

export function isIOS(): boolean {
  try {
    const ua = navigator.userAgent
    // iPadOS 13+ 的 UA 伪装成 Mac，靠触摸点数区分
    return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)
  } catch {
    return false
  }
}

const KEY = 'deskside.installNotice'

export function noticeDismissed(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

export function dismissNotice() {
  try {
    localStorage.setItem(KEY, '1')
  } catch {
    /* 存不进去也不该崩；大不了下次再提示一遍 */
  }
}

/**
 * 该不该提示。
 *
 * 只在「iOS + 还在浏览器里」时提示：装好了就不提，安卓/桌面也不提
 * （那边两个入口共享同一份存储，没有这个坑）。
 */
export function shouldPromptInstall(): boolean {
  return isIOS() && !isStandalone() && !noticeDismissed()
}
