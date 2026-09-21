/** 增量2 联动单测：趋势图告警 pin、告警行动卡纯函数（热力图选中描边测试已随表格式改造迁至 heat-table.test.ts） */
import { describe, expect, it } from 'vitest'
import { CT, trendOption } from '../charts/options'
import { alertKey, matchTask, momTone } from '../alerts'
import type { Alert, RectifyTask, SeriesResp } from '../types'
import series from '../../fixtures/series_yinhuang.json'

const s = series as SeriesResp

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
