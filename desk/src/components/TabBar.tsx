import type { ReactNode } from 'react'
import { IcToday, IcWork, IcLife, IcReview, IcPlus } from './icons'

export type Route = 'today' | 'work' | 'life' | 'review'

const TABS: { key: Route; label: string; icon: ReactNode }[] = [
  { key: 'today', label: '今日', icon: <IcToday /> },
  { key: 'work', label: '工作', icon: <IcWork /> },
  { key: 'life', label: '生活', icon: <IcLife /> },
  { key: 'review', label: '复盘', icon: <IcReview /> },
]

/** 4 个 tab + 正中央凸起的速记键。中央位是拇指最省力的位置。 */
export function TabBar({ route, onGo, onCapture }: { route: Route; onGo: (r: Route) => void; onCapture: () => void }) {
  return (
    <nav className="tabbar" aria-label="主导航">
      <div className="tabbar-in">
        {TABS.slice(0, 2).map((t) => (
          <button key={t.key} type="button" className={`tab${route === t.key ? ' on' : ''}`}
            onClick={() => onGo(t.key)} aria-current={route === t.key ? 'page' : undefined}>
            {t.icon}<span>{t.label}</span>
          </button>
        ))}
        <button type="button" className="cap" onClick={onCapture} aria-label="记一笔">
          <IcPlus />
        </button>
        {TABS.slice(2).map((t) => (
          <button key={t.key} type="button" className={`tab${route === t.key ? ' on' : ''}`}
            onClick={() => onGo(t.key)} aria-current={route === t.key ? 'page' : undefined}>
            {t.icon}<span>{t.label}</span>
          </button>
        ))}
      </div>
    </nav>
  )
}
