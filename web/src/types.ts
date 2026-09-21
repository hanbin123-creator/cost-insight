/** API 契约类型（与后端 pydantic schemas 对齐；openapi-typescript 自动生成列入联调待办） */

export interface ProductsResp {
  products: string[]
  months: string[]
}

export interface SeriesResp {
  product: string
  months: string[]
  unit_cost: number[]
  series: Record<string, number[]>
}

export interface WaterfallSegment {
  name: string
  type: 'total' | 'delta'
  start: number
  end: number
  value: number
  direction: 'up' | 'down' | 'flat' | 'base'
  transparent_base: number
  visible: number
}

export interface WaterfallResp {
  product: string
  month: string
  total_change: number
  waterfall_close_gap: number
  segments: WaterfallSegment[]
}

export interface StructureItem {
  name: string
  value: number
  parent?: string
}

export interface StructureResp {
  product: string
  month: string
  inner: StructureItem[]
  outer: StructureItem[]
  unit_cost: number
}

/** [monthIdx, rowIdx, momPct|null] —— null 为首月无环比，渲染"—" */
export type HeatPoint = [number, number, number | null]

export interface HeatmapResp {
  months: string[]
  rows: string[]
  data: HeatPoint[]
}

export interface Alert {
  channel: string
  element: string
  mom_pct: number
  message: string
}

export interface MetricsResp {
  product: string
  month: string
  output_qty: number
  unit_cost: number
  total_cost: number
  elements: Record<string, {
    current: number
    prev_month: number | null
    mom_pct: number | null
    yoy_pct: number | null
    budget_dev_pct: number | null
    contribution_pct: number | null
  }>
  unit_cost_mom_pct: number | null
  alerts: Alert[]
}

export interface DecisionResp {
  product: string
  month: string
  action: 'generate_attribution' | 'dashboard_only'
  reason: string
  engine: string
}

/** 预测延伸带（演示级）：所有展示坐标已由后端预计算，前端只摆放 */
export interface ForecastResp {
  product: string
  months_ext: string[]
  history: number[]
  forecast_line: (number | null)[]
  band_lower_line: (number | null)[]
  band_diff_line: (number | null)[]
  yoy_line: (number | null)[]
  point: number[]
  lower: number[]
  upper: number[]
  clipped: boolean[]
  method: string
  note: string
}

export interface Cause {
  title: string
  detail: string
  figures: number[]
  citations: string[]
}

export interface Verification {
  verdict: 'pass' | 'auto_fixed' | 'rejected'
  passed: boolean
  fixed: string[]
  errors: string[]
  retried?: boolean
}

export interface AttributionResp {
  product: string
  month: string
  summary: string
  causes: Cause[]
  suggestions: string[]
  verification: Verification
}

/** 整改任务下发结果（与后端 act.dispatch 返回对齐；RPA 不可达时 dispatch=dispatch_failed 如实呈现） */
export interface RectifyTask {
  task_id: string
  title: string
  assignee: string
  priority: string
  deadline: string
  dispatch: 'sent' | 'dispatch_failed'
  notify: 'pushed' | 'push_failed'
  /** 问题一修复：mock 重启失忆后用原 task_id 补发的任务 */
  resent?: boolean
  receipt: unknown
  error: string | null
}

export interface RectifyDispatchResp {
  product: string
  month: string
  tasks: RectifyTask[]
  note?: string
  text_source?: string
  rpa_base_url?: string
  /** 本地记已发但 RPA 不可达、未经远程核实——界面须如实标"待核实" */
  unverified?: boolean
  /** 本次补发数量（对方失忆后恢复） */
  resent?: number
}

/** 对标差异行（双向口径已由后端算好；description 是代码预生成的无歧义中文句，只读不算） */
export interface DiffRow {
  element: string
  main: number
  bench: number
  diff: number | null
  diff_rate_pct: number | null
  reverse_rate_pct: number | null
  direction: '优势' | '劣势' | '持平'
  description: string
}

/** 材料差异下钻（估算口径：按材料成本差占比分摊，后端已标注） */
export interface MaterialDiff {
  material: string
  main_unit_cost: number
  share_pct: number
  est_diff: number
}

export interface BenchmarkResp {
  product: string
  month: string
  rows: DiffRow[]
  material_detail: MaterialDiff[]
}

/** Agent 对话响应（/api/chat）：意图路由四态——执行/澄清/四入口/域外拒答 */
export interface ChatChoice { intent: string; name: string; description: string }

export interface ChatResult {
  ok?: boolean
  intent?: string
  scene?: string
  data?: Record<string, unknown>
  error?: string
  message?: string
  choices?: ChatChoice[]
}

export interface ChatResp {
  intent: string | null
  confidence: number
  layer: string
  classifier: string
  params: Record<string, string>
  clarification: string | null
  result: ChatResult | null
}

/** 整改追踪聚合（/api/rectify/tracking；RPA 不可达 ok=false 如实呈现） */
export interface RpaTask {
  task_id?: string
  title?: string
  status?: string
  priority?: string
  assignee?: string
  department?: string
  deadline?: string
  source?: string
}

export interface TrackingResp {
  ok: boolean
  error?: string
  aggregate: {
    已生成: number
    已送达: number
    已确认: number
    by_status: Record<string, number>
    by_priority: Record<string, number>
  } | null
  tasks?: RpaTask[]
}

/** 报告归档条目（/api/reports）：docx/pdf 伴生归组，mtime 服务端已倒序 */
export interface ReportFile { name: string; size_kb: number }

export interface ReportItem {
  product: string
  period: string
  theme: string
  docx: ReportFile | null
  pdf: ReportFile | null
  mtime: number
}

export interface ReportsResp {
  reports: ReportItem[]
  unknown_files: string[]
}

/** 报告生成响应（POST /api/report）：数字/表格全部后端算好，warnings 如实呈现 */
export interface ReportGenResp {
  docx: string
  pdf: string | null
  warnings: string[]
  verification: Verification
  theme: string
  sections_source: Record<string, string>
}

/** 知识库命中块（/api/kb/query）：通道标签与 RRF 分用于检索透明化展示 */
export interface KbHit {
  chunk_id: string
  doc_name: string
  page: number | null
  section: string | null
  doc_type: string
  text: string
  rrf_score: number
  channels: string[]
}

export interface KbQueryResp { query: string; hits: KbHit[] }

/** 知识库文档条目（/api/kb/documents） */
export interface KbDoc {
  name: string
  size_kb: number
  indexed_chunks: number
  doc_version: string | null
  indexed: boolean
}

export interface KbJob { state: string; detail?: string; chunks?: number }

export interface KbDocsResp {
  documents: KbDoc[]
  total_chunks: number
  job: KbJob
}
