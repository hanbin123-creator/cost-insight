<template>
  <!-- F6（选型 V3 分栏对照 + V4 归因链卡片）：左栏报告正文（数字可点击），
       右栏证据列（figures 芯片 + citations 出处），点击正文数字 → 证据高亮定位 -->
  <section class="panel">
    <h3>
      归因分析报告
      <span v-if="demoMode" class="demo-tag">演示模式（样例数据，LLM 未配置）</span>
      <span v-if="report" class="badge" :class="report.verification.verdict">
        {{ badgeText }}
      </span>
    </h3>

    <div v-if="loading" class="state">大模型生成中（含校验闭环）…</div>
    <div v-else-if="error" class="state error">⚠ {{ error }}</div>

    <template v-else-if="report">
      <!-- C2 纪律：rejected 只显示拦截状态与错误清单，正文不渲染 -->
      <div v-if="report.verification.verdict === 'rejected'" class="state error">
        <p><strong>报告未通过系统校验，已自动拦截。</strong></p>
        <ul><li v-for="(e, i) in report.verification.errors" :key="i">{{ e }}</li></ul>
      </div>

      <div v-else class="attr-cols">
        <!-- 左栏：报告正文，数字段渲染为可点按钮 -->
        <div class="attr-text">
          <p class="summary">
            <template v-for="(t, i) in summaryTokens" :key="i">
              <button v-if="t.value !== null" class="fig" @click="lit(t.value)">{{ t.text }}</button>
              <span v-else>{{ t.text }}</span>
            </template>
          </p>

          <!-- 排版选型方案一：材料量价分解表格（代码回填，与正文数字同源） -->
          <div v-if="report.decomposition && report.decomposition.length" class="decomp">
            <div class="decomp-head">
              材料量价分解明细
              <span class="decomp-src">代码计算 · 与正文数字同源</span>
            </div>
            <table class="decomp-table">
              <thead>
                <tr>
                  <th class="l">材料</th><th>价格 (元/kg)</th><th>用量 (kg/盒)</th>
                  <th>价格效应</th><th>用量效应</th><th class="l">口径</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="d in report.decomposition" :key="d.material">
                  <td class="l mname">{{ d.material }}</td>
                  <td class="num" :class="{ flat: d.price_prev === null }">
                    {{ fmtTransition(d.price_prev, d.price_curr, transitionPlaceholder(d)) }}
                  </td>
                  <td class="num" :class="{ flat: d.qty_prev === null }">
                    {{ d.qty_prev === null ? '—' : fmtTransition(d.qty_prev, d.qty_curr, '—') }}
                  </td>
                  <td class="num" :class="effClass(d.price_effect)">{{ fmtEffect(d.price_effect) }}</td>
                  <td class="num" :class="effClass(d.qty_effect)">{{ fmtEffect(d.qty_effect) }}</td>
                  <td class="l src" :class="{ market: d.covered }">{{ methodLabel(d) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-for="(c, ci) in report.causes" :key="ci" class="cause">
            <h4>{{ ci + 1 }}. {{ c.title }}</h4>
            <p>
              <template v-for="(t, i) in causeTokens(ci)" :key="i">
                <button v-if="t.value !== null" class="fig" @click="lit(t.value)">{{ t.text }}</button>
                <span v-else>{{ t.text }}</span>
              </template>
            </p>
          </div>
          <h4>改进建议</h4>
          <ul>
            <li v-for="(s, i) in report.suggestions" :key="i">{{ s }}</li>
          </ul>
          <details v-if="report.verification.verdict === 'auto_fixed'" class="fixed">
            <summary>系统自动补全声明（{{ report.verification.fixed.length }} 条，数字均真实存在于数据包）</summary>
            <ul><li v-for="(f, i) in report.verification.fixed" :key="i">{{ f }}</li></ul>
          </details>
          <p v-if="notFound" class="not-found">该数字未在本报告证据列中登记（正文数字均经校验存在于数据包，此处仅匹配证据芯片）</p>
        </div>

        <!-- 右栏：证据列——每条原因的 figures 芯片 + citations 出处 -->
        <aside class="attr-evidence">
          <div class="evi-head">证据列（点击正文数字可定位）</div>
          <div v-for="(c, ci) in report.causes" :key="ci" class="evi-cause">
            <div class="evi-title">{{ ci + 1 }}. {{ c.title }}</div>
            <div class="chips">
              <span v-for="(f, fi) in c.figures" :key="fi" class="chip"
                :id="`fig-${ci}-${fi}`"
                :class="{ lit: litValue !== null && Math.abs(f - litValue) < 1e-6 }">
                {{ f }}
              </span>
              <span v-if="!c.figures.length" class="chip empty">无数值证据</span>
            </div>
            <ul v-if="c.citations.length" class="cites">
              <li v-for="(ct, i) in c.citations" :key="i">{{ ct }}</li>
            </ul>
          </div>
        </aside>
      </div>
    </template>
    <div v-else class="state">点击「生成归因分析」</div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { findFigIndex, tokenizeFigures } from '../figures'
import { effClass, fmtEffect, fmtTransition, methodLabel, transitionPlaceholder } from '../decomp'
import type { AttributionResp } from '../types'

const props = defineProps<{
  report: AttributionResp | null
  loading: boolean
  error: string | null
  demoMode: boolean
}>()

const badgeText = computed(() => {
  if (!props.report) return ''
  const v = props.report.verification
  return v.verdict === 'pass' ? '✅ 校验通过'
    : v.verdict === 'auto_fixed' ? '⚠️ 通过（含自动补全）' : '❌ 已拦截'
})

// 正文数字 → 可点 token（纯函数，显示层摆放）
const summaryTokens = computed(() =>
  props.report ? tokenizeFigures(props.report.summary) : [])
const causeTokens = computed(() => (ci: number) =>
  tokenizeFigures(props.report?.causes[ci]?.detail ?? ''))

// 点击联动：正文数字 → 右栏证据芯片高亮 + 滚动定位
const litValue = ref<number | null>(null)
const notFound = ref(false)
let nfTimer: ReturnType<typeof setTimeout> | undefined
function lit(v: number) {
  litValue.value = v
  const hit = props.report?.causes.some((c) => findFigIndex(v, c.figures) >= 0)
  notFound.value = !hit
  clearTimeout(nfTimer)
  if (!hit) { nfTimer = setTimeout(() => { notFound.value = false }, 2600); return }
  // 找到第一枚匹配芯片并滚入视野（高亮由 litValue 驱动，所有同值芯片同时亮）
  const ci = props.report!.causes.findIndex((c) => findFigIndex(v, c.figures) >= 0)
  const fi = findFigIndex(v, props.report!.causes[ci]!.figures)
  document.getElementById(`fig-${ci}-${fi}`)
    ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}
</script>

<style scoped>
.panel {
  background: var(--card); border: none; border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 16px 18px; font-size: 14px; line-height: 1.7;
}
h3 { margin: 0 0 10px; font-size: 13px; font-weight: 600; color: var(--text-unit);
  letter-spacing: 0.02em; display: flex; align-items: center; gap: 10px; }
.badge { font-size: 12px; padding: 2px 10px; border-radius: 12px; }
.badge.pass { background: #e8f6ef; color: #1e8449; }
.badge.auto_fixed { background: #fef5e7; color: #b9770e; }
.badge.rejected { background: #fdedec; color: #c0392b; }
.demo-tag { font-size: 12px; color: var(--text-label); font-weight: normal; }

.attr-cols { display: grid; grid-template-columns: 1.4fr 1fr; gap: 18px; }
@container (max-width: 700px) { .attr-cols { grid-template-columns: 1fr; } }

.attr-text .summary { font-weight: 600; color: var(--text-num); margin-top: 0; }

/* 量价分解表格（排版选型方案一）：效应负=绿（降本），正=红（升本），与热力图同口径 */
.decomp { margin: 10px 0 4px; border: 1px solid rgba(93, 109, 126, 0.14); border-radius: 10px; overflow: hidden; }
.decomp-head {
  font-size: 12px; font-weight: 600; color: var(--text-unit);
  padding: 8px 12px; background: rgba(93, 109, 126, 0.05);
  display: flex; align-items: baseline; gap: 8px;
}
.decomp-src { font-size: 11px; font-weight: 400; color: var(--text-label); }
.decomp-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.decomp-table th {
  padding: 7px 10px; font-size: 11px; font-weight: 600; color: var(--text-label);
  border-bottom: 1.5px solid rgba(93, 109, 126, 0.16); text-align: right; white-space: nowrap;
}
.decomp-table th.l, .decomp-table td.l { text-align: left; }
.decomp-table td {
  padding: 7px 10px; border-bottom: 1px solid rgba(93, 109, 126, 0.07);
  text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap;
}
.decomp-table tr:last-child td { border-bottom: none; }
.decomp-table .mname { font-weight: 600; color: var(--text-num); }
.decomp-table .dn { color: #3d8a6f; font-weight: 600; }
.decomp-table .up { color: #c05a4b; font-weight: 600; }
.decomp-table .flat { color: var(--text-label); font-weight: 400; }
.decomp-table .src { font-size: 11px; color: var(--text-label); }
.decomp-table .src.market { color: var(--primary); }
.cause h4 { margin: 12px 0 4px; color: var(--text-unit); font-size: 13.5px; }
.cause p { margin: 0; }
.fixed { margin-top: 10px; font-size: 12px; color: #b9770e; }
.not-found { font-size: 12px; color: var(--text-label); }

/* 正文中可点的数字：主色下划线样式，暗示"有证据" */
.fig {
  border: none; background: none; padding: 0 1px; cursor: pointer;
  color: var(--primary); font: inherit; font-weight: 600;
  border-bottom: 1px dashed rgba(46, 109, 164, 0.55); border-radius: 2px;
}
.fig:hover { background: rgba(46, 109, 164, 0.1); }

.attr-evidence {
  background: rgba(93, 109, 126, 0.05); border-radius: 12px; padding: 12px 14px;
  align-self: start; font-size: 12.5px;
}
.evi-head { font-weight: 600; color: var(--text-unit); margin-bottom: 8px; }
.evi-cause { margin-bottom: 12px; }
.evi-title { color: var(--text-num); font-weight: 600; margin-bottom: 5px; }
.chips { display: flex; flex-wrap: wrap; gap: 5px; }
.chip {
  background: #fff; border-radius: 8px; padding: 2px 8px; font-size: 12px;
  color: var(--text-num); box-shadow: var(--shadow);
  font-variant-numeric: tabular-nums; transition: box-shadow 0.2s ease, outline 0.2s ease;
  outline: 2px solid transparent;
}
.chip.lit { outline-color: var(--primary); box-shadow: 0 0 0 4px rgba(46, 109, 164, 0.18); }
.chip.empty { color: var(--text-label); box-shadow: none; background: none; }
.cites { margin: 6px 0 0; padding-left: 16px; color: var(--text-label); font-size: 11.5px; }

.state { min-height: 120px; display: flex; flex-direction: column; justify-content: center; color: var(--text-label); }
.error { color: var(--sem-alert); }
</style>
