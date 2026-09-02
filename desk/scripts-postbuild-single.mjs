/**
 * 单文件构建后处理。两件事：
 *
 * 1. 去掉 type="module"。产物已经是 iife（没有 import/export），去掉之后
 *    在「没有 allow-same-origin 的沙箱 iframe」里也能执行。不去掉的话，
 *    内联 module 脚本在那种环境下根本不运行，页面一片白 —— 已经踩过。
 *
 * 2. 顺手产出 artifact 版：剥掉 doctype/html/head/body 外壳，
 *    重排成「样式 → DOM → 脚本」，供只接受 body 片段的托管环境使用。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))
const src = path.join(root, 'dist-single/index.html')
let html = fs.readFileSync(src, 'utf-8')

// --- 1. module → classic ---
// 幂等：允许对同一份产物重复运行（比如只想重新拷贝一次）
const moduleTags = html.match(/<script\b[^>]*\btype=["']module["'][^>]*>/g) ?? []
const alreadyDone = moduleTags.length === 0 && /<script>[\s\S]{50000,}<\/script>\s*<\/body>/.test(html)
if (moduleTags.length === 0 && !alreadyDone) {
  throw new Error('既没有 type="module" 脚本，也不像已处理过的产物 —— 构建配置可能变了')
}
html = html.replace(/<script\b[^>]*\btype=["']module["'][^>]*>/g, '<script>')

const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1])
const biggest = Math.max(0, ...inline.map((s) => s.length))
if (biggest < 50_000) {
  throw new Error(
    `最大的内联脚本只有 ${biggest} 字节，产物是空的。` +
    '常见原因：viteSingleFile 的 removeViteModuleLoader 在 iife 下会把入口脚本当成 loader 删掉。',
  )
}
if (inline.some((s) => /^\s*(?:import|export)\s/m.test(s))) {
  throw new Error('产物里还有 import/export，当不了传统脚本 —— 检查 rollup format 是否为 iife')
}

// 传统脚本没有 module 的隐式 defer，在 <head> 里会同步执行，
// 那时 #root 还没生成 → React #299。所以把内联脚本统一挪到 </body> 之前。
const moved = []
if (!alreadyDone) {
  html = html.replace(/<script>[\s\S]*?<\/script>/g, (tag) => { moved.push(tag); return '' })
}
// 必须用函数式替换：minified JS 里含 $& / $' 这类序列，
// 字符串式替换会把它们当成替换模式，产物会被悄悄改坏
if (moved.length) {
  const tail = moved.join('\n') + '\n</body>'
  html = html.replace('</body>', () => tail)
  if (html.indexOf('id="root"') > html.indexOf(moved[0])) {
    throw new Error('脚本仍排在 #root 之前，挪动失败')
  }
}

fs.writeFileSync(src, html)
const outDir = path.join(root, '../web/desk')
fs.mkdirSync(outDir, { recursive: true })
fs.writeFileSync(path.join(outDir, 'deskside-standalone.html'), html)

// --- 2. artifact 版 ---
const head = html.match(/<head>([\s\S]*?)<\/head>/)?.[1] ?? ''
let body = html.match(/<body>([\s\S]*?)<\/body>/)?.[1] ?? ''

const grab = (src_, re) => src_.match(re) ?? []
const styleLinks = grab(head, /<link\b[^>]*rel=["']stylesheet["'][^>]*>/g)
const styles = grab(head, /<style[\s\S]*?<\/style>/g)
const title = head.match(/<title>[\s\S]*?<\/title>/)?.[0] ?? '<title>案头 Deskside</title>'

// 脚本必须排在 #root 之后，React 一挂载就找它
const bodyScripts = grab(body, /<script[\s\S]*?<\/script>/g)
body = body.replace(/<script[\s\S]*?<\/script>/g, '')

const artifact = [title, ...styleLinks, ...styles, body.trim(), ...bodyScripts]
  .filter(Boolean)
  .join('\n')

if (!/<div id="root">/.test(artifact)) throw new Error('artifact 版里没有 #root，提取逻辑坏了')
fs.writeFileSync(path.join(root, 'dist-single/artifact.html'), artifact + '\n')

console.log(
  `postbuild ok — 单文件 ${(html.length / 1024).toFixed(0)}KB，` +
  `artifact 版 ${(artifact.length / 1024).toFixed(0)}KB，` +
  (alreadyDone ? '（产物已是处理过的，只做了拷贝）' : `转换了 ${moduleTags.length} 个 module 脚本`),
)
