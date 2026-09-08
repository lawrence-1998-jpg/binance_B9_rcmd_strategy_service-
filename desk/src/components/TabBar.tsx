import type { ReactNode } from 'react'
import { IcToday, IcWork, IcLife, IcPlus, IcWand } from './icons'

export type Route = 'today' | 'work' | 'life' | 'review'

/**
 * 底栏放哪四个，是按她真正在用什么排的，不是按功能对称排的。
 *
 * Prompt 管理器上了底栏、「复盘」下去了 —— 她原话是「突出保留 prompt 管理器」，
 * 而真正的突出是**在任何一屏都一步可达**，不是首页上摆一张卡。
 * 复盘没有被删：首页有一条常驻入口（以前只在傍晚出现，现在全天在），
 * 内容一条没少。
 */
type Slot = { key: Route | 'prompt'; label: string; icon: ReactNode }
const TABS: Slot[] = [
  { key: 'today', label: '今日', icon: <IcToday /> },
  { key: 'work', label: '工作', icon: <IcWork /> },
  { key: 'life', label: '生活', icon: <IcLife /> },
  { key: 'prompt', label: 'Prompt', icon: <IcWand /> },
]

/** 4 个 tab + 正中央凸起的速记键。中央位是拇指最省力的位置。 */
export function TabBar({
  route, onGo, onCapture, onPrompt, promptOn,
}: {
  route: Route
  onGo: (r: Route) => void
  onCapture: () => void
  onPrompt: () => void
  promptOn: boolean
}) {
  const hit = (t: Slot) => (t.key === 'prompt' ? promptOn : route === t.key)
  const go = (t: Slot) => (t.key === 'prompt' ? onPrompt() : onGo(t.key as Route))
  return (
    <nav className="tabbar" aria-label="主导航">
      <div className="tabbar-in">
        {TABS.slice(0, 2).map((t) => (
          <button key={t.key} type="button" className={`tab${hit(t) ? ' on' : ''}`}
            onClick={() => go(t)} aria-current={hit(t) ? 'page' : undefined}>
            {t.icon}<span>{t.label}</span>
          </button>
        ))}
        <button type="button" className="cap" onClick={onCapture} aria-label="记一笔">
          <IcPlus />
        </button>
        {TABS.slice(2).map((t) => (
          <button key={t.key} type="button" className={`tab${hit(t) ? ' on' : ''}`}
            onClick={() => go(t)} aria-current={hit(t) ? 'page' : undefined}>
            {t.icon}<span>{t.label}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}
