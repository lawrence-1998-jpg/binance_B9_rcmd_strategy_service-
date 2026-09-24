/**
 * 假的 api.anthropic.com：接住页面发出去的请求，按关键词回一张固定的卡。
 * 测试里从来不碰真网络，也不需要真 Key。
 *
 *   const api = await mockAnthropic(ctx)
 *   api.fail = 'bad_key' | 'rate_limited' | 'overloaded' | 'no_credit' | 'offline' | 'refusal' | null
 *   api.delay = 400          // 每个请求等多久再回（测「在整理」那一下）
 *   api.calls                // 每个请求：{ path, method, key, beta, body, hasImage, imageType, prompt, stream }
 *
 * 形状照着 Messages API：非流式回 BetaMessage JSON；流式回 SSE。
 * 页面是跨域请求，所以预检（OPTIONS）和每个响应都带 CORS 头 —— 跟真接口一样
 */

// 按原文里的关键词给卡（跟 examples.ts 的三张示例对得上）
const CARDS = [
  [/Traceback|KeyError/, { kind: 'code', title: '流水线 KeyError', summary: '配置里缺 source 字段，run_pipeline 第 37 行取值时报错。', fields: [{ label: '文件', value: '/app/run_pipeline.py' }, { label: '行号', value: '37' }, { label: '错误', value: "KeyError: 'source'" }], todos: ['检查配置文件里的 source 字段'], tags: ['报错'], prompt: '帮我排查这个 KeyError：最可能的原因和修法。' }],
  [/王总|周五|国贸/, { kind: 'event', title: '王总的会改到周五', summary: '会议改到周五上午 10 点，地点国贸三期 B 座 1208。', fields: [{ label: '时间', value: '9月26日（周五）10:00' }, { label: '地点', value: '国贸三期 B 座 1208' }, { label: '参会', value: '王总、Linda' }, { label: '材料', value: '竞品分析' }], todos: ['带上竞品分析', '回复王总确认'], tags: ['客户会议'], prompt: '帮我回复王总，确认改到周五上午 10 点。' }],
  [/138|手机|邮箱|@/, { kind: 'contact', title: 'Lily Chen', summary: '增长策略负责人。', fields: [{ label: '姓名', value: 'Lily Chen' }, { label: '手机', value: '138 1234 5678' }, { label: '邮箱', value: 'lily.chen@example.com' }], todos: [], tags: ['人脉'], prompt: '帮我给 Lily 写一条初次联系的微信。' }],
]
const FALLBACK = { kind: 'note', title: '一条笔记', summary: '一段随手记下的内容。', fields: [], todos: [], tags: ['笔记'], prompt: '帮我提炼这段内容的要点。' }
// 读截图：图里「写着」一条报价
const SHOT = { raw: '报价单\n年费版 ¥36,000/年（含 20 席）\n有效期至 10 月 15 日', kind: 'data', title: '年费报价截图', summary: '20 席年费 3.6 万，10 月 15 日前有效。', fields: [{ label: '年费', value: '¥36,000/年' }, { label: '有效期', value: '10 月 15 日' }], todos: [], tags: ['报价'], prompt: '帮我判断这份报价贵不贵。' }

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-headers': '*',
  'access-control-allow-methods': 'GET, POST, OPTIONS',
  'access-control-expose-headers': '*',
}
const ERRORS = {
  bad_key: [401, 'authentication_error', 'invalid x-api-key'],
  no_access: [403, 'permission_error', 'Your API key does not have permission to use the specified resource.'],
  rate_limited: [429, 'rate_limit_error', 'Number of request tokens has exceeded your per-minute rate limit'],
  overloaded: [529, 'overloaded_error', 'Overloaded'],
  no_credit: [400, 'invalid_request_error', 'Your credit balance is too low to access the Anthropic API.'],
}

const message = (text, stop = 'end_turn') => ({
  id: 'msg_mock', type: 'message', role: 'assistant', model: 'claude-opus-5',
  content: stop === 'refusal' ? [] : [{ type: 'text', text }],
  stop_reason: stop, stop_sequence: null, stop_details: null,
  usage: { input_tokens: 100, output_tokens: 50 },
})

function sse(text, stop = 'end_turn') {
  const ev = (type, data) => `event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`
  const out = [ev('message_start', { message: { ...message(''), content: [], stop_reason: null } })]
  out.push(ev('content_block_start', { index: 0, content_block: { type: 'text', text: '' } }))
  for (const c of text.match(/.{1,8}/gs) ?? []) out.push(ev('content_block_delta', { index: 0, delta: { type: 'text_delta', text: c } }))
  out.push(ev('content_block_stop', { index: 0 }))
  out.push(ev('message_delta', { delta: { stop_reason: stop, stop_sequence: null }, usage: { output_tokens: 20 } }))
  out.push(ev('message_stop', {}))
  return out.join('')
}

/** 「问一问」：从提示里的卡片找沾边的那张，照规定格式回答（带 [编号]） */
function answer(prompt) {
  const q = (prompt.match(/我的问题：(.*)$/s) || [])[1] || ''
  const lines = [...prompt.matchAll(/^\[(\d+)\] (.+)$/gm)]
  const words = q.replace(/[？?的是多少哪些有吗呢]/g, ' ').split(/\s+/).filter((w) => w.length >= 2)
  const hit = lines.find(([, , l]) => words.some((w) => l.includes(w)))
  return hit ? `找到了：${hit[2].split('｜')[1]}。电话是 138 1234 5678 [${hit[1]}]。` : '你收的东西里没有这个。'
}

export async function mockAnthropic(ctx) {
  const api = { fail: null, delay: 350, calls: [] }
  await ctx.route('https://api.anthropic.com/**', async (route, req) => {
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS })
    const u = new URL(req.url())
    let body = null
    try { body = req.postDataJSON() } catch { /* GET */ }
    const content = body?.messages?.[0]?.content
    const blocks = typeof content === 'string' ? [{ type: 'text', text: content }] : content ?? []
    const img = blocks.find((b) => b.type === 'image')
    const call = {
      path: u.pathname, method: req.method(),
      key: req.headers()['x-api-key'], beta: req.headers()['anthropic-beta'] ?? '',
      body, stream: !!body?.stream,
      hasImage: !!img, imageType: img?.source?.media_type,
      prompt: blocks.filter((b) => b.type === 'text').map((b) => b.text).join('\n'),
    }
    api.calls.push(call)
    await new Promise((r) => setTimeout(r, api.delay))

    const fail = api.fail
    // 断网：请求直接失败（SDK 会当成连不上）
    if (fail === 'offline') return route.abort('internetdisconnected')
    if (fail && ERRORS[fail]) {
      const [status, type, msg] = ERRORS[fail]
      // x-should-retry: false —— 让 SDK 别自己重试，测试不用干等退避
      return route.fulfill({ status, headers: { ...CORS, 'content-type': 'application/json', 'x-should-retry': 'false' }, body: JSON.stringify({ type: 'error', error: { type, message: msg } }) })
    }

    if (u.pathname.startsWith('/v1/models/')) {
      return route.fulfill({ status: 200, headers: { ...CORS, 'content-type': 'application/json' }, body: JSON.stringify({ type: 'model', id: 'claude-opus-5', display_name: 'Claude Opus 5', created_at: '2026-01-01T00:00:00Z' }) })
    }
    if (u.pathname === '/v1/messages') {
      const stop = fail === 'refusal' ? 'refusal' : 'end_turn'
      if (call.stream) {
        return route.fulfill({ status: 200, headers: { ...CORS, 'content-type': 'text/event-stream' }, body: sse(stop === 'refusal' ? '' : answer(call.prompt), stop) })
      }
      const raw = call.prompt.split('<<<').pop() || ''
      const card = img ? SHOT : (CARDS.find(([re]) => re.test(raw))?.[1] ?? FALLBACK)
      return route.fulfill({ status: 200, headers: { ...CORS, 'content-type': 'application/json' }, body: JSON.stringify(message(JSON.stringify(card), stop)) })
    }
    return route.fulfill({ status: 404, headers: CORS, body: '{}' })
  })
  return api
}

/** 预先把 Key 放进这台「设备」：省得每条测试都去设置里填一遍 */
export const TEST_KEY = 'sk-ant-api03-test-0000000000000000000000000000'
export const presetKey = (ctx, key = TEST_KEY) => ctx.addInitScript((k) => { try { if (!sessionStorage.getItem('__keyset')) { localStorage.setItem('suishou.apikey', k); sessionStorage.setItem('__keyset', '1') } } catch {} }, key)
