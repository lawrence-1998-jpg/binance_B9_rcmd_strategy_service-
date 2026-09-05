/**
 * 把两份 md 解析成 src/data/prompts.json：
 *   lawrence-prompt-list.md  → items（完整的 prompt）
 *   lawrence-prompt-parts.md → parts（零件：叮嘱语 / 附录，挂在任何一条后面）
 *
 * 一份来源：改 md → 重新构建 → app 里就更新，绝不在代码里复制第二份。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.join(root, '../docs/playbook/lawrence-prompt-list.md')
const SRC_PARTS = path.join(root, '../docs/playbook/lawrence-prompt-parts.md')
const OUT = path.join(root, 'src/data/prompts.json')

if (!fs.existsSync(SRC)) {
  console.error('找不到 prompt 源文件：' + SRC)
  process.exit(1)
}

const md = fs.readFileSync(SRC, 'utf-8')
const lines = md.split('\n')

const items = []
let cat = null, catName = ''
let cur = null
let fence = false
let body = []
let note = []

function flush() {
  if (!cur) return
  const b = body.join('\n').trim()
  if (b) {
    items.push({
      id: cur.id,
      cat, catName,
      title: cur.title,
      body: b,
      note: note.join(' ').replace(/\s+/g, ' ').trim(),
    })
  }
  cur = null; body = []; note = []
}

for (const raw of lines) {
  const line = raw.replace(/\r$/, '')

  if (!fence) {
    const mCat = line.match(/^##\s+([A-Z])\.\s+(.+?)\s*$/)
    if (mCat) { flush(); cat = mCat[1]; catName = mCat[2]; continue }

    const mItem = line.match(/^###\s+([A-Z]\d+)\s*·\s*(.+?)\s*$/)
    if (mItem) { flush(); cur = { id: mItem[1], title: mItem[2] }; continue }

    if (/^##\s+/.test(line)) { flush(); cat = null; catName = ''; continue }
  }

  if (/^```/.test(line)) {
    fence = !fence
    continue
  }
  if (fence) { if (cur) body.push(line); continue }

  if (cur && /^>\s*/.test(line)) {
    note.push(line.replace(/^>\s*/, '').replace(/\*\*/g, ''))
  }
}
flush()

if (items.length === 0) {
  console.error('一条也没解析出来 —— md 的结构可能变了，检查 ## / ### / ``` 的写法')
  process.exit(1)
}

/**
 * 零件那份的结构比 prompt 简单：`## 类别` + `### 名字` + 代码块 + `>` 注。
 * 分开解析而不是塞进同一个状态机 —— 两种东西的格式各自演进，
 * 混在一起改一边就会碰坏另一边。
 */
function parseParts(md) {
  const out = []
  let kind = '', cur = null, fence = false, body = [], note = []
  const flush = () => {
    if (cur && body.join('\n').trim()) {
      out.push({ id: 'p' + (out.length + 1), kind, title: cur, body: body.join('\n').trim(), note: note.join(' ').replace(/\s+/g, ' ').trim() })
    }
    cur = null; body = []; note = []
  }
  for (const raw of md.split('\n')) {
    const line = raw.replace(/\r$/, '')
    if (!fence) {
      const mk = line.match(/^##\s+(叮嘱语|附录)\s*$/)
      if (mk) { flush(); kind = mk[1]; continue }
      const mi = line.match(/^###\s+(.+?)\s*$/)
      if (mi) { flush(); cur = mi[1]; continue }
    }
    if (/^```/.test(line)) { fence = !fence; continue }
    if (fence) { if (cur) body.push(line); continue }
    if (cur && /^>\s*/.test(line)) note.push(line.replace(/^>\s*/, '').replace(/\*\*/g, ''))
  }
  flush()
  return out
}

let parts = []
if (fs.existsSync(SRC_PARTS)) {
  parts = parseParts(fs.readFileSync(SRC_PARTS, 'utf-8'))
  if (parts.length === 0) {
    console.error('零件一条也没解析出来 —— 检查 lawrence-prompt-parts.md 的 ## / ### / ``` 写法')
    process.exit(1)
  }
} else {
  console.error('找不到零件源文件：' + SRC_PARTS)
  process.exit(1)
}

const out = {
  source: 'docs/playbook/lawrence-prompt-list.md',
  generatedAt: new Date().toISOString().slice(0, 10),
  items,
  parts,
}
fs.mkdirSync(path.dirname(OUT), { recursive: true })
fs.writeFileSync(OUT, JSON.stringify(out, null, 2) + '\n')

const byCat = items.reduce((m, i) => ({ ...m, [i.cat + '. ' + i.catName]: (m[i.cat + '. ' + i.catName] ?? 0) + 1 }), {})
console.log(`解析出 ${items.length} 条 prompt、${parts.length} 个零件：`, JSON.stringify(byCat, null, 0))
