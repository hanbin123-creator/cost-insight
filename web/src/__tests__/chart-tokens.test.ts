import { describe, expect, it } from 'vitest'
import { CT, elementColor, structureOption, trendOption } from '../charts/options'
import type { SeriesResp, StructureResp } from '../types'
import series from '../../public/fixtures/series_yinhuang.json'
import structure from '../../public/fixtures/structure_yinhuang_01.json'

describe('图表 token 色彩纪律（条款 6 + D7 Tableau 10 分类色）', () => {
  it('趋势图：单位成本=深海军蓝主角，要素线=分类色且跨图一致', () => {
    const opt = trendOption(series as SeriesResp) as {
      series: Array<{ name: string; lineStyle: { color: string; width: number } }>
    }
    expect(opt.series[0]!.lineStyle.color).toBe(CT.main)
    expect(opt.series[0]!.lineStyle.width).toBeGreaterThan(2)
    for (const s of opt.series.slice(1)) {
      expect(s.lineStyle.color).toBe(elementColor(s.name))  // 趋势线颜色 = 要素身份色
      expect(s.lineStyle.width).toBeLessThan(2.5)
    }
  })

  it('要素身份色跨图一致：趋势线与环形图内环同色', () => {
    const opt = structureOption(structure as StructureResp) as {
      series: Array<{ data: Array<{ name: string; itemStyle: { color: string } }> }>
    }
    for (const d of opt.series[0]!.data) {
      expect(d.itemStyle.color).toBe(CT.element[d.name])
    }
  })

  it('结构图外环：物料跟随父要素色相族（明度浅化），组间色相分明', () => {
    const opt = structureOption(structure as StructureResp) as {
      series: Array<{ data: Array<{ name: string; itemStyle: { color: string } }> }>
    }
    const outer = opt.series[1]!.data
    const src = structure as StructureResp
    outer.forEach((d, i) => {
      const parent = src.outer[i]!.parent
      if (parent && CT.elementTint[parent]) {
        expect(CT.elementTint[parent]).toContain(d.itemStyle.color)
      }
    })
    // 族间对比：材料族任一切片 ≠ 人工/费用切片色
    const matColors = outer.filter((_, i) => src.outer[i]!.parent === '直接材料').map((d) => d.itemStyle.color)
    expect(matColors).not.toContain(CT.elementTint['直接人工']![0])
    expect(matColors).not.toContain(CT.elementTint['制造费用']![0])
  })

  it('分类板不含信号红/信号绿（语义色只给方向与告警）', () => {
    const categorical = [CT.main, ...Object.values(CT.element), ...Object.values(CT.elementTint).flat(), ...CT.fallback]
    expect(categorical).not.toContain(CT.up)
    expect(categorical).not.toContain(CT.down)
    expect(CT.up).toBe('#c0392b')
    expect(CT.down).toBe('#27a06c')
  })

  it('瀑布总量柱用深板岩灰蓝（D7：淡色无存在感）', () => {
    expect(CT.base).toBe('#54687a')
  })

  it('未知要素名确定性落 fallback（同名必同色，不随机）', () => {
    expect(elementColor('未知要素X')).toBe(elementColor('未知要素X'))
    expect(CT.fallback).toContain(elementColor('未知要素X'))
  })
})
