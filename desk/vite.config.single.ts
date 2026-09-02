import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

/**
 * 自包含单文件构建：JS / CSS / 图标全部内联进一个 .html。
 * 双击就能用，不需要任何服务器 —— 桌面上最省事的一条路。
 * 代价：没有 service worker（不需要，本来就没有网络请求）。
 */
export default defineConfig({
  base: './',
  plugins: [react(), viteSingleFile({ removeViteModuleLoader: true })],
  build: {
    outDir: 'dist-single',
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
})
