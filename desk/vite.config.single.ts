import { defineConfig } from 'vite'
import { execSync } from 'node:child_process'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

/**
 * 自包含单文件构建：JS / CSS / 图标全部内联进一个 .html。
 * 双击就能用，不需要任何服务器 —— 桌面上最省事的一条路。
 *
 * 关键：产物必须是**传统脚本**（iife），不能是 ES module。
 * 内联的 <script type="module"> 在没有 allow-same-origin 的沙箱 iframe 里
 * 根本不执行（各种网页预览器就是这么嵌的），结果是一片白。
 * 所以这里打成 iife，再由 postbuild 去掉 type="module"。
 */

const sha = (() => {
  try { return execSync('git rev-parse --short HEAD').toString().trim() } catch { return 'dev' }
})()
const built = new Date().toISOString().slice(0, 16).replace('T', ' ')

export default defineConfig({
  define: {
    __BUILD_SHA__: JSON.stringify(sha),
    __BUILD_TIME__: JSON.stringify(built),
  },
  base: './',
  // removeViteModuleLoader 不能开：iife 下入口脚本本身会被当成 module loader 删掉，
  // 产出一个空 <script> 的白屏页面（已经踩过）
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: 'dist-single',
    target: 'es2019',
    modulePreload: false,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: { output: { format: 'iife', inlineDynamicImports: true } },
  },
})
