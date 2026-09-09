/**
 * 一条命令跑完整套：构建 → 起静态服务 → 跑套件 → 收摊。
 *
 * 这套东西以前只活在一次会话的临时目录里 —— 也就是说我报的每一次「全绿」
 * 除了那次会话谁都复现不了，包括她自己和下一个 session。
 * 搬进仓库、并且能一条命令跑起来，这些断言才算数。
 *
 *   npm test              跑默认那批
 *   npm test -- pend flow2  只跑指定的几条
 */
import { spawn, spawnSync } from 'node:child_process'
import { createServer } from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const DIST = resolve(HERE, '..', 'dist')
const PORT = Number(process.env.DESK_PORT ?? 8765)

// 默认这一批：能在干净机器上跑起来、且真的出断言的。
// migrate 不在里面 —— 它要拿两个历史版本的构建产物当基线（见文件顶部），
// 那是本地专用的，缺基线时它会直接报错而不是悄悄跳过。
const DEFAULT = [
  'bottom', 'click', 'conf', 'fade', 'contrast-install', 'disabled', 'dlg', 'empty', 'exif', 'fills',
  'flow2', 'fonts', 'home', 'import-guard', 'install', 'ios', 'measure', 'measure-dark',
  'messy', 'nextstep', 'parts', 'pend', 'pill', 'pixel', 'pmstate', 'private', 'rescue',
  'review', 'shapes', 'single', 'stamp', 'swupdate', 'tabs', 'talk', 'tap', 'timeline',
  'verify', 'verify-backup', 'walk2', 'walk3', 'zoom',
]

const suites = process.argv.slice(2).filter((a) => !a.startsWith('-'))
const list = suites.length ? suites : DEFAULT

if (!process.env.DESK_URL) {
  console.log('· 构建…')
  const b = spawnSync('npm', ['run', 'build'], { cwd: resolve(HERE, '..'), stdio: 'inherit' })
  if (b.status !== 0) { console.error('构建就没过，后面不用跑了'); process.exit(2) }
}

const MIME = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.json':'application/json',
  '.webmanifest':'application/manifest+json', '.png':'image/png', '.svg':'image/svg+xml',
  '.woff2':'font/woff2', '.ico':'image/x-icon' }

let server = null
if (!process.env.DESK_URL) {
  await stat(join(DIST, 'index.html')).catch(() => {
    console.error(`dist 里没有 index.html（${DIST}）`); process.exit(2)
  })
  server = createServer(async (req, res) => {
    const p = join(DIST, decodeURIComponent(new URL(req.url, 'http://x').pathname))
    try {
      const buf = await readFile(p)
      res.writeHead(200, { 'content-type': MIME[extname(p)] ?? 'application/octet-stream',
                           'cache-control': 'no-store' })
      res.end(buf)
    } catch { res.writeHead(404); res.end('nope') }
  })
  await new Promise((ok, no) => {
    // 端口被占是最常见的一种失败，别甩一堆栈给人看
    server.once('error', (e) => {
      if (e.code === 'EADDRINUSE') {
        console.error(`端口 ${PORT} 被占了。换一个：DESK_PORT=8766 npm test`)
        console.error(`或者指着已经跑起来的那份：DESK_URL=http://127.0.0.1:${PORT}/index.html npm test`)
        process.exit(2)
      }
      no(e)
    })
    server.listen(PORT, '127.0.0.1', ok)
  })
  console.log(`· 服务起在 http://127.0.0.1:${PORT}`)
}

const code = await new Promise((r) => {
  const sh = spawn('bash', [join(HERE, 'run-all.sh'), ...list], { stdio: 'inherit', cwd: HERE })
  sh.on('exit', r)
})
server?.close()
process.exit(code ?? 1)
