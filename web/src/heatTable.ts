// 表格式热力图（方案二 + 产品分区）的纯函数层。
// 取代 ECharts heatmap：数据不变（/api/charts/heatmap），渲染换为条件格式表格。
// 铁律不变：所有色阶/分组/选中判定都是纯函数，单测锁死，组件只摆放。

import { CT } from './charts/options'
import type { HeatmapResp } from './types'

export interface HeatZoneRow { element: string; ri: number }
export interface HeatZone { product: string; rows: HeatZoneRow[] }

/** 色阶量程：与 ECharts visualMap 同口径（ceil 最大绝对值，至少 1） */
export function heatMaxAbs(h: HeatmapResp): number {
  const nums = h.data.map((d) => d[2]).filter((v): v is number => v !== null)
  return Math.ceil(Math.max(...nums.map(Math.abs), 1))
}

/** 行 → 产品分区：相邻同产品的行并为一区（行序即服务端返回序，前端不重排） */
export function heatZones(h: HeatmapResp): HeatZone[] {
  const zones: HeatZone[] = []
  h.rows.forEach((r, ri) => {
    const sep = r.indexOf('·')
    const product = sep >= 0 ? r.slice(0, sep) : r
    const element = sep >= 0 ? r.slice(sep + 1) : ''
    const last = zones[zones.length - 1]
    if (last && last.product === product) last.rows.push({ element, ri })
    else zones.push({ product, rows: [{ element, ri }] })
  })
  return zones
}

/** (ri,mi) → 值 查找表：网格未覆盖的坐标返回 null（与首月无环比同义，显示"—"） */
export function heatCellMap(h: HeatmapResp): Map<string, number | null> {
  const m = new Map<string, number | null>()
  for (const [mi, ri, v] of h.data) m.set(`${ri}:${mi}`, v)
  return m
}

/** 显示值：服务端已按口径取整/保留小数，前端只补符号，不再四舍五入 */
export function fmtPct(v: number | null): string {
  return v === null ? '—' : `${v > 0 ? '+' : ''}${v}%`
}

function lerpChannel(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t)
}

function hexRgb(hex: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number]
}

/** 单元格底色：白 → 端色（绿降/红升）按 |v|/maxAbs 插值；null 给中性灰格 */
export function heatCellBg(v: number | null, maxAbs: number): string {
  if (v === null) return '#f0f1f5'
  const t = Math.min(Math.abs(v) / maxAbs, 1)
  const end = hexRgb(v > 0 ? CT.heat[2] : CT.heat[0])
  const start = hexRgb('#f7f9fa')
  const k = 0.12 + 0.88 * t   // 保底 12% 着色：小幅度也看得见
  const [r, g, b] = [0, 1, 2].map((i) => lerpChannel(start[i]!, end[i]!, k))
  return `rgb(${r}, ${g}, ${b})`
}

/** 单元格文字色：深色底上换白字（阈值 0.62，与白底插值端点匹配） */
export function heatCellFg(v: number | null, maxAbs: number): string {
  return v !== null && Math.abs(v) / maxAbs > 0.62 ? '#ffffff' : '#33415c'
}

/** 选中格判定：行属于当前产品 且 列等于当前月份（联动逻辑与旧热力图同口径） */
export function isSelCell(h: HeatmapResp, sel: { product?: string; month?: string }, ri: number, mi: number): boolean {
  if (sel.product == null || !sel.month) return false
  if (h.months[mi] !== sel.month) return false
  return (h.rows[ri] ?? '').startsWith(`${sel.product}·`)
}
