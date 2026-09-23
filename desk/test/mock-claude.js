/**
 * 假的 claude.ai 运行时：在浏览器里装一个 window.claude，让测试能在本地把
 * 「在 claude.ai 里打开」那条路完整走一遍。
 *
 *   sample.json —— 假 Claude。按原文里的关键词回一张固定的卡；
 *                  window.__mock.fail = 'not_granted' | 'rate_limited' | 'invalid_json' … 让它按那种方式失败。
 *                  window.__mock.calls 记着每一次调用（带 modelTier），测试拿来核对。
 *   db          —— 假数据库。路径、文档奇偶、update 必须先存在、onSnapshot 推送，
 *                  都照着 db.d.ts 的约定来；数据存在 sessionStorage，刷新后还在。
 *   user        —— 固定的 id。
 *
 * 用法：page.addInitScript({ path: 'test/mock-claude.js' })
 */
(() => {
  const M = (window.__mock = window.__mock || { fail: null, delay: 350, calls: [], writes: [] })
  const KEY = '__mockdb'
  const load = () => { try { return JSON.parse(sessionStorage.getItem(KEY) || '{}') } catch { return {} } }
  let docs = load()
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(docs)) } catch {} }
  const subs = new Set()
  const later = (fn, ms = 20) => setTimeout(fn, ms)
  const segs = (p) => p.split('/').filter(Boolean)

  function query(colPath, order, lim) {
    const q = {
      orderBy: (f, dir = 'asc') => query(colPath, { f, dir }, lim),
      limit: (n) => query(colPath, order, n),
      onSnapshot(next) {
        const run = () => {
          let rows = Object.entries(docs)
            .filter(([p]) => p.startsWith(colPath + '/') && segs(p).length === segs(colPath).length + 1)
            .map(([p, d]) => ({ id: p.split('/').pop(), exists: true, data: () => d, d }))
          if (order) rows.sort((a, b) => (order.dir === 'desc' ? -1 : 1) * ((a.d[order.f] ?? 0) - (b.d[order.f] ?? 0)))
          if (lim) rows = rows.slice(0, lim)
          next({ docs: rows, size: rows.length, empty: !rows.length })
        }
        subs.add(run)
        later(run)
        return () => subs.delete(run)
      },
    }
    return q
  }
  const emit = () => subs.forEach((f) => later(f, 5))

  function docRef(path) {
    if (segs(path).length % 2) throw new TypeError('document path needs an even number of segments: ' + path)
    return {
      id: path.split('/').pop(),
      path,
      async get() { const d = docs[path]; return { id: path.split('/').pop(), exists: !!d, data: () => d } },
      async set(d) { M.writes.push(['set', path]); docs[path] = JSON.parse(JSON.stringify(d)); save(); emit() },
      async update(d) {
        M.writes.push(['update', path])
        if (!docs[path]) throw { code: 'invalid_argument', message: 'update on missing doc' }
        docs[path] = { ...docs[path], ...JSON.parse(JSON.stringify(d)) }; save(); emit()
      },
      async delete() { M.writes.push(['delete', path]); delete docs[path]; save(); emit() },
      collection: (name) => colRef(path + '/' + name),
    }
  }
  function colRef(path) {
    if (segs(path).length % 2 === 0) throw new TypeError('collection path needs an odd number of segments: ' + path)
    const q = query(path)
    return { ...q, path, doc: (id) => docRef(path + '/' + (id || Math.random().toString(36).slice(2))) }
  }
  const db = Object.freeze({ doc: docRef, collection: colRef })

  // 假 Claude：按关键词给卡
  const CARDS = [
    [/Traceback|KeyError/, { kind: 'code', title: '流水线 KeyError', summary: '配置里缺 source 字段，run_pipeline 第 37 行取值时报错。', fields: [{ label: '文件', value: '/app/run_pipeline.py' }, { label: '行号', value: '37' }, { label: '错误', value: "KeyError: 'source'" }], todos: ['检查配置文件里的 source 字段'], tags: ['报错'], prompt: '帮我排查这个 KeyError：最可能的原因和修法。' }],
    [/王总|周五|国贸/, { kind: 'event', title: '王总的会改到周五', summary: '会议改到周五上午 10 点，地点国贸三期 B 座 1208。', fields: [{ label: '时间', value: '9月26日（周五）10:00' }, { label: '地点', value: '国贸三期 B 座 1208' }, { label: '参会', value: '王总、Linda' }, { label: '材料', value: '竞品分析' }], todos: ['带上竞品分析', '回复王总确认'], tags: ['客户会议'], prompt: '帮我回复王总，确认改到周五上午 10 点。' }],
    [/138|手机|邮箱|@/, { kind: 'contact', title: 'Lily Chen', summary: '增长策略负责人。', fields: [{ label: '姓名', value: 'Lily Chen' }, { label: '手机', value: '138 1234 5678' }, { label: '邮箱', value: 'lily.chen@example.com' }], todos: [], tags: ['人脉'], prompt: '帮我给 Lily 写一条初次联系的微信。' }],
  ]
  const FALLBACK = { kind: 'note', title: '一条笔记', summary: '一段随手记下的内容。', fields: [], todos: [], tags: ['笔记'], prompt: '帮我提炼这段内容的要点。' }

  async function json(input, opts = {}) {
    M.calls.push({ input, tier: opts.modelTier ?? 'default', cache: opts.cache })
    await new Promise((r) => setTimeout(r, M.delay))
    if (M.fail) throw { code: M.fail, message: 'mock ' + M.fail }
    const raw = String(input).split('<<<').pop() || ''
    const hit = CARDS.find(([re]) => re.test(raw))
    return JSON.parse(JSON.stringify(hit ? hit[1] : FALLBACK))
  }
  const sample = Object.assign(async (input, opts) => ({ text: JSON.stringify(await json(input, opts)), truncated: false }), { json })

  const user = Object.freeze({ id: async () => 'u_test', isOwner: async () => true, canEdit: async () => true, can: async () => true })

  window.claude = Object.freeze({
    use: async (name) => {
      await new Promise((r) => setTimeout(r, 30))
      if (M.off && M.off.includes(name)) return null
      return { sample, db, user }[name] ?? null
    },
  })
})()
