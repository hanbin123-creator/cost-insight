import { describe, expect, it } from 'vitest'
import { parseFocus, parseHash, ROUTES } from '../router'

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

describe('A11 内容级锚点（?focus=）解析', () => {
  it('解析 focus 锚点', () => {
    expect(parseFocus('#/dashboard?focus=dashboard:heatmap')).toBe('dashboard:heatmap')
  })
  it('focus 做 URL 解码（知识库文档名含中文/冒号）', () => {
    const a = `kb:doc:${encodeURIComponent('产品配方文档_银黄口服液.txt')}`
    expect(parseFocus(`#/kb?focus=${a}`)).toBe('kb:doc:产品配方文档_银黄口服液.txt')
  })
  it('无 focus 或空值回 null', () => {
    expect(parseFocus('#/kb')).toBeNull()
    expect(parseFocus('#/kb?from=alert')).toBeNull()
  })
  it('focus 不影响路由名解析', () => {
    expect(parseHash('#/dashboard?focus=dashboard:heatmap')).toBe('dashboard')
  })
})
