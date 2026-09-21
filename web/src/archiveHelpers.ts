// 报告中心 + 知识库页的纯展示助手（前端只摆放不算数：格式化/映射/校验全部纯函数可测）

/** 归档时间显示：epoch 秒 → 'MM-DD HH:mm'（同年不显示年份，跨年补年份） */
export function fmtMtime(epochSec: number, now: Date = new Date()): string {
  const d = new Date(epochSec * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  const base = `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  return d.getFullYear() === now.getFullYear() ? base : `${d.getFullYear()}-${base}`
}

/** 文件大小显示：KB → 保留整数；>=1024KB 转 MB 一位小数 */
export function fmtSize(kb: number): string {
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.round(kb)} KB`
}

/** 主题徽标：后端 theme 字段 → 显示文案（月报/季报/专题），未知主题原样透传 */
export function themeLabel(theme: string): string {
  if (theme.includes('月')) return '月报'
  if (theme.includes('季')) return '季报'
  if (theme.includes('专题')) return '专题'
  return theme
}

/** 新建报告参数校验：返回 null 表示可提交，否则返回用户可读的原因 */
export function validateReportParams(
  theme: 'monthly' | 'quarterly' | 'topical',
  product: string,
  month: string,
  quarter: string,
): string | null {
  if (!product) return '请选择产品'
  if (theme === 'quarterly') {
    return quarter ? null : '季度报告须选择季度（Q1/Q2）'
  }
  return month ? null : '月报/专题须选择月份'
}

/** 召回通道标签：后端 channels 数组 → 中文 chips（RAG 透明化展示） */
export function channelLabel(ch: string): string {
  switch (ch) {
    case 'vector': return '向量'
    case 'bm25': return '关键词'
    case 'graph': return '图谱'
    default: return ch
  }
}

/** 索引重建任务状态文案（job.state 原值来自后端，如实映射） */
export function jobStateText(job: { state: string; detail?: string; chunks?: number }): string {
  switch (job.state) {
    case 'running': return '索引重建中…'
    case 'done': return job.chunks ? `索引就绪（${job.chunks} 块）` : '索引就绪'
    case 'failed': return `重建失败：${job.detail ?? '未知原因'}`
    default: return '索引空闲'
  }
}

/** 命中文本摘要：超出 maxLen 截断加省略号（卡片展示用，不改动原证据文本） */
export function snippet(text: string, maxLen = 120): string {
  const t = text.replace(/\s+/g, ' ').trim()
  return t.length > maxLen ? `${t.slice(0, maxLen)}…` : t
}
