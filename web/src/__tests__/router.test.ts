import { describe, expect, it } from 'vitest'
import { parseHash, ROUTES } from '../router'

describe('hash 路由解析（确定性：空/未知一律回 dashboard）', () => {
  it('空 hash 与根路径回 dashboard', () => {
    expect(parseHash('')).toBe('dashboard')
    expect(parseHash('#')).toBe('dashboard')
    expect(parseHash('#/')).toBe('dashboard')
  })
  it('五个合法路由各自解析', () => {
    for (const r of ROUTES) expect(parseHash(`#/${r}`)).toBe(r)
  })
  it('未知路由回 dashboard 而不抛错', () => {
    expect(parseHash('#/nonexistent')).toBe('dashboard')
    expect(parseHash('#/dashboard/extra')).toBe('dashboard')
  })
  it('忽略查询串', () => {
    expect(parseHash('#/kb?from=alert')).toBe('kb')
  })
})
