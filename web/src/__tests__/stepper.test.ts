// stepper 纯函数测试：月份步进与端点禁用态（顶栏切换器方案三）
import { describe, expect, it } from 'vitest'
import { canStep, stepMonth } from '../stepper'

const MONTHS = ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06']

describe('stepMonth 相邻月步进', () => {
  it('正常前进/后退', () => {
    expect(stepMonth(MONTHS, '2026-02', 1)).toBe('2026-03')
    expect(stepMonth(MONTHS, '2026-02', -1)).toBe('2026-01')
  })
  it('端点钳制：首月不可再退，末月不可再进', () => {
    expect(stepMonth(MONTHS, '2026-01', -1)).toBe('2026-01')
    expect(stepMonth(MONTHS, '2026-06', 1)).toBe('2026-06')
  })
  it('异常输入安全返回原值：未知月份 / 空列表', () => {
    expect(stepMonth(MONTHS, '2025-12', 1)).toBe('2025-12')
    expect(stepMonth([], '2026-02', 1)).toBe('2026-02')
  })
})

describe('canStep 端点禁用态', () => {
  it('中间月双向可走，端点对应方向锁死', () => {
    expect(canStep(MONTHS, '2026-02', -1)).toBe(true)
    expect(canStep(MONTHS, '2026-02', 1)).toBe(true)
    expect(canStep(MONTHS, '2026-01', -1)).toBe(false)
    expect(canStep(MONTHS, '2026-06', 1)).toBe(false)
  })
})
