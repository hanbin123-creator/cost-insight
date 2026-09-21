// archiveHelpers 纯函数测试：时间/大小格式化、主题徽标、参数校验、通道标签、摘要
import { describe, expect, it } from 'vitest'
import {
  channelLabel, fmtMtime, fmtSize, jobStateText, snippet, themeLabel, validateReportParams,
} from '../archiveHelpers'

describe('fmtMtime 归档时间', () => {
  const now = new Date('2026-09-21T12:00:00')
  it('同年显示 MM-DD HH:mm，不显示年份', () => {
    const ts = new Date('2026-05-03T14:30:00').getTime() / 1000
    expect(fmtMtime(ts, now)).toBe('05-03 14:30')
  })
  it('跨年补年份；单位数补零', () => {
    const ts = new Date('2025-01-05T08:05:00').getTime() / 1000
    expect(fmtMtime(ts, now)).toBe('2025-01-05 08:05')
  })
})

describe('fmtSize 文件大小', () => {
  it('KB 整数显示；超 1024 转 MB 一位小数', () => {
    expect(fmtSize(512.6)).toBe('513 KB')
    expect(fmtSize(2048)).toBe('2.0 MB')
  })
})

describe('themeLabel 主题徽标', () => {
  it('月度/季度/专题映射为月报/季报/专题', () => {
    expect(themeLabel('月度')).toBe('月报')
    expect(themeLabel('季度')).toBe('季报')
    expect(themeLabel('专题')).toBe('专题')
  })
  it('未知主题原样透传不崩', () => {
    expect(themeLabel('年度')).toBe('年度')
  })
})

describe('validateReportParams 新建报告校验', () => {
  it('月报/专题须选月份；季报须选季度', () => {
    expect(validateReportParams('monthly', '银黄口服液', '2026-05', '')).toBeNull()
    expect(validateReportParams('monthly', '银黄口服液', '', '')).toContain('月份')
    expect(validateReportParams('topical', '银黄口服液', '', '')).toContain('月份')
    expect(validateReportParams('quarterly', '银黄口服液', '', 'Q2')).toBeNull()
    expect(validateReportParams('quarterly', '银黄口服液', '', '')).toContain('季度')
  })
  it('未选产品优先报产品', () => {
    expect(validateReportParams('monthly', '', '', '')).toBe('请选择产品')
  })
})

describe('channelLabel 召回通道', () => {
  it('三路通道映射中文；未知通道透传', () => {
    expect(channelLabel('vector')).toBe('向量')
    expect(channelLabel('bm25')).toBe('关键词')
    expect(channelLabel('graph')).toBe('图谱')
    expect(channelLabel('hybrid')).toBe('hybrid')
  })
})

describe('jobStateText 索引任务状态', () => {
  it('running/done/failed/idle 四态如实映射', () => {
    expect(jobStateText({ state: 'running' })).toBe('索引重建中…')
    expect(jobStateText({ state: 'done', chunks: 128 })).toBe('索引就绪（128 块）')
    expect(jobStateText({ state: 'failed', detail: '嵌入超时' })).toBe('重建失败：嵌入超时')
    expect(jobStateText({ state: 'idle' })).toBe('索引空闲')
  })
})

describe('snippet 命中摘要', () => {
  it('空白归一化；超长截断加省略号；短文本原样', () => {
    expect(snippet('  多  行\n文本  ')).toBe('多 行 文本')
    const long = '字'.repeat(200)
    expect(snippet(long, 120)).toHaveLength(121)
    expect(snippet(long, 120).endsWith('…')).toBe(true)
    expect(snippet('短')).toBe('短')
  })
})
