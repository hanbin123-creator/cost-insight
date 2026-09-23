// decomp 纯函数测试：量价分解表格的着色/格式化/口径文案（排版选型方案一）
import { describe, expect, it } from 'vitest'
import { effClass, fmtEffect, fmtTransition, methodLabel, transitionPlaceholder } from '../decomp'
import type { DecompRow } from '../types'
import demo from '../../public/fixtures/demo_attribution.json'

const market: DecompRow = {
  material: '金银花', method: 'market_price', price_prev: 126.5, price_curr: 124,
  qty_prev: 0.0257, qty_curr: 0.0256, price_effect: -0.0641, qty_effect: -0.0059,
  covered: true, note: '按市场行情价分解',
}
const stable: DecompRow = {
  material: '纯化水', method: 'stable_price_assumption', price_prev: null, price_curr: null,
  qty_prev: null, qty_curr: null, price_effect: 0, qty_effect: 0,
  covered: false, note: '行情未覆盖的稳价辅料',
}
const uncovered: DecompRow = {
  material: '某辅料', method: 'uncovered', price_prev: null, price_curr: null,
  qty_prev: null, qty_curr: null, price_effect: null, qty_effect: null,
  covered: false, note: '行情未覆盖且无上月数据，不分解',
}

describe('effClass 着色（与热力图同口径：降本绿/升本红）', () => {
  it('负效应 dn，正效应 up，零与缺失 flat', () => {
    expect(effClass(-0.0641)).toBe('dn')
    expect(effClass(0.0067)).toBe('up')
    expect(effClass(0)).toBe('flat')
    expect(effClass(null)).toBe('flat')
  })
})

describe('fmtEffect 显示', () => {
  it('4 位小数；正数补 +；负数自带 -；缺失 —', () => {
    expect(fmtEffect(-0.0641)).toBe('-0.0641')
    expect(fmtEffect(0.0067)).toBe('+0.0067')
    expect(fmtEffect(0)).toBe('0.0000')
    expect(fmtEffect(null)).toBe('—')
  })
})

describe('fmtTransition 变迁显示', () => {
  it('正常值箭头连接；整数价格补一位小数', () => {
    expect(fmtTransition(126.5, 124, '')).toBe('126.5 → 124.0')
    expect(fmtTransition(0.0257, 0.0256, '')).toBe('0.0257 → 0.0256')
  })
  it('任一侧 null → 占位文案', () => {
    expect(fmtTransition(null, null, '稳价假设')).toBe('稳价假设')
  })
})

describe('口径与占位文案', () => {
  it('三种 method 的标签', () => {
    expect(methodLabel(market)).toBe('行情价')
    expect(methodLabel(stable)).toBe('稳价假设 · 行情未覆盖')
    expect(methodLabel(uncovered)).toBe('数据缺失 · 不分解')
  })
  it('占位文案：稳价假设 vs 无上月数据', () => {
    expect(transitionPlaceholder(stable)).toBe('稳价假设')
    expect(transitionPlaceholder(uncovered)).toBe('无上月数据')
  })
})

describe('演示 fixture 结构', () => {
  it('demo_attribution.json 带 decomposition 且字段齐全', () => {
    expect(Array.isArray(demo.decomposition)).toBe(true)
    expect(demo.decomposition.length).toBeGreaterThan(0)
    for (const d of demo.decomposition) {
      expect(d).toHaveProperty('material')
      expect(d).toHaveProperty('method')
      expect(d).toHaveProperty('covered')
      expect(d).toHaveProperty('price_effect')
      expect(d).toHaveProperty('qty_effect')
    }
  })
})
