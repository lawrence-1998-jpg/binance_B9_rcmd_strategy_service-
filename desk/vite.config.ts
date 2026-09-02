import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

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
      workbox: { globPatterns: ['**/*.{js,css,html,png,svg,woff2}'] },
    }),
  ],
  build: { outDir: 'dist', assetsInlineLimit: 8192 },
})
