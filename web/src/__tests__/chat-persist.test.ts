// chatPersist 纯函数测试：序列化 / 裁剪 / 上下文标签 / 容错降级
import { describe, expect, it } from 'vitest'
import {
  CHAT_KEY,
  CHAT_MAX,
  CHAT_VERSION,
  clearChat,
  loadChat,
  needCtxTag,
  saveChat,
  trimChat,
  type PersistedMsg,
  type StorageLike,
} from '../chatPersist'

function fakeStorage(): StorageLike & { map: Map<string, string> } {
  const map = new Map<string, string>()
  return {
    map,
    getItem: (k) => (map.has(k) ? map.get(k)! : null),
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
  }
}

function msg(i: number, ctx = { product: '银黄口服液', month: '2026-05' }): PersistedMsg {
  return {
    role: i % 2 === 0 ? 'user' : 'agent',
    text: `m${i}`,
    view: { kind: 'clarify', text: `m${i}` },
    ctx,
    ts: 1700000000000 + i,
  }
}

describe('chatPersist 存档往返', () => {
  it('saveChat → loadChat 完整还原消息（含 ctx/ts）', () => {
    const s = fakeStorage()
    const list = [msg(0), msg(1, { product: '板蓝根颗粒', month: '2026-04' })]
    saveChat(list, s)
    const back = loadChat(s)
    expect(back).toHaveLength(2)
    expect(back[1].ctx).toEqual({ product: '板蓝根颗粒', month: '2026-04' })
    expect(back[1].view.kind).toBe('clarify')
  })

  it('存档带版本号与 savedAt；版本不符时读取为空', () => {
    const s = fakeStorage()
    saveChat([msg(0)], s)
    const raw = JSON.parse(s.map.get(CHAT_KEY)!)
    expect(raw.version).toBe(CHAT_VERSION)
    expect(typeof raw.savedAt).toBe('number')
    s.map.set(CHAT_KEY, JSON.stringify({ version: 999, messages: [msg(0)] }))
    expect(loadChat(s)).toEqual([])
  })
})

describe('trimChat 裁剪', () => {
  it(`超过 ${CHAT_MAX} 条时只留最近 ${CHAT_MAX} 条（裁最旧）`, () => {
    const many = Array.from({ length: CHAT_MAX + 10 }, (_, i) => msg(i))
    const kept = trimChat(many)
    expect(kept).toHaveLength(CHAT_MAX)
    expect(kept[0].text).toBe('m10')          // 最旧的 10 条被裁掉
    expect(kept[CHAT_MAX - 1].text).toBe(`m${CHAT_MAX + 9}`)
  })

  it('不足上限时原样返回（不改动入参）', () => {
    const few = [msg(0), msg(1)]
    expect(trimChat(few)).toHaveLength(2)
    expect(few).toHaveLength(2)
  })

  it('saveChat 落盘前自动裁剪', () => {
    const s = fakeStorage()
    saveChat(Array.from({ length: CHAT_MAX + 5 }, (_, i) => msg(i)), s)
    expect(loadChat(s)).toHaveLength(CHAT_MAX)
  })
})

describe('容错降级（隐私模式 / 损坏数据）', () => {
  it('无存储时读写清空全部静默为空操作', () => {
    expect(loadChat(null)).toEqual([])
    expect(() => saveChat([msg(0)], null)).not.toThrow()
    expect(() => clearChat(null)).not.toThrow()
  })

  it('JSON 损坏 / 结构非法时返回空数组', () => {
    const s = fakeStorage()
    s.map.set(CHAT_KEY, '{{{not json')
    expect(loadChat(s)).toEqual([])
    s.map.set(CHAT_KEY, JSON.stringify({ version: CHAT_VERSION, messages: 'oops' }))
    expect(loadChat(s)).toEqual([])
  })

  it('逐条校验：缺 ctx/view 的脏数据被丢弃，好数据保留', () => {
    const s = fakeStorage()
    const good = msg(0)
    const bad = { role: 'user', text: '脏' } // 无 view/ctx/ts
    s.map.set(CHAT_KEY, JSON.stringify({ version: CHAT_VERSION, messages: [good, bad] }))
    const back = loadChat(s)
    expect(back).toHaveLength(1)
    expect(back[0].text).toBe('m0')
  })

  it('setItem 抛异常（配额满）时 saveChat 静默', () => {
    const s = fakeStorage()
    s.setItem = () => { throw new Error('QuotaExceeded') }
    expect(() => saveChat([msg(0)], s)).not.toThrow()
  })

  it('clearChat 后读取为空', () => {
    const s = fakeStorage()
    saveChat([msg(0)], s)
    clearChat(s)
    expect(loadChat(s)).toEqual([])
  })

  it('保存空数组时直接删键（清空后不留空壳存档）', () => {
    const s = fakeStorage()
    saveChat([msg(0)], s)
    expect(s.map.has(CHAT_KEY)).toBe(true)
    saveChat([], s)
    expect(s.map.has(CHAT_KEY)).toBe(false)
  })
})

describe('needCtxTag 上下文标签判定', () => {
  it('产品或月份任一不同 → 需要标签', () => {
    expect(needCtxTag({ product: '板蓝根颗粒', month: '2026-05' }, '银黄口服液', '2026-05')).toBe(true)
    expect(needCtxTag({ product: '银黄口服液', month: '2026-04' }, '银黄口服液', '2026-05')).toBe(true)
  })

  it('完全一致 → 不需要标签；无 ctx → 不需要标签', () => {
    expect(needCtxTag({ product: '银黄口服液', month: '2026-05' }, '银黄口服液', '2026-05')).toBe(false)
    expect(needCtxTag(undefined, '银黄口服液', '2026-05')).toBe(false)
  })
})
