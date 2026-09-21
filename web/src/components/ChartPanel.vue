<template>
  <section class="panel">
    <h3>{{ title }}<span v-if="hint" class="hint">{{ hint }}</span></h3>
    <div v-if="loading" class="state">加载中…</div>
    <div v-else-if="error" class="state error">⚠ {{ error }}</div>
    <v-chart v-else-if="option" class="chart" :class="{ tall }" :option="option" autoresize
             @click="(p: unknown) => emit('chart-click', p)" />
    <div v-else class="state">暂无数据</div>
  </section>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  option: object | null
  loading: boolean
  error: string | null
  /** 主从布局：主图加高（趋势图用） */
  tall?: boolean
  /** 交互提示小字（如"点击格子联动"），非装饰，是可用性指引 */
  hint?: string
}>()

// 点击事件透传（热力图格子联动用；ECharts 事件参数原样上交，由调用方解释）
const emit = defineEmits<{ (e: 'chart-click', p: unknown): void }>()
</script>

<style scoped>
.panel {
  background: var(--card); border: none; border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 16px 18px; display: flex; flex-direction: column;
}
h3 { margin: 0 0 10px; font-size: 13px; font-weight: 600; color: var(--text-unit); letter-spacing: 0.02em; }
.hint { margin-left: 8px; font-size: 11px; font-weight: 400; color: var(--text-label); }
.chart { flex: 1; min-height: 260px; }
.chart.tall { min-height: 420px; }
.state {
  flex: 1; min-height: 260px; display: flex; align-items: center;
  justify-content: center; color: var(--text-label); font-size: 13px;
}
.error { color: var(--sem-alert); }
</style>
