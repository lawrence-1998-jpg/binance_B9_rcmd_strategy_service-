import { defineConfig } from 'vite'
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

// 版本戳在这里是固定的，不是提交号 + 构建时间。
// 仓库里签着一份这个产物，CI 会拿源码重新构建一遍、逐字节比对（不一致就红）——
// 要是把构建时间印进去，两次构建永远不一样，那条检查就永远是红的。
// 产物只取决于源码，才比得出「过没过期」。
export default defineConfig({
  define: {
    __BUILD_SHA__: JSON.stringify('offline'),
    __BUILD_TIME__: JSON.stringify('offline'),
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
