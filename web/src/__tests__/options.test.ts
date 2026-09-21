/** 图表映射层单测：真实 API fixture 驱动 + 恶意用例（null 首月 / 负总变动瀑布） */
import { describe, expect, it } from 'vitest'
import {
  CT, structureOption, trendOption, waterfallOption,
} from '../charts/options'
import type {
  ForecastResp, SeriesResp, StructureResp, WaterfallResp,
} from '../types'
import forecast from '../../fixtures/forecast_yinhuang.json'
import series from '../../fixtures/series_yinhuang.json'
import structure from '../../fixtures/structure_yinhuang_01.json'
import waterfallNeg from '../../fixtures/waterfall_liuwei_03_negative.json'
import waterfall from '../../fixtures/waterfall_yinhuang_05.json'

describe('trendOption', () => {
  it('4 条线（单位成本+三要素），每条 6 个点', () => {
    const opt = trendOption(series as SeriesResp) as {
      series: Array<{ data: number[] }>
    }
    expect(opt.series).toHaveLength(4)
    for (const s of opt.series) expect(s.data).toHaveLength(6)
  })

  it('预测延伸带：x 轴扩到 9 月，历史线尾部补 null，虚线/置信带/对照线齐备', () => {
    const f = forecast as ForecastResp
    const opt = trendOption(series as SeriesResp, f) as {
      xAxis: { data: string[] }
      legend: { data: string[] }
      series: Array<{ name: string; data: (number | null)[]; lineStyle?: { type?: string } }>
    }
    expect(opt.xAxis.data).toHaveLength(9)
    expect(opt.series).toHaveLength(8)  // 4 历史 + 带底 + 带厚 + Holt + 同比
    // 历史线尾部补 null（摆放，不得补 0）
    const unitCost = opt.series.find((s) => s.name === '单位成本')!
    expect(unitCost.data).toHaveLength(9)
    expect(unitCost.data.slice(6)).toEqual([null, null, null])
    // Holt 虚线与最后历史点衔接
    const holt = opt.series.find((s) => s.name === 'Holt 预测')!
    expect(holt.lineStyle?.type).toBe('dashed')
    expect(holt.data[5]).toBe((series as SeriesResp).unit_cost[5])
    // 置信带：厚度 = upper - lower（后端预算，前端不得再减）
    const lower = opt.series.find((s) => s.name === 'band-lower')!
    const band = opt.series.find((s) => s.name === '80% 置信带')!
    for (let i = 6; i < 9; i++) {
      expect((lower.data[i]! as number) + (band.data[i]! as number))
        .toBeCloseTo(f.upper[i - 6]!, 1)
    }
    // 图例不含堆叠基底
    expect(opt.legend.data).not.toContain('band-lower')
    expect(opt.legend.data).toContain('同比对照')
  })
})

describe('waterfallOption', () => {
  it('堆叠不变式：transparent_base + visible = max(start, end)', () => {
    const w = waterfall as WaterfallResp
    waterfallOption(w)
    for (const s of w.segments) {
      expect(s.transparent_base + s.visible).toBeCloseTo(Math.max(s.start, s.end), 6)
    }
  })

  it('负总变动月份（恶意用例）：全部 delta 段为绿色 down，基底坐标非负', () => {
    const w = waterfallNeg as WaterfallResp
    const opt = waterfallOption(w) as {
      series: Array<{ data: Array<{ itemStyle: { color: string } }> }>
    }
    const bars = opt.series[1]!.data
    const deltas = w.segments.filter((s) => s.type === 'delta')
    expect(w.total_change).toBeLessThan(0)
    deltas.forEach((s, i) => {
      expect(s.direction).toBe('down')
      expect(bars[i + 1]!.itemStyle.color).toBe(CT.down)
      expect(s.transparent_base).toBeGreaterThanOrEqual(0)
    })
  })
})

describe('structureOption', () => {
  it('外环合计 ≈ 单位成本（对账容差 0.02）', () => {
    const s = structure as StructureResp
    structureOption(s)
    const outerSum = s.outer.reduce((a, o) => a + o.value, 0)
    expect(Math.abs(outerSum - s.unit_cost)).toBeLessThanOrEqual(0.02)
  })
})

// 注：heatmapOption 已随"表格式热力图"改造移除；null 首月语义由
// heat-table.test.ts 的 heatCellMap 用例承接（未覆盖坐标 = null = "—"）。
