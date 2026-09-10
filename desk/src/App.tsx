import { useEffect, useState } from 'react'
import { TabBar, type Route } from './components/TabBar'
import { Toast, useToast, ConfirmDialog, UpdatePill, RescueNotice } from './components/ui'
import { onPersistFail } from './lib/store'
import { Today } from './screens/Today'
import { Work } from './screens/Work'
import { Life } from './screens/Life'
import { Review } from './screens/Review'
import { Capture } from './screens/Capture'
import { Settings } from './screens/Settings'
import { Prompts } from './screens/Prompts'

const ROUTES: Route[] = ['today', 'work', 'life', 'review']
type Sheet = 'capture' | 'settings' | 'prompts' | null

function readHash(): Route {
  const r = location.hash.replace(/^#\/?/, '').split(/[?&]/)[0] as Route
  return ROUTES.includes(r) ? r : 'today'
}

export function App() {
  const [route, setRoute] = useState<Route>(readHash)
  const [sheet, setSheet] = useState<Sheet>(null)
  const [storageBroken, setStorageBroken] = useState(false)
  const toast = useToast()

  // 写盘失败必须冒到界面上。这是本日记：界面更新了但一个字没落盘，
  // 用户是察觉不到的，直到某天打开发现全没了
  useEffect(() => onPersistFail(setStorageBroken), [])

  /**
   * 冷启动时先把 hash 里挂着的 `?sheet=…` 抹掉。
   *
   * 浮层状态只在 hashchange 里读，**初次挂载不读** —— 所以 App 被系统杀掉时
   * 如果正开着速记（hash 停在 `#/today?sheet=capture`），从桌面图标重开就是：
   * 屏幕上没有浮层，而 URL 说有。
   *
   * 光是对不上还不算什么，真正咬人的是下一步：这时候点 ＋ 开速记，
   * `location.hash` 要写的值**跟现在一模一样**，赋值不触发跳转、
   * history 里不会多出一格；而 closeSheet 走的是 `history.back()`，
   * 于是那一下弹掉的是 App 自己 —— 实测直接落到 about:blank。
   * 主屏 PWA 是 standalone 窗口，没有浏览器返回键，她只能杀掉重进。
   *
   * 抹掉就行，不用把浮层恢复出来：草稿本来就没存，恢复出来也是个空壳，
   * 而「重开 App 弹出一个空速记框」比直接回到今日更奇怪。
   * 用 replaceState：不触发 hashchange，也不往 history 里加东西。
   */
  useEffect(() => {
    if (location.hash.includes('sheet=')) {
      history.replaceState(null, '', `#/${readHash()}`)
    }
  }, [])

  /**
   * 自己写的 hash 路由：五个屏不值得引一个路由库，
   * 而且 hash 路由在 file:// 下也能用（桌面快捷方式直接打开 dist/index.html）。
   *
   * 覆盖层（速记 / 设置 / Prompt）开的时候会往 history 里塞一格。
   * 不塞的话，手势返回会直接退到上一个路由——实测在「今日」开速记再返回，
   * 人会莫名其妙落到「复盘」屏。而手机上关闭一个全屏浮层，
   * 手势返回就是最顺手的那个动作，不能不接。
   */
  useEffect(() => {
    const on = () => {
      const h = location.hash
      const isSheet = h.includes('sheet=')
      if (isSheet) {
        const m = h.match(/sheet=(\w+)/)
        setSheet((m?.[1] as Sheet) ?? null)
      } else {
        setSheet(null)
      }
      setRoute(readHash())
    }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  function go(r: Route) {
    location.hash = `#/${r}`
    setRoute(r)
    setSheet(null)
    window.scrollTo({ top: 0 })
  }

  function openSheet(k: Exclude<Sheet, null>) {
    if (sheet) return
    location.hash = `#/${route}?sheet=${k}`
    setSheet(k)
  }

  function closeSheet() {
    // 用 back 而不是直接改 hash：这样 history 里不会越堆越多，
    // 「关闭」和手势返回走的也是同一条路
    if (location.hash.includes('sheet=')) history.back()
    else setSheet(null)
  }

  return (
    <>
      {storageBroken && (
        <div className="storage-warn" role="alert">
          存不进去了 —— 可能是存储满了，或浏览器在无痕模式。
          <strong>现在改的东西关掉页面就会没。</strong>
        </div>
      )}

      <RescueNotice toast={toast.show} />

      <main className="app">
        {route === 'today' && <Today go={go} onCapture={() => openSheet('capture')} onPromptTool={() => openSheet('prompts')} toast={toast.show} />}
        {route === 'work' && <Work toast={toast.show} onPromptTool={() => openSheet('prompts')} />}
        {route === 'life' && <Life toast={toast.show} />}
        {route === 'review' && <Review go={go} onSettings={() => openSheet('settings')} toast={toast.show} />}
      </main>

      <TabBar route={route} onGo={go} onCapture={() => openSheet('capture')}
        onPrompt={() => openSheet('prompts')} promptOn={sheet === 'prompts'} />

      {sheet === 'capture' && <Capture onClose={closeSheet} toast={toast.show} />}
      {sheet === 'settings' && <Settings onClose={closeSheet} toast={toast.show} />}
      {sheet === 'prompts' && <Prompts onClose={closeSheet} toast={toast.show} />}
      <ConfirmDialog />
      <UpdatePill />
      <Toast text={toast.text} />
    </>
  )
}
