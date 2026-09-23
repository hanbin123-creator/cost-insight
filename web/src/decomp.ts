// 量价分解表格的纯显示函数（排版选型方案一）：着色口径与热力图一致——
// 效应为负（拉低成本）= 绿 dn，为正（推高成本）= 红 up，零/缺失 = 灰 flat。
import type { DecompRow } from './types'

/** 效应值着色类名 */
export function effClass(v: number | null): 'dn' | 'up' | 'flat' {
  if (v === null || v === 0) return 'flat'
  return v < 0 ? 'dn' : 'up'
}

/** 效应值显示：统一 4 位小数，正数补 +，缺失 — */
export function fmtEffect(v: number | null): string {
  if (v === null) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(4)
}

/** 价格/用量变迁显示：null（稳价假设或未覆盖）→ 占位文案；整数价格补一位小数 */
export function fmtTransition(prev: number | null, curr: number | null, placeholder: string): string {
  if (prev === null || curr === null) return placeholder
  const f = (v: number) => (Number.isInteger(v) ? v.toFixed(1) : String(v))
  return `${f(prev)} → ${f(curr)}`
}

/** 口径列文案 */
export function methodLabel(d: DecompRow): string {
  if (d.method === 'market_price') return '行情价'
  if (d.method === 'stable_price_assumption') return '稳价假设 · 行情未覆盖'
  return '数据缺失 · 不分解'
}

/** 该行的价格/用量变迁占位文案 */
export function transitionPlaceholder(d: DecompRow): string {
  return d.method === 'uncovered' ? '无上月数据' : '稳价假设'
}
