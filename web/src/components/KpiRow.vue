<template>
  <div class="kpi-row">
    <div v-if="error" class="kpi-card state-err">
      <div class="label">KPI 加载失败</div>
      <div class="err-text">{{ error }}</div>
    </div>
    <template v-else>
      <!-- 单位成本：主 KPI，带环比徽章（成本降=绿/升=红，徽章必带 +/- 文字） -->
      <div class="kpi-card" :class="'st-' + unitStatus">
        <div class="label">单位成本</div>
        <div class="num">{{ fmtNum(metrics?.unit_cost) }}</div>
        <div class="delta" :class="'tone-' + unitTone">{{ fmtDelta(metrics?.unit_cost_mom_pct ?? null) }}</div>
      </div>
      <div class="kpi-card st-neutral">
        <div class="label">总成本</div>
        <div class="num">{{ fmtNum(metrics?.total_cost) }}</div>
        <div class="delta-plain">本月发生额</div>
      </div>
      <div class="kpi-card st-neutral">
        <div class="label">产量</div>
        <div class="num">{{ fmtNum(metrics?.output_qty) }}</div>
        <div class="delta-plain">本月产量</div>
      </div>
      <!-- 告警卡：有告警即红（告警=行动入口）；点击滚动到告警区 -->
      <div class="kpi-card clickable" :class="'st-' + alertStatus" @click="scrollToAlerts">
        <div class="label">波动告警</div>
        <div class="num">{{ metrics?.alerts.length ?? 0 }}<span class="unit">条</span></div>
        <div class="delta tone-neutral">{{ metrics?.alerts.length ? '需处理 →' : '无越限' }}</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MetricsResp } from '../types'
import { alertCardStatus, costDeltaTone, fmtDelta, fmtNum, unitCostStatus } from '../kpi'

const props = defineProps<{ metrics: MetricsResp | null; error: string | null }>()

const unitStatus = computed(() =>
  unitCostStatus(props.metrics?.unit_cost_mom_pct ?? null))
const alertStatus = computed(() => alertCardStatus(props.metrics?.alerts.length ?? 0))
const unitTone = computed(() => costDeltaTone(props.metrics?.unit_cost_mom_pct ?? null))

function scrollToAlerts() {
  document.getElementById('alert-section')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
</script>

<style scoped>
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 14px; }
.kpi-card {
  background: var(--card); border: none; border-radius: var(--radius);
  box-shadow: var(--shadow);
  border-left: 4px solid var(--sem-normal); padding: 16px 18px; min-height: 104px;
  transition: box-shadow 0.15s ease;
}
.kpi-card.clickable { cursor: pointer; }
.kpi-card.clickable:hover { box-shadow: var(--shadow-lg); }
.kpi-card.st-alert { border-left-color: var(--sem-alert); }
.kpi-card.st-warn { border-left-color: var(--sem-warn); }
.kpi-card.st-neutral { border-left-color: var(--sem-normal); }
.label { font-size: 12px; color: var(--text-label); margin-bottom: 8px; letter-spacing: 0.03em; }
.num { font-family: var(--font-num); font-size: 30px; font-weight: 700; color: var(--text-num); font-variant-numeric: tabular-nums; line-height: 1.15; }
.unit { font-size: 13px; font-weight: 400; color: var(--text-unit); margin-left: 3px; }
.delta {
  display: inline-block; font-size: 12px; margin-top: 8px; padding: 2px 9px; border-radius: 999px;
}
.tone-good { color: var(--sem-good); background: rgba(39, 160, 108, 0.1); }
.tone-bad { color: var(--sem-alert); background: rgba(192, 57, 43, 0.09); }
.tone-neutral { color: var(--text-unit); background: rgba(133, 150, 165, 0.12); }
.delta-plain { font-size: 12px; margin-top: 8px; color: var(--text-label); }
.state-err { grid-column: 1 / -1; border-left-color: var(--sem-alert); }
.err-text { font-size: 12px; color: var(--sem-alert); word-break: break-all; }
</style>
