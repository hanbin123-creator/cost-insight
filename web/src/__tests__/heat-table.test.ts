// heatTable 纯函数测试：色阶/分组/查找/选中判定
import { describe, expect, it } from 'vitest'
import {
  fmtPct, heatCellBg, heatCellFg, heatCellMap, heatMaxAbs, heatZones, isSelCell,
} from '../heatTable'
import { CT } from '../charts/options'
import type { HeatmapResp } from '../types'
import heatmap from '../../fixtures/heatmap.json'

const h = heatmap as HeatmapResp

describe('heatMaxAbs 色阶量程', () => {
  it('ceil 最大绝对值；全 null 时保底 1', () => {
    expect(heatMaxAbs(h)).toBeGreaterThanOrEqual(1)
    expect(heatMaxAbs({ months: [], rows: [], data: [] })).toBe(1)
    expect(heatMaxAbs({ months: ['m'], rows: ['r'], data: [[0, 0, -6.2]] })).toBe(7)
  })
})

describe('heatZones 产品分区', () => {
  it('相邻同产品行并区：3 产品 × 3 要素 = 3 区，行索引原序', () => {
    const zones = heatZones(h)
    expect(zones).toHaveLength(3)
    expect(zones.map((z) => z.product)).toEqual(['银黄口服液', '板蓝根颗粒', '六味地黄胶囊'])
    for (const z of zones) {
      expect(z.rows).toHaveLength(3)
      expect(z.rows.map((r) => r.element)).toEqual(['直接材料', '直接人工', '制造费用'])
    }
    // 行索引连续且覆盖全部 9 行
    expect(zones.flatMap((z) => z.rows.map((r) => r.ri))).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8])
  })
})

describe('heatCellMap 查找', () => {
  it('覆盖坐标返回值；未覆盖返回 undefined→按 null 处理', () => {
    const m = heatCellMap(h)
    expect(m.get('0:1')).not.toBeUndefined()
    expect(m.get('0:0')).toBeNull()          // 首月无环比
    expect(m.get('99:99')).toBeUndefined()
  })
})

describe('fmtPct 显示', () => {
  it('null → "—"；正数补 +；不做二次取整', () => {
    expect(fmtPct(null)).toBe('—')
    expect(fmtPct(10.4)).toBe('+10.4%')
    expect(fmtPct(-3)).toBe('-3%')
    expect(fmtPct(0)).toBe('0%')
  })
})

describe('heatCellBg / heatCellFg 色阶', () => {
  it('null 灰格；正向偏红端、负向偏绿端；零值近白', () => {
    expect(heatCellBg(null, 6)).toBe('#f0f1f5')
    expect(heatCellBg(6, 6)).toBe(`rgb(${[1, 3, 5].map((i) => parseInt(CT.heat[2].slice(i, i + 2), 16)).join(', ')})`)
    expect(heatCellBg(-6, 6)).toBe(`rgb(${[1, 3, 5].map((i) => parseInt(CT.heat[0].slice(i, i + 2), 16)).join(', ')})`)
    expect(heatCellBg(0, 6)).not.toBe('#f0f1f5')   // 零值仍有 12% 保底着色
  })
  it('超量程钳制不溢出；深色底换白字', () => {
    expect(heatCellBg(99, 6)).toBe(heatCellBg(6, 6))
    expect(heatCellFg(6, 6)).toBe('#ffffff')
    expect(heatCellFg(0.5, 6)).toBe('#33415c')
    expect(heatCellFg(null, 6)).toBe('#33415c')
  })
})

describe('isSelCell 选中判定（与旧热力图同口径）', () => {
  it('当前 产品×月份 的三要素格命中；跨月/跨产品/缺参不命中', () => {
    const mi = h.months.indexOf('2026-05')
    expect(isSelCell(h, { product: '银黄口服液', month: '2026-05' }, 0, mi)).toBe(true)
    expect(isSelCell(h, { product: '银黄口服液', month: '2026-05' }, 2, mi)).toBe(true)
    expect(isSelCell(h, { product: '银黄口服液', month: '2026-05' }, 3, mi)).toBe(false) // 板蓝根行
    expect(isSelCell(h, { product: '银黄口服液', month: '2026-05' }, 0, 0)).toBe(false)  // 首月
    expect(isSelCell(h, { product: '银黄口服液' }, 0, mi)).toBe(false)                   // 缺月份
    expect(isSelCell(h, {}, 0, mi)).toBe(false)
  })
})
