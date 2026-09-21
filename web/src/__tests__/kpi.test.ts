import { describe, expect, it } from 'vitest'
import { alertCardStatus, costDeltaTone, fmtDelta, fmtNum, unitCostStatus } from '../kpi'

describe('KPI 状态分类（阈值对齐后端告警通道 ±10%）', () => {
  it('单位成本卡只看自身环比：>10 红 / >5 橙 / 其余中性（不耦合其他告警）', () => {
    expect(unitCostStatus(12.4)).toBe('alert')
    expect(unitCostStatus(-10.5)).toBe('alert')
    expect(unitCostStatus(6)).toBe('warn')
    expect(unitCostStatus(-5.5)).toBe('warn')
    expect(unitCostStatus(2.8)).toBe('neutral')
    expect(unitCostStatus(null)).toBe('neutral')
  })
  it('告警卡：有即红，无则中性', () => {
    expect(alertCardStatus(3)).toBe('alert')
    expect(alertCardStatus(0)).toBe('neutral')
  })
})

describe('数字与徽章格式化（两位小数 / 必带±文字）', () => {
  it('千分位 + 两位小数', () => {
    expect(fmtNum(14495511)).toBe('14,495,511.00')
    expect(fmtNum(1.5)).toBe('1.50')
    expect(fmtNum(null)).toBe('—')
  })
  it('环比徽章带 +/- 文字；null 显示 —', () => {
    expect(fmtDelta(12.36)).toBe('环比 +12.4%')
    expect(fmtDelta(-3.22)).toBe('环比 -3.2%')
    expect(fmtDelta(null)).toBe('—')
  })
  it('成本方向语义：降=good 升=bad', () => {
    expect(costDeltaTone(-2)).toBe('good')
    expect(costDeltaTone(2)).toBe('bad')
    expect(costDeltaTone(0)).toBe('neutral')
    expect(costDeltaTone(null)).toBe('neutral')
  })
})
