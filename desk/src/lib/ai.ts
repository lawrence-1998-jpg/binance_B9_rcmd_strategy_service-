import type Anthropic from '@anthropic-ai/sdk'
import { KINDS } from './card'

/**
 * 可选的 AI：她自己的 Claude API Key。默认关着。
 *
 *   不填 —— 什么都不出这台设备，card.ts 里的本地整理就是全部。
 *   填了 —— 收下的那一条（截图、提问也一样）从这台设备直接发给 api.anthropic.com，
 *           不经过任何别的服务器。Key 只存在这台设备的浏览器里，只出现在发给
 *           api.anthropic.com 的请求头里。test/private.mjs 把这两条变成会失败的检查。
 *
 * SDK 只在真要用的时候才加载：没填 Key 的人一个字节都不用多下。
 */

const KEY_SLOT = 'suishou.apikey'
export const MODEL = 'claude-opus-5'
/** Claude 的安全分类偶尔会误拒一条正常的东西：服务端自动换一个模型接着做，不用她重试 */
const BETAS = ['server-side-fallback-2026-07-01']

export function loadKey(): string {
  try { return localStorage.getItem(KEY_SLOT) ?? '' } catch { return '' }
}
export function saveKey(k: string): boolean {
  try { localStorage.setItem(KEY_SLOT, k.trim()); return true } catch { return false }
}
export function clearKey(): void {
  try { localStorage.removeItem(KEY_SLOT) } catch { /* 无痕模式：本来也没存上 */ }
}
export const looksLikeKey = (k: string) => /^sk-ant-[\w-]{16,}$/.test(k.trim())

/** 出错统一成几种她能看懂、能照着做的情况 */
export type AiErrCode =
  | 'bad_key' | 'no_access' | 'no_credit' | 'rate_limited' | 'overloaded' | 'offline'
  | 'too_large' | 'image_rejected' | 'refused' | 'truncated' | 'invalid_json' | 'cancelled' | 'failed'

export class AiError extends Error {
  constructor(public code: AiErrCode, msg: string = code) { super(msg) }
}

let sdk: Promise<typeof import('@anthropic-ai/sdk')> | null = null
const clients = new Map<string, Anthropic>()

async function client(key: string): Promise<Anthropic> {
  const hit = clients.get(key)
  if (hit) return hit
  sdk ??= import('@anthropic-ai/sdk')
  const { default: SDK } = await sdk
  // 浏览器里直连：Key 是她自己的、存在她自己设备上，不是网站的密钥，所以这里是对的用法
  const c = new SDK({ apiKey: key, dangerouslyAllowBrowser: true, maxRetries: 1, timeout: 90_000 })
  clients.clear()
  clients.set(key, c)
  return c
}

function classify(e: unknown, signal?: AbortSignal): AiError {
  if (e instanceof AiError) return e
  if (signal?.aborted) return new AiError('cancelled')
  const x = (e ?? {}) as { status?: number; name?: string; message?: string; error?: { error?: { type?: string; message?: string } } }
  const msg = `${x.error?.error?.message ?? ''} ${x.message ?? ''}`
  if (x.name === 'APIUserAbortError') return new AiError('cancelled')
  if (x.status === undefined && /Connection|Timeout|fetch/i.test(`${x.name} ${x.message}`)) return new AiError('offline')
  switch (x.status) {
    case 401: return new AiError('bad_key')
    case 403: return new AiError('no_access')
    case 413: return new AiError('too_large')
    case 429: return new AiError('rate_limited')
    case 400:
      if (/credit balance/i.test(msg)) return new AiError('no_credit')
      if (/image/i.test(msg)) return new AiError('image_rejected')
      if (/too long|too large|maximum|context/i.test(msg)) return new AiError('too_large')
      return new AiError('failed', msg)
    case 404: return new AiError('no_access')
  }
  if (typeof x.status === 'number' && x.status >= 500) return new AiError('overloaded')
  return new AiError('failed', msg)
}

/** Claude 回的卡片必须长这样（结构化输出：它只能按这个格式回，不会夹带别的话） */
function cardSchema(withRaw: boolean) {
  const str = { type: 'string' }
  return {
    type: 'object',
    additionalProperties: false,
    required: [...(withRaw ? ['raw'] : []), 'kind', 'title', 'summary', 'fields', 'todos', 'tags', 'prompt'],
    properties: {
      ...(withRaw ? { raw: str } : {}),
      kind: { type: 'string', enum: Object.keys(KINDS) },
      title: str,
      summary: str,
      fields: {
        type: 'array',
        items: { type: 'object', additionalProperties: false, required: ['label', 'value'], properties: { label: str, value: str } },
      },
      todos: { type: 'array', items: str },
      tags: { type: 'array', items: str },
      prompt: str,
    },
  }
}

type ImageType = 'image/jpeg' | 'image/png' | 'image/gif' | 'image/webp'

/**
 * 整理一条。image：截图的 data URL（读图时 prompt 里不带原文）。
 * effort：平时 low（几秒就回）；她点「重新整理」时 medium，想得仔细些。
 * 回来的是没核过的对象 —— 调用方一律再过一遍 fromAi()。
 */
export async function organize(
  key: string, prompt: string, image?: string, effort: 'low' | 'medium' = 'low', signal?: AbortSignal,
): Promise<unknown> {
  try {
    const c = await client(key)
    const img = image?.match(/^data:(image\/(?:jpeg|png|gif|webp));base64,(.+)$/)
    const res = await c.beta.messages.create({
      model: MODEL,
      max_tokens: 8000,
      betas: BETAS,
      fallbacks: 'default',
      output_config: { effort, format: { type: 'json_schema', schema: cardSchema(!!img) } },
      messages: [{
        role: 'user',
        content: [
          ...(img ? [{ type: 'image' as const, source: { type: 'base64' as const, media_type: img[1] as ImageType, data: img[2] } }] : []),
          { type: 'text' as const, text: prompt },
        ],
      }],
    }, { signal })
    if (res.stop_reason === 'refusal') throw new AiError('refused')
    if (res.stop_reason === 'max_tokens') throw new AiError('truncated')
    const text = res.content.map((b) => (b.type === 'text' ? b.text : '')).join('')
    try { return JSON.parse(text) } catch { throw new AiError('invalid_json') }
  } catch (e) {
    throw classify(e, signal)
  }
}

/** 问一问：边写边显示 */
export async function ask(key: string, prompt: string, onText: (text: string) => void, signal?: AbortSignal): Promise<string> {
  try {
    const c = await client(key)
    const stream = c.beta.messages.stream({
      model: MODEL,
      max_tokens: 4000,
      betas: BETAS,
      fallbacks: 'default',
      output_config: { effort: 'low' },
      messages: [{ role: 'user', content: prompt }],
    }, { signal })
    stream.on('text', (_delta, snapshot) => onText(snapshot))
    const msg = await stream.finalMessage()
    const text = msg.content.map((b) => (b.type === 'text' ? b.text : '')).join('')
    if (msg.stop_reason === 'refusal') throw Object.assign(new AiError('refused'), { text })
    return text
  } catch (e) {
    const err = classify(e, signal)
    const partial = (e as { text?: string })?.text
    throw partial ? Object.assign(err, { text: partial }) : err
  }
}

/** 设置里「保存并测试」：查一下这个模型它能不能用（不花钱） */
export async function check(key: string): Promise<void> {
  try {
    const c = await client(key)
    await c.models.retrieve(MODEL)
  } catch (e) {
    throw classify(e)
  }
}

/** 卡片上那一行说明：出了什么事、她能做什么 */
export function noteFor(code: AiErrCode): string {
  switch (code) {
    case 'bad_key': return 'API Key 不对或已失效 —— 去「设置」里换一个，再点「重新整理」'
    case 'no_access': return '这个 API Key 用不了 Claude —— 去「设置」里检查一下'
    case 'no_credit': return 'API 账户余额不足，先做了基础整理 —— 充值后点「重新整理」'
    case 'rate_limited': return 'Claude 这会儿忙，过一会儿点「重新整理」'
    case 'overloaded': return 'Claude 那边暂时出了点问题，过一会儿点「重新整理」'
    case 'offline': return '没连上网，先做了基础整理 —— 有网了点「重新整理」'
    case 'too_large': return '太长了，Claude 一次读不完 —— 可以分几段收'
    case 'image_rejected': return '这张图 Claude 读不了，换一张试试'
    case 'refused': return 'Claude 没接这条，先做了基础整理'
    default: return '这次没整理成，点「重新整理」再试'
  }
}
