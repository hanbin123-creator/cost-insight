<template>
  <div>
    <!-- F2：KPI 看板行（大数字卡 + 语义色边条，≤6 卡） -->
    <KpiRow :metrics="metrics" :error="metricsError" />

    <!-- Agent 决策横幅：系统自主判断并说明理由（F5 增量将升级为抽屉+决策卡流） -->
    <div v-if="decision" class="decision" :class="decision.action">
      🤖 Agent 决策（{{ decision.engine }}）：{{ decision.action === 'generate_attribution' ? '建议生成归因报告' : '仅更新看板' }}——{{ decision.reason }}
    </div>

    <!-- F8 V4：首页最新报告卡（归档真源在报告中心；加载失败静默隐藏，不抢主视线） -->
    <div v-if="latestReport" class="latest-report">
      <span class="lr-theme">{{ themeLabel(latestReport.theme) }}</span>
      <span class="lr-title">最新报告：{{ latestReport.product }} · {{ latestReport.period }}</span>
      <a v-if="latestReport.docx" :href="api.reportUrl(latestReport.docx.name)"
        :download="latestReport.docx.name">Word</a>
      <a v-if="latestReport.pdf" :href="api.reportUrl(latestReport.pdf.name)"
        :download="latestReport.pdf.name">PDF</a>
      <button class="lr-more" @click="navigate('reports')">报告中心 →</button>
    </div>

    <!-- F3：告警行动卡片列——每条告警可处置：确认 / 生成归因 / 下发整改 -->
    <AlertActionCards v-if="metrics && metrics.alerts.length"
      :alerts="metrics.alerts" :product="store.product" :month="store.month"
      :attr-loading="attrLoading" @generate="generateFromAlert" />

    <!-- F4：主从布局——趋势主图（2/3 宽加高）＋ 右侧结构/瀑布堆叠 ＋ 热力图全宽沉底 -->
    <main class="grid">
      <ChartPanel class="area-trend" title="趋势图 · 近6月单位成本与要素走势"
        :option="trendOpt" :loading="loading.trend" :error="errors.trend" tall />
      <div class="area-side">
        <ChartPanel title="结构图 · 本月成本构成" :option="structureOpt"
          :loading="loading.structure" :error="errors.structure" />
        <ChartPanel title="瀑布图 · 成本变动分解" :option="waterfallOpt"
          :loading="loading.waterfall" :error="errors.waterfall" />
      </div>
      <ChartPanel class="area-heat" title="热力图 · 产品×月份×要素环比（加分项）"
        hint="点击格子可切换看板的产品与月份"
        :option="heatmapOpt" :loading="loading.heatmap" :error="errors.heatmap"
        @chart-click="onHeatClick" />
    </main>

    <div class="gen-bar">
      <button :disabled="attrLoading" @click="generate">
        {{ attrLoading ? '生成中…' : '生成归因分析' }}
      </button>
    </div>

    <AttributionPanel id="attr-panel" :report="report" :loading="attrLoading"
      :error="attrError" :demo-mode="demoMode" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, loadDemoAttribution } from '../api'
import { themeLabel } from '../archiveHelpers'
import { navigate } from '../router'
import { store } from '../store'
import { heatmapOption, structureOption, trendOption, waterfallOption } from '../charts/options'
import ChartPanel from '../components/ChartPanel.vue'
import AttributionPanel from '../components/AttributionPanel.vue'
import AlertActionCards from '../components/AlertActionCards.vue'
import KpiRow from '../components/KpiRow.vue'
import type {
  AttributionResp, DecisionResp, ForecastResp, HeatmapResp, MetricsResp,
  ReportItem, SeriesResp, StructureResp, WaterfallResp,
} from '../types'

// F8 V4：首页最新报告卡（服务端已按 mtime 倒序，取第一条）
const latestReport = ref<ReportItem | null>(null)
onMounted(async () => {
  try { latestReport.value = (await api.reports()).reports[0] ?? null }
  catch { latestReport.value = null }
})

const seriesData = ref<SeriesResp | null>(null)
const forecastData = ref<ForecastResp | null>(null)
const waterfallData = ref<WaterfallResp | null>(null)
const structureData = ref<StructureResp | null>(null)
const heatmapData = ref<HeatmapResp | null>(null)
const metrics = ref<MetricsResp | null>(null)
const metricsError = ref<string | null>(null)
const decision = ref<DecisionResp | null>(null)
const report = ref<AttributionResp | null>(null)
const demoMode = ref(false)
const attrLoading = ref(false)
const attrError = ref<string | null>(null)

const loading = reactive({ trend: false, waterfall: false, structure: false, heatmap: false })
const errors = reactive<Record<string, string | null>>({
  trend: null, waterfall: null, structure: null, heatmap: null,
})

const trendOpt = computed(() =>
  (seriesData.value
    ? trendOption(seriesData.value, forecastData.value,
        // F3 V4 联动：当前月有告警时主线钉红色 pin（数量=告警条数）
        metrics.value?.alerts.length
          ? { month: store.month, count: metrics.value.alerts.length }
          : null)
    : null))
const waterfallOpt = computed(() => (waterfallData.value ? waterfallOption(waterfallData.value) : null))
const structureOpt = computed(() => (structureData.value ? structureOption(structureData.value) : null))
// F4 V4 联动：当前 产品×月份 在热力图上描边高亮
const heatmapOpt = computed(() =>
  (heatmapData.value
    ? heatmapOption(heatmapData.value, { product: store.product, month: store.month })
    : null))

/** 热力图点格联动：行名"产品·要素"解析出产品，列即月份，写回全局筛选（watcher 自动刷新） */
function onHeatClick(p: unknown) {
  const d = (p as { data?: [number, number, number | null] }).data
  const h = heatmapData.value
  if (!d || !h) return
  const product = (h.rows[d[1]] ?? '').split('·')[0]
  const month = h.months[d[0]]
  if (!product || !month || !store.products.includes(product)) return
  if (product === store.product && month === store.month) return  // 已是当前选中
  store.product = product
  store.month = month
}

/** 告警卡"生成归因"入口：复用主生成流程，并把归因面板滚动进视野 */
async function generateFromAlert() {
  await generate()
  document.getElementById('attr-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function guard<T>(key: keyof typeof loading, fn: () => Promise<T>, set: (v: T) => void) {
  loading[key] = true
  errors[key] = null
  try { set(await fn()) } catch (e) { errors[key] = e instanceof Error ? e.message : String(e) }
  finally { loading[key] = false }
}

async function refresh() {
  report.value = null
  demoMode.value = false
  attrError.value = null
  guard('trend', () => api.series(store.product), (v) => { seriesData.value = v })
  // 预测为增强层：失败时趋势图照常渲染（无延伸带），不阻断主流程——错误仍在 console 留痕
  api.forecast(store.product)
    .then((v) => { forecastData.value = v })
    .catch((e) => { forecastData.value = null; console.warn('预测延伸带加载失败（已降级）', e) })
  guard('structure', () => api.structure(store.product, store.month), (v) => { structureData.value = v })
  guard('waterfall', () => api.waterfall(store.product, store.month), (v) => { waterfallData.value = v })
  guard('heatmap', () => api.heatmap(), (v) => { heatmapData.value = v })
  metricsError.value = null
  try { metrics.value = await api.metrics(store.product, store.month) }
  catch (e) { metrics.value = null; metricsError.value = e instanceof Error ? e.message : String(e) }
  try { decision.value = await api.decision(store.product, store.month) } catch { decision.value = null }
}

async function generate() {
  attrLoading.value = true
  attrError.value = null
  try {
    report.value = await api.attribution(store.product, store.month)
    demoMode.value = false
  } catch (e) {
    // LLM 未配置（503）→ 演示模式：加载经校验闭环的固化样例并明确标注
    try {
      report.value = await loadDemoAttribution()
      demoMode.value = true
    } catch {
      attrError.value = e instanceof Error ? e.message : String(e)
    }
  } finally {
    attrLoading.value = false
  }
}

watch(() => [store.product, store.month], refresh, { immediate: true })

// F5 决策卡片流：Agent 抽屉"确认生成归因"跨视图触发（计数器变化即执行）
watch(() => store.attributionRequest, (n, o) => {
  if (n > o) generateFromAlert()
})
</script>

<style scoped>
.decision {
  margin: 0 0 14px; padding: 11px 16px; border-radius: 12px; font-size: 13px;
  background: #eae7f6; border: none; color: #3b2f75; box-shadow: var(--shadow);
}
.decision.dashboard_only { background: var(--card); color: var(--text-unit); }

/* F8 V4：首页最新报告卡 */
.latest-report {
  margin: 0 0 14px; padding: 10px 16px; border-radius: 12px; font-size: 12.5px;
  background: var(--card); box-shadow: var(--shadow);
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.lr-theme {
  font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
  background: rgba(46, 109, 164, 0.1); color: var(--primary);
}
.lr-title { color: var(--text-num); font-weight: 600; }
.latest-report a { color: var(--primary); text-decoration: none; font-size: 12px; }
.latest-report a:hover { text-decoration: underline; }
.lr-more {
  margin-left: auto; border: none; background: none; cursor: pointer;
  color: var(--text-label); font-size: 12px;
}
.lr-more:hover { color: var(--primary); }
.grid {
  display: grid; gap: 14px; margin-bottom: 14px;
  grid-template-columns: 1.6fr 1fr;
  grid-template-areas: "trend side" "heat heat";
}
/* ECharts 初始化后容器带内联像素宽，grid 项默认 min-width:auto 会被它顶爆——
   必须显式 min-width:0 允许收缩（实测趋势列被挤到 49px 的缺陷） */
.area-trend { grid-area: trend; min-width: 0; }
.area-side { grid-area: side; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.area-side > * { flex: 1; min-width: 0; }
.area-side :deep(.chart) { min-height: 220px; }  /* 侧列两张小图：给主图让出纵向空间 */
.area-heat { grid-area: heat; min-width: 0; }
@container (max-width: 600px) {
  /* 内容区过窄（如侧栏展开时的 742px 面板 → 479px）→ 单列堆叠保可读性；
     收起侧栏内容区 619px → 自动恢复主从布局（容器查询感知侧栏状态） */
  .grid { grid-template-columns: 1fr; grid-template-areas: "trend" "side" "heat"; }
}
.gen-bar { margin-bottom: 14px; }
.gen-bar button {
  padding: 10px 22px; border-radius: 10px; border: none; cursor: pointer;
  background: var(--primary); color: #fff; font-size: 14px;
  box-shadow: 0 3px 10px rgba(46, 109, 164, 0.3); transition: background 0.15s ease;
}
.gen-bar button:hover:not(:disabled) { background: var(--primary-hover); }
.gen-bar button:disabled { background: #95a5a6; box-shadow: none; cursor: wait; }
</style>
