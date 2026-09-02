import { useEffect, useState } from 'react'
import { TabBar, type Route } from './components/TabBar'
import { Toast, useToast } from './components/ui'
import { Today } from './screens/Today'
import { Work } from './screens/Work'
import { Life } from './screens/Life'
import { Review } from './screens/Review'
import { Capture } from './screens/Capture'
import { Settings } from './screens/Settings'
import { Prompts } from './screens/Prompts'

const ROUTES: Route[] = ['today', 'work', 'life', 'review']

function readHash(): Route {
  const r = location.hash.replace(/^#\/?/, '') as Route
  return ROUTES.includes(r) ? r : 'today'
}

export function App() {
  const [route, setRoute] = useState<Route>(readHash)
  const [capture, setCapture] = useState(false)
  const [settings, setSettings] = useState(false)
  const [promptTool, setPromptTool] = useState(false)
  const toast = useToast()

  // 自己写的 hash 路由：五个屏不值得引一个路由库，
  // 而且 hash 路由在 file:// 下也能用（桌面快捷方式直接打开 dist/index.html）
  useEffect(() => {
    const on = () => {
      setRoute(readHash())
      // 路由变了就收起覆盖层。正常操作时 sheet 盖住了 tab 栏点不到，
      // 但手势返回会绕过去，留下「换了页却还盖着一层」的状态
      setCapture(false)
      setSettings(false)
      setPromptTool(false)
    }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  function go(r: Route) {
    location.hash = `#/${r}`
    setRoute(r)
    window.scrollTo({ top: 0 })
  }

  return (
    <>
      <main className="app">
        {route === 'today' && <Today go={go} onCapture={() => setCapture(true)} toast={toast.show} />}
        {route === 'work' && <Work toast={toast.show} onPromptTool={() => setPromptTool(true)} />}
        {route === 'life' && <Life toast={toast.show} />}
        {route === 'review' && <Review go={go} onSettings={() => setSettings(true)} toast={toast.show} />}
      </main>

      <TabBar route={route} onGo={go} onCapture={() => setCapture(true)} />

      {capture && <Capture onClose={() => setCapture(false)} toast={toast.show} />}
      {settings && <Settings onClose={() => setSettings(false)} toast={toast.show} />}
      {promptTool && <Prompts onClose={() => setPromptTool(false)} toast={toast.show} />}
      <Toast text={toast.text} />
    </>
  )
}
