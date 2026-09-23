/**
 * 假的 claude.ai 运行时：在浏览器里装一个 window.claude，让测试能在本地把
 * 「在 claude.ai 里打开」那条路完整走一遍。
 *
 *   sample      —— 「问一问」：按提示里的卡片回答，带 [编号]，分几段流出来（onText）。
 *   sample.json —— 假 Claude。按原文里的关键词回一张固定的卡；带图就当读截图；
 *                  window.__mock.fail = 'not_granted' | 'rate_limited' | 'invalid_json' … 让它按那种方式失败。
 *                  window.__mock.calls 记着每一次调用（带 modelTier），测试拿来核对。
 *   db          —— 假数据库。路径、文档奇偶、update 必须先存在、onSnapshot 推送，
 *                  都照着 db.d.ts 的约定来；数据存在 sessionStorage，刷新后还在。
 *   user        —— 固定的 id。
 *
 * 用法：page.addInitScript({ path: 'test/mock-claude.js' })
 */
(() => {
  const M = (window.__mock = window.__mock || { fail: null, askFail: null, noImages: false, delay: 350, calls: [], asks: [], writes: [] })
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

  // 读截图：图里「写着」一条报价
  const SHOT = { raw: '报价单\n年费版 ¥36,000/年（含 20 席）\n有效期至 10 月 15 日', kind: 'data', title: '年费报价截图', summary: '20 席年费 3.6 万，10 月 15 日前有效。', fields: [{ label: '年费', value: '¥36,000/年' }, { label: '有效期', value: '10 月 15 日' }], todos: [], tags: ['报价'], prompt: '帮我判断这份报价贵不贵。' }

  async function json(input, opts = {}) {
    const images = opts.images ? [].concat(opts.images) : []
    M.calls.push({ input, tier: opts.modelTier ?? 'default', cache: opts.cache, images: images.length, imageTypes: images.map((b) => b.type) })
    await new Promise((r) => setTimeout(r, M.delay))
    if (M.fail) throw { code: M.fail, message: 'mock ' + M.fail }
    if (images.length) return JSON.parse(JSON.stringify(SHOT))
    const raw = String(input).split('<<<').pop() || ''
    const hit = CARDS.find(([re]) => re.test(raw))
    return JSON.parse(JSON.stringify(hit ? hit[1] : FALLBACK))
  }

  // 「问一问」：从提示里的卡片找沾边的那张，照着规定格式回答（带 [编号]），分几段流出来
  async function ask(input, opts = {}) {
    M.asks.push({ input, cache: opts.cache })
    const text = String(input)
    const q = (text.match(/我的问题：(.*)$/s) || [])[1] || ''
    const lines = [...text.matchAll(/^\[(\d+)\] (.+)$/gm)]
    const words = q.replace(/[？?的是多少哪些有吗呢]/g, ' ').split(/\s+/).filter((w) => w.length >= 2)
    const hit = lines.find(([, , l]) => words.some((w) => l.includes(w)))
    const answer = M.askFail ? '' : hit ? `找到了：${hit[2].split('｜')[1]}。电话是 138 1234 5678 [${hit[1]}]。` : '你收的东西里没有这个。'
    const chunks = answer.match(/.{1,8}/gs) || []
    let so = ''
    for (const c of chunks) {
      await new Promise((r) => setTimeout(r, 60))
      if (opts.signal?.aborted) throw { code: 'cancelled', message: 'mock cancelled', text: so || undefined }
      so += c
      opts.onText?.({ text: so, delta: c })
    }
    if (M.askFail) throw { code: M.askFail, message: 'mock ' + M.askFail }
    return { text: so, truncated: false, modelTierApplied: 'default' }
  }
  const limits = async () => ({ maxPromptBytes: 65536, ...(M.noImages ? {} : { images: { maxCount: 5, maxInputBytes: 20e6, mediaTypes: ['image/jpeg', 'image/png', 'image/webp', 'image/gif'] } }) })
  const sample = Object.assign(ask, { json, limits })

  const user = Object.freeze({ id: async () => 'u_test', isOwner: async () => true, canEdit: async () => true, can: async () => true })

  window.claude = Object.freeze({
    use: async (name) => {
      await new Promise((r) => setTimeout(r, 30))
      if (M.off && M.off.includes(name)) return null
      return { sample, db, user }[name] ?? null
    },
  })
})()
