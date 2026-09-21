<template>
  <!-- F8 报告中心（选型 V3 时间轴归档 + 顶部新建操作条）：
       报告生成/校验全部后端完成，本页只负责参数收集、进度呈现与归档展示 -->
  <div class="reports">
    <!-- 新建报告操作条 -->
    <section class="panel action-bar">
      <div class="ab-left">
        <span class="ab-title">新建报告</span>
        <button v-for="t in THEMES" :key="t.key" class="theme-btn"
          :disabled="generating" @click="openDialog(t.key)">
          {{ t.label }}
        </button>
      </div>
      <button class="refresh-btn" :disabled="generating" @click="refresh">刷新归档</button>
    </section>

    <!-- 生成进度 / 结果条 -->
    <p v-if="genNote" class="gen-note" :class="{ err: genErr }">{{ genNote }}</p>

    <!-- 参数弹窗 -->
    <div v-if="dialog" class="dialog-mask" @click.self="dialog = null">
      <section class="dialog panel">
        <h3>{{ dialogLabel }}</h3>
        <label>产品
          <select v-model="form.product">
            <option v-for="p in products" :key="p" :value="p">{{ p }}</option>
          </select>
        </label>
        <label v-if="dialog === 'quarterly'">季度
          <select v-model="form.quarter">
            <option value="Q1">Q1（1–3 月）</option>
            <option value="Q2">Q2（4–6 月）</option>
          </select>
        </label>
        <label v-else>月份
          <select v-model="form.month">
            <option v-for="m in months" :key="m" :value="m">{{ m }}</option>
          </select>
        </label>
        <p v-if="formErr" class="form-err">{{ formErr }}</p>
        <div class="dialog-actions">
          <button class="cancel" :disabled="generating" @click="dialog = null">取消</button>
          <button class="confirm" :disabled="generating" @click="generate">
            {{ generating ? '生成中…（图表/校验/排版约 1–3 分钟）' : '开始生成' }}
          </button>
        </div>
      </section>
    </div>

    <!-- 时间轴归档（服务端已按 mtime 倒序） -->
    <section class="panel timeline">
      <h3>报告归档<span class="count">{{ data?.reports.length ?? 0 }}</span></h3>
      <div v-if="loading" class="state">加载中…</div>
      <div v-else-if="loadError" class="state error">⚠ {{ loadError }}</div>
      <div v-else-if="!data?.reports.length" class="state">暂无归档报告，用上方操作条生成第一份</div>
      <div v-else class="tl-list">
        <article v-for="r in data.reports" :key="r.product + r.period + r.theme" class="tl-item">
          <div class="tl-node" :class="`t-${themeLabel(r.theme)}`"></div>
          <div class="tl-body">
            <div class="tl-head">
              <span class="tl-theme">{{ themeLabel(r.theme) }}</span>
              <strong>{{ r.product }} · {{ r.period }}</strong>
              <span class="tl-time">{{ fmtMtime(r.mtime) }}</span>
            </div>
            <div class="tl-files">
              <a v-if="r.docx" :href="api.reportUrl(r.docx.name)" :download="r.docx.name" class="file">
                Word · {{ fmtSize(r.docx.size_kb) }}
              </a>
              <a v-if="r.pdf" :href="api.reportUrl(r.pdf.name)" :download="r.pdf.name" class="file">
                PDF · {{ fmtSize(r.pdf.size_kb) }}
              </a>
              <span v-if="!r.pdf" class="file none">PDF 未出（本机 LibreOffice 不可达时如实缺省）</span>
            </div>
          </div>
        </article>
      </div>
      <p v-if="data?.unknown_files.length" class="unknown">
        未识别文件（命名不合规，未归档）：{{ data.unknown_files.join('、') }}
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { fmtMtime, fmtSize, themeLabel, validateReportParams } from '../archiveHelpers'
import { store } from '../store'
import type { ReportsResp } from '../types'

const THEMES = [
  { key: 'monthly', label: '月度报告' },
  { key: 'quarterly', label: '季度报告' },
  { key: 'topical', label: '专题报告' },
] as const
type ThemeKey = (typeof THEMES)[number]['key']

const data = ref<ReportsResp | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)

const products = ref<string[]>([store.product])
const months = ref<string[]>([store.month])

const dialog = ref<ThemeKey | null>(null)
const dialogLabel = ref('')
const form = ref({ product: store.product, month: store.month, quarter: 'Q2' })
const formErr = ref('')
const generating = ref(false)
const genNote = ref('')
const genErr = ref(false)

async function refresh() {
  loading.value = true
  loadError.value = null
  try { data.value = await api.reports() }
  catch (e) { data.value = null; loadError.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}

function openDialog(theme: ThemeKey) {
  dialog.value = theme
  dialogLabel.value = `新建${THEMES.find((t) => t.key === theme)!.label}`
  formErr.value = ''
  genNote.value = ''
}

async function generate() {
  if (!dialog.value) return
  const err = validateReportParams(dialog.value, form.value.product, form.value.month, form.value.quarter)
  if (err) { formErr.value = err; return }
  generating.value = true
  genErr.value = false
  genNote.value = ''
  try {
    const r = await api.generateReport(
      form.value.product, dialog.value,
      dialog.value === 'quarterly' ? undefined : form.value.month,
      dialog.value === 'quarterly' ? form.value.quarter : undefined)
    const warns = r.warnings.length ? `；注意：${r.warnings.join('；')}` : ''
    genNote.value = `生成完成（校验 ${r.verification.verdict}）${warns}，已入归档`
    dialog.value = null
    await refresh()
  } catch (e) {
    genNote.value = `生成失败：${e instanceof Error ? e.message : String(e)}`
    genErr.value = true
  } finally {
    generating.value = false
  }
}

onMounted(async () => {
  refresh()
  try {
    const p = await api.products()
    products.value = p.products
    months.value = p.months
  } catch { /* 下拉退回当前上下文值，不阻断归档展示 */ }
})
</script>

<style scoped>
.reports { display: flex; flex-direction: column; gap: 14px; }
.panel { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); padding: 14px 18px; }

.action-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.ab-left { display: flex; align-items: center; gap: 10px; }
.ab-title { font-size: 13px; font-weight: 600; color: var(--text-unit); margin-right: 2px; }
.theme-btn {
  border: none; border-radius: 10px; padding: 9px 16px; cursor: pointer;
  background: var(--primary); color: #fff; font-size: 13px;
  box-shadow: 0 3px 10px rgba(46, 109, 164, 0.3);
}
.theme-btn:disabled { opacity: 0.6; cursor: wait; }
.refresh-btn {
  border: none; border-radius: 10px; padding: 9px 14px; cursor: pointer;
  background: rgba(93, 109, 126, 0.1); color: var(--text-unit); font-size: 13px;
}
.gen-note { margin: 0; font-size: 12.5px; color: #1e8449; }
.gen-note.err { color: #c0392b; }

.dialog-mask {
  position: fixed; inset: 0; z-index: 60; background: rgba(30, 41, 59, 0.35);
  display: flex; align-items: center; justify-content: center;
}
.dialog { width: 320px; display: flex; flex-direction: column; gap: 12px; }
.dialog h3 { margin: 0; font-size: 15px; color: var(--text-num); }
.dialog label { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--text-label); }
.dialog select {
  padding: 8px 12px; border-radius: 10px; border: none;
  background: rgba(93, 109, 126, 0.08); font-size: 13px; color: var(--text-num); cursor: pointer;
}
.form-err { margin: 0; font-size: 12px; color: #c0392b; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.cancel { border: none; background: none; cursor: pointer; color: var(--text-label); font-size: 12.5px; }
.confirm {
  border: none; border-radius: 10px; padding: 8px 16px; cursor: pointer;
  background: var(--primary); color: #fff; font-size: 12.5px;
}
.confirm:disabled { opacity: 0.6; cursor: wait; }

.timeline h3 { margin: 0 0 12px; font-size: 13px; font-weight: 600; color: var(--text-unit); }
.count {
  margin-left: 8px; font-size: 11px; color: var(--text-label);
  background: rgba(93, 109, 126, 0.1); border-radius: 999px; padding: 1px 8px;
}
.tl-list { display: flex; flex-direction: column; }
.tl-item { display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid #eef1f6; }
.tl-item:last-child { border-bottom: none; }
.tl-node {
  flex: none; width: 10px; height: 10px; border-radius: 50%; margin-top: 5px;
  background: var(--primary); box-shadow: 0 0 0 3px rgba(46, 109, 164, 0.15);
}
.tl-node.t-季报 { background: #7a5fa0; box-shadow: 0 0 0 3px rgba(122, 95, 160, 0.15); }
.tl-node.t-专题 { background: #b9770e; box-shadow: 0 0 0 3px rgba(185, 119, 14, 0.15); }
.tl-body { flex: 1; min-width: 0; }
.tl-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.tl-theme {
  font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
  background: rgba(46, 109, 164, 0.1); color: var(--primary);
}
.tl-head strong { font-size: 13.5px; color: var(--text-num); }
.tl-time { margin-left: auto; font-size: 11px; color: var(--text-label); font-variant-numeric: tabular-nums; }
.tl-files { display: flex; gap: 10px; margin-top: 6px; flex-wrap: wrap; }
a.file {
  font-size: 12px; color: var(--primary); text-decoration: none;
  padding: 3px 10px; border-radius: 8px; background: rgba(46, 109, 164, 0.08);
}
a.file:hover { background: rgba(46, 109, 164, 0.16); }
.file.none { font-size: 11.5px; color: var(--text-label); }
.unknown { margin: 10px 0 0; font-size: 11.5px; color: var(--sem-alert); }
.state { min-height: 120px; display: flex; align-items: center; justify-content: center; color: var(--text-label); }
.state.error { color: var(--sem-alert); }
</style>
