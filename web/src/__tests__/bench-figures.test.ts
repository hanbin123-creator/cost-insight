/** 增量3 单测：F9 蝶形对比图 option 不变式 + F6 数字联动纯函数 */
import { describe, expect, it } from 'vitest'
import { butterflyOption, CT } from '../charts/options'
import { findFigIndex, parseFig, tokenizeFigures } from '../figures'
import type { BenchmarkResp } from '../types'

const bench: BenchmarkResp = {
  product: '银黄口服液', month: '2026-05',
  rows: [
    { element: '直接材料', main: 7.31, bench: 8.15, diff: -0.84,
      diff_rate_pct: -10.31, reverse_rate_pct: 11.49, direction: '优势', description: 'd1' },
    { element: '直接人工', main: 1.52, bench: 1.72, diff: -0.2,
      diff_rate_pct: -11.63, reverse_rate_pct: 13.16, direction: '优势', description: 'd2' },
    { element: '制造费用', main: 2.38, bench: 2.5, diff: -0.12,
      diff_rate_pct: -4.8, reverse_rate_pct: 5.04, direction: '优势', description: 'd3' },
    { element: '单位成本', main: 11.21, bench: 12.37, diff: -1.16,
      diff_rate_pct: -9.38, reverse_rate_pct: 10.35, direction: '优势', description: 'd4' },
  ],
  material_detail: [],
}

describe('butterflyOption（F9 蝶形图）', () => {
  it('镜像不变式：一厂系列 = -main（仅显示镜像），二厂系列 = bench 原值', () => {
    const opt = butterflyOption(bench) as {
      series: Array<{ name: string; data: number[] }>
    }
    const [s1, s2] = opt.series
    expect(s1!.name).toBe('一厂')
    expect(s2!.name).toBe('二厂')
    bench.rows.forEach((r, i) => {
      expect(s1!.data[i]).toBe(-r.main)
      expect(s2!.data[i]).toBe(r.bench)
    })
  })

  it('x 轴对称量程（min === -max）且容纳两方最大值', () => {
    const opt = butterflyOption(bench) as { xAxis: { min: number; max: number } }
    expect(opt.xAxis.min).toBe(-opt.xAxis.max)
    const maxV = Math.max(...bench.rows.flatMap((r) => [r.main, r.bench]))
    expect(opt.xAxis.max).toBeGreaterThanOrEqual(maxV)
  })

  it('两方配色：一厂主色深海军蓝 / 二厂同族浅蓝（CT.peer），y 轴为要素序', () => {
    const opt = butterflyOption(bench) as {
      series: Array<{ itemStyle: { color: string } }>
      yAxis: { data: string[] }
    }
    expect(opt.series[0]!.itemStyle.color).toBe(CT.main)
    expect(opt.series[1]!.itemStyle.color).toBe(CT.peer)
    expect(opt.yAxis.data).toEqual(['直接材料', '直接人工', '制造费用', '单位成本'])
  })
})

describe('figures 数字联动纯函数（F6）', () => {
  it('tokenizeFigures：切出数字段且拼接还原原文', () => {
    const text = '直接人工由 1.52 升至 1.72，环比+10.4%'
    const tokens = tokenizeFigures(text)
    expect(tokens.map((t) => t.text).join('')).toBe(text)
    expect(tokens.filter((t) => t.value !== null).map((t) => t.value))
      .toEqual([1.52, 1.72, 10.4])
  })

  it('parseFig：千分位/百分号/负数/非数字', () => {
    expect(parseFig('1,234.56')).toBe(1234.56)
    expect(parseFig('-3.2%')).toBe(-3.2)
    expect(parseFig('+10.4%')).toBe(10.4)
    expect(parseFig('abc')).toBeNull()
  })

  it('findFigIndex：精确匹配（容差 1e-6），未命中返 -1', () => {
    expect(findFigIndex(1.52, [1.52, 10.4])).toBe(0)
    expect(findFigIndex(9.99, [1.52, 10.4])).toBe(-1)
  })
})
