/**
 * 把 docs/playbook/lawrence-prompt-list.md 解析成 src/data/prompts.json。
 * 一份来源：改 md → 重新构建 → app 里就更新，绝不在代码里复制第二份。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.join(root, '../docs/playbook/lawrence-prompt-list.md')
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

const out = {
  source: 'docs/playbook/lawrence-prompt-list.md',
  generatedAt: new Date().toISOString().slice(0, 10),
  items,
}
fs.mkdirSync(path.dirname(OUT), { recursive: true })
fs.writeFileSync(OUT, JSON.stringify(out, null, 2) + '\n')

const byCat = items.reduce((m, i) => ({ ...m, [i.cat + '. ' + i.catName]: (m[i.cat + '. ' + i.catName] ?? 0) + 1 }), {})
console.log(`解析出 ${items.length} 条 prompt：`, JSON.stringify(byCat, null, 0))
