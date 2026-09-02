/**
 * 保存文件。同一份代码要在三种环境下都能用，所以分三级降级：
 *
 * 1. 托管在 claude.ai 上时：走平台的 downloads 能力（页面自己发起的下载会被拦）
 * 2. 双击打开的单文件 / 本地服务：普通 blob 下载
 * 3. 两条都不通：把 JSON 摊出来让人手动复制 —— 导出是数据安全的最后一道，
 *    宁可难看也不能静默失败
 */
export type SaveOutcome = 'saved' | 'declined' | 'manual'

interface DownloadsNS {
  save: (req: { filename: string; data: string }) => Promise<{ status: string }>
}
interface ClaudeGlobal {
  use?: (name: string) => Promise<unknown>
}

export async function saveFile(filename: string, data: string): Promise<SaveOutcome> {
  const claude = (window as unknown as { claude?: ClaudeGlobal }).claude

  if (typeof claude?.use === 'function') {
    let ns: DownloadsNS | null = null
    try {
      ns = (await claude.use('downloads')) as DownloadsNS | null
    } catch {
      ns = null
    }
    // 在这种环境里 blob 下载是不通的，所以拿不到能力就只能手动复制
    if (!ns) return 'manual'
    try {
      await ns.save({ filename, data })
      return 'saved'
    } catch (err) {
      const code = (err as { code?: string } | null)?.code
      if (code === 'declined') return 'declined'
      return 'manual'
    }
  }

  return blobDownload(filename, data)
}

function blobDownload(filename: string, data: string): SaveOutcome {
  try {
    const url = URL.createObjectURL(new Blob([data], { type: 'application/json' }))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    return 'saved'
  } catch {
    return 'manual'
  }
}
