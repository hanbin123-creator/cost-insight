/** 增量2 联动单测：趋势图告警 pin、热力图选中描边、告警行动卡纯函数 */
import { describe, expect, it } from 'vitest'
import { CT, heatmapOption, trendOption } from '../charts/options'
import { alertKey, matchTask, momTone } from '../alerts'
import type { Alert, HeatmapResp, RectifyTask, SeriesResp } from '../types'
import heatmap from '../../fixtures/heatmap.json'
import series from '../../fixtures/series_yinhuang.json'

const s = series as SeriesResp
const h = heatmap as HeatmapResp

describe('trendOption 告警 pin（F3 V4 联动）', () => {
  it('当前月有告警：单位成本主线钉 pin，坐标=该月实际值，数量=告警条数', () => {
    const month = s.months[s.months.length - 1]!
    const idx = s.months.indexOf(month)
    const opt = trendOption(s, null, { month, count: 2 }) as {
      series: Array<{ name: string; markPoint?: { data: Array<{ coord: [string, number] }>; itemStyle: { color: string } } }>
    }
    const main = opt.series[0]!
    expect(main.name).toBe('单位成本')
    expect(main.markPoint).toBeDefined()
    expect(main.markPoint!.data).toHaveLength(1)
    expect(main.markPoint!.data[0]!.coord).toEqual([month, s.unit_cost[idx]])
    expect(main.markPoint!.itemStyle.color).toBe(CT.up)  // 告警=信号红
  })

  it('无告警 / 告警月不在轴上：不钉 pin', () => {
    const noMark = trendOption(s, null, null) as { series: Array<{ markPoint?: unknown }> }
    expect(noMark.series[0]!.markPoint).toBeUndefined()
    const badMonth = trendOption(s, null, { month: '1999-01', count: 1 }) as { series: Array<{ markPoint?: unknown }> }
    expect(badMonth.series[0]!.markPoint).toBeUndefined()
  })
})

describe('heatmapOption 选中描边（F4 V4 联动）', () => {
  it('当前 产品×月份 的格子加深色描边：数量=该产品要素行数，月份索引正确', () => {
    const product = h.rows[0]!.split('·')[0]!
    const month = h.months[h.months.length - 1]!
    const mi = h.months.indexOf(month)
    const rowCount = h.rows.filter((r) => r.startsWith(`${product}·`)).length
    const opt = heatmapOption(h, { product, month }) as {
      series: Array<{ data: Array<[number, number, number | null] | { value: [number, number, number | null]; itemStyle: { borderColor: string } }> }>
    }
    const bordered = opt.series[0]!.data.filter((d) => !Array.isArray(d))
    expect(bordered).toHaveLength(rowCount)
    for (const d of bordered) {
      if (!Array.isArray(d)) {
        expect(d.value[0]).toBe(mi)
        expect(d.itemStyle.borderColor).toBe(CT.main)
        expect(h.rows[d.value[1]]!.startsWith(`${product}·`)).toBe(true)
      }
    }
  })

  it('无选中参数 / 月份不存在：数据原样（纯数组，无描边包装）', () => {
    const plain = heatmapOption(h) as { series: Array<{ data: unknown[] }> }
    expect(plain.series[0]!.data.every(Array.isArray)).toBe(true)
    const badMonth = heatmapOption(h, { product: '银黄口服液', month: '1999-01' }) as { series: Array<{ data: unknown[] }> }
    expect(badMonth.series[0]!.data.every(Array.isArray)).toBe(true)
  })

  it('tooltip 双形态兼容：选中格（对象包装）不炸且带"当前看板"前缀，普通格无前缀', () => {
    const product = h.rows[0]!.split('·')[0]!
    const month = h.months[h.months.length - 1]!
    const opt = heatmapOption(h, { product, month }) as {
      series: Array<{ data: Array<[number, number, number | null] | { value: [number, number, number | null] }> }>
      tooltip: { formatter: (p: { data: unknown }) => string }
    }
    const selCell = opt.series[0]!.data.find((d) => !Array.isArray(d)) as { value: [number, number, number | null] }
    const plainCell = opt.series[0]!.data.find(Array.isArray) as [number, number, number | null]
    const selTip = opt.tooltip.formatter({ data: selCell })       // 修复前：此处直接 TypeError
    const plainTip = opt.tooltip.formatter({ data: plainCell })
    expect(selTip).toContain('当前看板')
    expect(selTip).toContain(h.rows[selCell.value[1]]!)
    expect(plainTip).not.toContain('当前看板')
    expect(plainTip).toContain('环比')
  })
})

describe('告警行动卡纯函数', () => {
  const a1: Alert = { channel: '累计涨幅', element: '金银花', mom_pct: 10.4, message: '金银花行情价累计+10.4%' }
  const a2: Alert = { channel: '要素环比', element: '直接人工', mom_pct: -12.1, message: '直接人工环比-12.1%' }

  it('alertKey：同告警同键、不同告警不同键', () => {
    expect(alertKey(a1)).toBe(alertKey({ ...a1 }))
    expect(alertKey(a1)).not.toBe(alertKey(a2))
  })

  it('matchTask：按要素名匹配任务标题；无匹配/空要素返回 null', () => {
    const tasks = [
      { task_id: 'ZG-2026-05-01', title: '金银花采购价格异常整改', assignee: '张三(采购部)',
        priority: '高', deadline: '2026-06-25', dispatch: 'sent', notify: 'pushed',
        receipt: null, error: null },
    ] as RectifyTask[]
    expect(matchTask(a1, tasks)?.task_id).toBe('ZG-2026-05-01')
    expect(matchTask(a2, tasks)).toBeNull()
    expect(matchTask({ ...a1, element: '' }, tasks)).toBeNull()
  })

  it('momTone：涨=up（不利红）/ 跌=down（有利绿）/ 平=flat', () => {
    expect(momTone(10.4)).toBe('up')
    expect(momTone(-3.2)).toBe('down')
    expect(momTone(0)).toBe('flat')
  })
})
