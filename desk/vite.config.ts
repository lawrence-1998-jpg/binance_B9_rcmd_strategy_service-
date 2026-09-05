import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { execSync } from 'node:child_process'

// 版本戳。手机上 Service Worker 会把旧代码缓存住，而人是看不出
// 自己停在哪一版的——修了 bug 说「已经修好了」，对面看到的还是旧的。
// 把它显式印在设置页里，出问题时一眼能对上。
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
      registerType: 'autoUpdate',
      includeAssets: ['icons/apple-touch-icon.png'],
      manifest: {
        name: '案头 Deskside',
        short_name: '案头',
        lang: 'zh-CN',
        description: '个人工作台：咨询 · 字节 · 我们俩',
        start_url: './index.html',
        scope: './',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#f5ead8',
        theme_color: '#f5ead8',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
        // 字体是跨域外链，不在 precache 范围内。不缓存的话离线打开
        // Caprasimo 会回退到 Georgia、IBM Plex Mono 回退到系统等宽，
        // 纪念日倒数那几个大数字会明显变样。这个 App 是要在飞机上、
        // 地铁里用的，离线是常态不是异常
        runtimeCaching: [
          {
            urlPattern: /^https:\/\/fonts\.googleapis\.com\//,
            handler: 'StaleWhileRevalidate',
            options: { cacheName: 'gfonts-css', cacheableResponse: { statuses: [0, 200] } },
          },
          {
            urlPattern: /^https:\/\/fonts\.gstatic\.com\//,
            handler: 'CacheFirst',
            options: {
              cacheName: 'gfonts-files',
              cacheableResponse: { statuses: [0, 200] },
              expiration: { maxEntries: 20, maxAgeSeconds: 60 * 60 * 24 * 365 },
            },
          },
        ],
      },
    }),
  ],
  define: {
    __BUILD_SHA__: JSON.stringify(sha),
    __BUILD_TIME__: JSON.stringify(built),
  },
  build: { outDir: 'dist', assetsInlineLimit: 8192 },
})
