import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { execSync } from 'node:child_process'

// 版本戳。手机上 Service Worker 会把旧代码缓存住，而人是看不出
// 自己停在哪一版的——修了 bug 说「已经修好了」，对面看到的还是旧的。
// 印在首页最底下，出问题时一眼能对上。
const sha = (() => {
  try { return execSync('git rev-parse --short HEAD').toString().trim() } catch { return 'dev' }
})()
const built = new Date().toISOString().slice(0, 16).replace('T', ' ')

// base './' 让 dist/index.html 双击也能直接打开（桌面快捷方式用）
export default defineConfig({
  base: './',
  plugins: [
    react(),
    VitePWA({
      // prompt 而不是 autoUpdate：autoUpdate 会 skipWaiting，新 SW 抢先接管，
      // 页面却还跑着旧代码——实测的结果是「打开一次还是旧版，开第二次才换」。
      // 换成 prompt 后新版装好了先等着，什么时候上位由 lib/update.ts 决定
      registerType: 'prompt',
      injectRegister: null,
      includeAssets: ['icons/apple-touch-icon.png'],
      manifest: {
        name: '随手 · 贴进来，拿走 Prompt',
        short_name: '随手',
        lang: 'zh-CN',
        description: '复制了什么就贴进来，自动拼好结构化的 AI Prompt，一下复制走。',
        start_url: './index.html',
        scope: './',
        display: 'standalone',
        orientation: 'any',
        background_color: '#f4f2ed',
        theme_color: '#f4f2ed',
        // 安卓上装到桌面之后，在任何 App 里点「分享」都能直接丢进来（App.tsx 读 ?text=）
        share_target: {
          action: './index.html',
          method: 'GET',
          params: { title: 'title', text: 'text', url: 'url' },
        },
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // 新 SW 只在收到 SKIP_WAITING 后才上位（prompt 模式），
        // 但上位那一刻必须立刻接管已经开着的页面。没有 clientsClaim 就没有
        // controllerchange，而 controllerchange 是 lib/update.ts 唯一认的信号
        // ——换版本会永远卡在「正在换……」
        clientsClaim: true,
        skipWaiting: false,
        // 装完之后飞机上、地铁里打开也能用 —— 它本来就不需要网
        globPatterns: ['**/*.{js,css,html,png,svg}'],
      },
    }),
  ],
  define: {
    __BUILD_SHA__: JSON.stringify(sha),
    __BUILD_TIME__: JSON.stringify(built),
  },
  build: { outDir: 'dist', assetsInlineLimit: 8192 },
})
