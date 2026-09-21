/** F6 归因分栏的数字联动纯函数：把报告文本切成"数字段/非数字段"，
 *  数字段渲染为可点按钮，点击后与证据列 figures 精确匹配高亮。
 *  解析=显示层摆放（数字本身由后端/校验闭环保证真实存在），不涉任何计算。 */

export interface FigToken {
  text: string
  /** 非数字段为 null；数字段为解析值（去千分位逗号，% 只取数值部分） */
  value: number | null
}

const FIG_RE = /[+-]?\d[\d,]*(?:\.\d+)?%?/g

export function parseFig(text: string): number | null {
  const m = text.match(/[+-]?\d[\d,]*(?:\.\d+)?/)
  if (!m) return null
  const v = parseFloat(m[0].replace(/,/g, ''))
  return Number.isFinite(v) ? v : null
}

export function tokenizeFigures(text: string): FigToken[] {
  const out: FigToken[] = []
  let last = 0
  for (const m of text.matchAll(FIG_RE)) {
    const i = m.index
    if (i > last) out.push({ text: text.slice(last, i), value: null })
    out.push({ text: m[0], value: parseFig(m[0]) })
    last = i + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last), value: null })
  return out
}

/** 数字与 figures 列表匹配（浮点精确到分位，容差 1e-6 防二进制误差） */
export function findFigIndex(value: number, figures: number[]): number {
  return figures.findIndex((f) => Math.abs(f - value) < 1e-6)
}
