// Agent 抽屉消息持久化（方案 A：localStorage 本地存档）。
// 设计要点：
// - 只存可 JSON 序列化的消息体（role/text/view/intent/confidence/layer + ctx + ts）
// - 只保留最近 CHAT_MAX 条，超出裁最旧
// - 所有 localStorage 操作 try/catch：隐私模式 / 配额满时静默降级为"不持久化"，绝不影响对话主流程
// - 决策卡状态不持久化（每次打开抽屉重新向 /api/agent/decision 求值）

import type { ReplyView } from './agentCards'

export const CHAT_KEY = 'ci-agent-chat'
export const CHAT_MAX = 50
export const CHAT_VERSION = 1

export interface ChatCtx { product: string; month: string }

export interface PersistedMsg {
  role: 'user' | 'agent'
  text?: string
  view: ReplyView
  intent?: string
  confidence?: number
  layer?: string
  ctx: ChatCtx
  ts: number
}

export interface StorageLike {
  getItem(k: string): string | null
  setItem(k: string, v: string): void
  removeItem(k: string): void
}

// localStorage 在某些环境（隐私模式 / SSR / 测试）可能不存在或抛异常
function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

/** 裁剪到最近 CHAT_MAX 条（纯函数，不改动入参） */
export function trimChat<T>(list: T[], max = CHAT_MAX): T[] {
  return list.length > max ? list.slice(list.length - max) : list.slice()
}

/** 轻量校验一条持久化消息的结构完整性；缺关键字段即丢弃该条 */
function isValidMsg(m: unknown): m is PersistedMsg {
  if (!m || typeof m !== 'object') return false
  const v = m as Record<string, unknown>
  if (v.role !== 'user' && v.role !== 'agent') return false
  const view = v.view as Record<string, unknown> | undefined
  if (!view || typeof view !== 'object' || typeof view.kind !== 'string') return false
  const ctx = v.ctx as Record<string, unknown> | undefined
  if (!ctx || typeof ctx !== 'object') return false
  if (typeof ctx.product !== 'string' || typeof ctx.month !== 'string') return false
  if (typeof v.ts !== 'number') return false
  return true
}

/** 读取存档；任何异常（无存储 / JSON 损坏 / 版本不符）都返回空数组，不抛错 */
export function loadChat(storage: StorageLike | null = defaultStorage()): PersistedMsg[] {
  if (!storage) return []
  try {
    const raw = storage.getItem(CHAT_KEY)
    if (!raw) return []
    const data = JSON.parse(raw) as { version?: number; messages?: unknown[] }
    if (data.version !== CHAT_VERSION || !Array.isArray(data.messages)) return []
    return trimChat(data.messages.filter(isValidMsg))
  } catch {
    return []
  }
}

/** 写入存档（先裁剪再序列化）；空存档直接删键，避免清空后残留空壳；失败静默 */
export function saveChat(messages: PersistedMsg[], storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return
  try {
    const trimmed = trimChat(messages)
    if (!trimmed.length) {
      storage.removeItem(CHAT_KEY)
      return
    }
    const payload = { version: CHAT_VERSION, messages: trimmed, savedAt: Date.now() }
    storage.setItem(CHAT_KEY, JSON.stringify(payload))
  } catch {
    /* 配额满 / 隐私模式：静默，不打断对话 */
  }
}

/** 清空存档；失败静默 */
export function clearChat(storage: StorageLike | null = defaultStorage()): void {
  if (!storage) return
  try {
    storage.removeItem(CHAT_KEY)
  } catch {
    /* 静默 */
  }
}

/** 消息上下文与当前页面筛选不一致时需要显示灰色小标签 */
export function needCtxTag(msgCtx: ChatCtx | undefined, curProduct: string, curMonth: string): boolean {
  if (!msgCtx) return false
  return msgCtx.product !== curProduct || msgCtx.month !== curMonth
}
