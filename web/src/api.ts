/** API 访问层：所有请求集中于此；错误统一抛出由面板三态展示 */
import type {
  AttributionResp, BenchmarkResp, ChatResp, DecisionResp, ForecastResp, HeatmapResp,
  KbDocsResp, KbQueryResp, MetricsResp, ProductsResp, RectifyDispatchResp, ReportGenResp,
  ReportsResp, SeriesResp, StructureResp, TrackingResp, WaterfallResp,
} from './types'

const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

export const api = {
  products: () => get<ProductsResp>('/products'),
  series: (p: string) => get<SeriesResp>(`/series/${encodeURIComponent(p)}`),
  waterfall: (p: string, m: string) =>
    get<WaterfallResp>(`/charts/waterfall/${encodeURIComponent(p)}/${m}`),
  structure: (p: string, m: string) =>
    get<StructureResp>(`/charts/structure/${encodeURIComponent(p)}/${m}`),
  heatmap: () => get<HeatmapResp>('/charts/heatmap'),
  metrics: (p: string, m: string) =>
    get<MetricsResp>(`/metrics/${encodeURIComponent(p)}/${m}`),
  decision: (p: string, m: string) =>
    get<DecisionResp>(`/agent/decision/${encodeURIComponent(p)}/${m}`),
  forecast: (p: string) => get<ForecastResp>(`/forecast/${encodeURIComponent(p)}`),
  attribution: (p: string, m: string) =>
    post<AttributionResp>('/attribution', { product: p, month: m }),
  rectifyDispatch: (p: string, m: string, speed?: string) =>
    post<RectifyDispatchResp>('/rectify/dispatch', { product: p, month: m, speed }),
  benchmark: (p: string, m: string) =>
    get<BenchmarkResp>(`/benchmark/${encodeURIComponent(p)}/${m}`),
  chat: (text: string, p?: string, m?: string) =>
    post<ChatResp>('/chat', { text, product: p, month: m }),
  rectifyTracking: () => get<TrackingResp>('/rectify/tracking'),
  // F8 报告中心
  reports: () => get<ReportsResp>('/reports'),
  reportUrl: (name: string) => `${BASE}/reports/${encodeURIComponent(name)}`,
  generateReport: (product: string, theme: 'monthly' | 'quarterly' | 'topical',
    month?: string, quarter?: string) =>
    post<ReportGenResp>('/report', { product, theme, month, quarter }),
  // F10 知识库
  kbQuery: (q: string, topK = 5) =>
    get<KbQueryResp>(`/kb/query?q=${encodeURIComponent(q)}&top_k=${topK}`),
  kbDocs: () => get<KbDocsResp>('/kb/documents'),
  kbUpload: (filename: string, contentB64: string) =>
    post<{ accepted: boolean; filename: string; note: string }>(
      '/kb/documents', { filename, content_b64: contentB64 }),
  kbDelete: (name: string) =>
    del<{ deleted: string }>(`/kb/documents/${encodeURIComponent(name)}`),
}

async function del<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json() as Promise<T>
}

/** 演示模式：LLM 未配置时加载经校验闭环固化的样例（页面必须标注演示模式） */
export async function loadDemoAttribution(): Promise<AttributionResp> {
  const r = await fetch('/fixtures/demo_attribution.json')
  if (!r.ok) throw new Error('演示样例缺失')
  return r.json() as Promise<AttributionResp>
}
