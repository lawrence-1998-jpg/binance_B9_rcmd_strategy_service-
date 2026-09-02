import { useEffect, useState } from 'react'
import { getPhoto } from './media'

/** 把 IndexedDB 里的图片变成可用的 src，卸载时释放 object URL。 */
export function usePhotoURL(id: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let dead = false
    let made: string | null = null
    if (!id) { setUrl(null); return }
    void getPhoto(id).then((blob) => {
      if (dead || !blob) return
      made = URL.createObjectURL(blob)
      setUrl(made)
    })
    return () => {
      dead = true
      if (made) URL.revokeObjectURL(made)
    }
  }, [id])
  return url
}
