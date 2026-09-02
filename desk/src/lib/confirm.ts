import { useEffect, useState } from 'react'

/**
 * 破坏性操作的二次确认。
 *
 * 这个 App 没有后端、没有回收站、没有撤销：删掉的纪念日、照片、
 * 手写的三句话，是真的没了。而删除按钮就贴在卡片右上角，
 * 有几个还只有 18px 高——在手机上误触是迟早的事。
 *
 * 所以凡是不可撤销的删除都要过这一道。**不用 window.confirm**：
 * 它在 iOS 主屏 PWA 里样式不受控，且会打断动画。
 *
 * 走模块级订阅而不是 React context，跟这套代码里 store 的做法保持一致——
 * 五个屏加一个 Provider 层不值当。
 */
export interface Ask {
  title: string
  detail?: string
  confirmLabel?: string
  onYes: () => void
}

let pending: Ask | null = null
const subs = new Set<() => void>()

function emit() { subs.forEach((f) => f()) }

/** 在任何地方调用：askConfirm({ title, detail, onYes }) */
export function askConfirm(a: Ask) {
  pending = a
  emit()
}

export function dismissConfirm() {
  pending = null
  emit()
}

export function useConfirm(): Ask | null {
  const [, bump] = useState(0)
  useEffect(() => {
    const f = () => bump((n) => n + 1)
    subs.add(f)
    return () => { subs.delete(f) }
  }, [])
  return pending
}
