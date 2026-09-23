// 月份步进器纯函数（顶栏切换器方案三）：相邻月步进，越界钳制在端点
export function stepMonth(months: string[], current: string, delta: number): string {
  const i = months.indexOf(current)
  if (i < 0 || !months.length) return current
  const j = Math.min(Math.max(i + delta, 0), months.length - 1)
  return months[j] ?? current
}

/** 当前月是否还能向某方向步进（驱动 ‹ › 按钮的禁用态） */
export function canStep(months: string[], current: string, delta: number): boolean {
  return stepMonth(months, current, delta) !== current
}
