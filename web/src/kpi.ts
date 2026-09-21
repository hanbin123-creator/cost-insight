/** KPI 行纯函数（可单测）：格式化与状态分类。
 * 状态语义（条款 2 + ISA-101）：neutral=平稳中性（不上色）、warn=预警橙、alert=告警红。
 * 注意：本文件只做"展示分类"，阈值与后端 alert 通道一致（±10% 赛题字面口径），不改数、不算数。 */

export type KpiStatus = 'neutral' | 'warn' | 'alert'

/** 单位成本卡状态：只看该指标自身的环比（|环比|>10% 告警，对齐后端通道①；>5% 预警）。
 * 不耦合 alerts 数组——金银花行情告警不该把"单位成本"卡染红（ISA-101：颜色只标出问题的那个东西），
 * 告警有专门的告警卡承担红色。 */
export function unitCostStatus(momPct: number | null): KpiStatus {
  if (momPct === null) return 'neutral'
  const a = Math.abs(momPct)
  if (a > 10) return 'alert'
  if (a > 5) return 'warn'
  return 'neutral'
}

/** 告警卡状态：有告警即红（告警是行动入口，不是信息） */
export function alertCardStatus(alertCount: number): KpiStatus {
  return alertCount > 0 ? 'alert' : 'neutral'
}

/** 数字格式化：千分位 + 最多两位小数（报告口径：保留两位小数） */
export function fmtNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** 环比徽章文案：必带 +/- 文字（条款 6：不只靠色相编码）；null 为首月显示"—" */
export function fmtDelta(momPct: number | null): string {
  if (momPct === null) return '—'
  return `环比 ${momPct >= 0 ? '+' : ''}${momPct.toFixed(1)}%`
}

/** 成本类指标的升降方向语义：成本降=good（绿），升=bad（红）；null=neutral */
export function costDeltaTone(momPct: number | null): 'good' | 'bad' | 'neutral' {
  if (momPct === null || momPct === 0) return 'neutral'
  return momPct < 0 ? 'good' : 'bad'
}
