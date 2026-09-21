<template>
  <!-- F7 整改追踪（选型 V1 看板三列 + V5 告警卡联动）：状态真源在 RPA 侧，
       实时拉取聚合；RPA 不可达如实展示，不展示假数据 -->
  <div class="rectify">
    <section class="panel head-bar">
      <div class="agg" v-if="data?.aggregate">
        <div class="agg-item"><span class="agg-num">{{ data.aggregate.已生成 }}</span><span class="agg-label">已生成</span></div>
        <div class="agg-item"><span class="agg-num">{{ data.aggregate.已送达 }}</span><span class="agg-label">已送达</span></div>
        <div class="agg-item"><span class="agg-num">{{ data.aggregate.已确认 }}</span><span class="agg-label">已确认</span></div>
        <div class="agg-prio">
          <span v-for="(n, p) in data.aggregate.by_priority" :key="p" class="prio" :class="String(p)">
            {{ p }} {{ n }}
          </span>
        </div>
      </div>
      <div class="head-actions">
        <select v-model="speed" aria-label="演示速度">
          <option value="">标准下发</option>
          <option value="FAST">演示·快速闭环</option>
          <option value="DONE">演示·直接完成</option>
          <option value="OVERDUE">演示·逾期</option>
        </select>
        <button class="dispatch-btn" :disabled="dispatching" @click="dispatchNow">
          {{ dispatching ? '下发中…' : `下发整改（${store.product} · ${store.month}）` }}
        </button>
        <button class="refresh-btn" @click="refresh">刷新</button>
      </div>
    </section>

    <p v-if="dispatchNote" class="dispatch-note" :class="{ err: dispatchErr, warn: dispatchWarn && !dispatchErr }">{{ dispatchNote }}</p>

    <!-- RPA 不可达：如实状态卡（不展示假数据），给出恢复路径 -->
    <section v-if="data && !data.ok" class="panel unreachable">
      <h3>⚠ RPA 服务不可达</h3>
      <p>{{ data.error }}</p>
      <p class="hint-line">任务下发仍会落库为 dispatch_failed；启动官方 mock 服务后点「刷新」即可看到真实状态聚合。</p>
    </section>

    <!-- 看板三列 -->
    <div v-if="data?.ok" class="kanban">
      <section v-for="col in cols" :key="col" class="kcol panel">
        <h3>{{ KANBAN_TITLES[col] }}<span class="count">{{ grouped[col].length }}</span></h3>
        <div v-if="!grouped[col].length" class="empty">暂无任务</div>
        <article v-for="(t, i) in grouped[col]" :key="t.task_id ?? i" class="kcard">
          <div class="k-title">{{ t.title ?? t.task_id }}</div>
          <div class="k-meta">
            <span v-if="t.assignee">{{ t.assignee }}</span>
            <span v-if="t.department">（{{ t.department }}）</span>
          </div>
          <div class="k-meta">
            <span v-if="t.deadline">截止 {{ t.deadline }}</span>
            <span v-if="t.priority" class="prio" :class="t.priority">{{ t.priority }}</span>
          </div>
          <div class="k-status">状态：{{ t.status ?? '—' }}</div>
        </article>
      </section>
    </div>

    <div v-if="loading" class="state">加载中…</div>
    <div v-else-if="loadError" class="state error">⚠ {{ loadError }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { groupTasks, KANBAN_TITLES, type KanbanCol } from '../agentCards'
import { store } from '../store'
import type { TrackingResp } from '../types'

const data = ref<TrackingResp | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)

const cols: KanbanCol[] = ['todo', 'doing', 'done']
const grouped = computed(() => groupTasks(data.value?.tasks ?? []))

// 演示下发：speed 后缀驱动官方 mock 状态机（FAST/DONE/OVERDUE）
const speed = ref('')
const dispatching = ref(false)
const dispatchNote = ref('')
const dispatchErr = ref(false)
const dispatchWarn = ref(false)

async function refresh() {
  loading.value = true
  loadError.value = null
  try { data.value = await api.rectifyTracking() }
  catch (e) { data.value = null; loadError.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}

async function dispatchNow() {
  dispatching.value = true
  dispatchNote.value = ''
  dispatchErr.value = false
  dispatchWarn.value = false
  try {
    const r = await api.rectifyDispatch(store.product, store.month, speed.value || undefined)
    const failed = r.tasks.filter((t) => t.dispatch === 'dispatch_failed').length
    if (r.tasks.length) {
      const resentNote = r.resent ? `，其中 ${r.resent} 个为补发（对方服务重启后恢复）` : ''
      dispatchNote.value = `装配 ${r.tasks.length} 个任务${failed ? `，其中 ${failed} 个 RPA 不可达已落库 dispatch_failed` : '，已发送'}${resentNote}`
    } else {
      dispatchNote.value = r.note ?? '无可下发任务'
    }
    // 问题一修复：本地记已发但未能远程核实 → 琥珀色"待核实"警示，不假装一切正常
    if (failed) dispatchErr.value = true
    else if (r.unverified) dispatchWarn.value = true
    await refresh()
  } catch (e) {
    dispatchNote.value = `下发失败：${e instanceof Error ? e.message : String(e)}`
    dispatchErr.value = true
  } finally {
    dispatching.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.rectify { display: flex; flex-direction: column; gap: 14px; }
.panel {
  background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 14px 18px;
}
.head-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
.agg { display: flex; align-items: center; gap: 22px; }
.agg-item { display: flex; flex-direction: column; align-items: center; }
.agg-num { font-size: 24px; font-weight: 700; color: var(--text-num); font-variant-numeric: tabular-nums; }
.agg-label { font-size: 11px; color: var(--text-label); }
.agg-prio { display: flex; gap: 6px; margin-left: 6px; }
.prio { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: rgba(93, 109, 126, 0.1); color: var(--text-unit); }
.prio.高 { background: rgba(192, 57, 43, 0.12); color: #c0392b; }
.prio.中 { background: rgba(242, 142, 44, 0.14); color: #b9770e; }
.head-actions { display: flex; gap: 8px; align-items: center; }
select {
  padding: 8px 12px; border-radius: 10px; border: none; background: rgba(93, 109, 126, 0.08);
  font-size: 12.5px; color: var(--text-num); cursor: pointer;
}
.dispatch-btn {
  border: none; border-radius: 10px; padding: 9px 16px; cursor: pointer;
  background: var(--primary); color: #fff; font-size: 13px;
  box-shadow: 0 3px 10px rgba(46, 109, 164, 0.3);
}
.dispatch-btn:disabled { opacity: 0.6; cursor: wait; }
.refresh-btn {
  border: none; border-radius: 10px; padding: 9px 14px; cursor: pointer;
  background: rgba(93, 109, 126, 0.1); color: var(--text-unit); font-size: 13px;
}
.dispatch-note { margin: 0; font-size: 12.5px; color: #1e8449; }
.dispatch-note.err { color: #c0392b; }
.dispatch-note.warn { color: #b9770e; }
.unreachable h3 { margin: 0 0 8px; font-size: 14px; color: var(--sem-alert); }
.unreachable p { margin: 4px 0; font-size: 12.5px; color: var(--text-num); }
.hint-line { color: var(--text-label) !important; }
.kanban { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; align-items: start; }
@container (max-width: 700px) { .kanban { grid-template-columns: 1fr; } }
.kcol h3 { margin: 0 0 10px; font-size: 13px; font-weight: 600; color: var(--text-unit); }
.count {
  margin-left: 8px; font-size: 11px; color: var(--text-label);
  background: rgba(93, 109, 126, 0.1); border-radius: 999px; padding: 1px 8px;
}
.empty { color: var(--text-label); font-size: 12.5px; padding: 14px 0; text-align: center; }
.kcard {
  background: #fff; border-radius: 10px; padding: 10px 12px; margin-bottom: 8px;
  box-shadow: var(--shadow); font-size: 12.5px;
}
.k-title { font-weight: 600; color: var(--text-num); margin-bottom: 5px; line-height: 1.45; }
.k-meta { color: var(--text-label); font-size: 11.5px; display: flex; gap: 6px; align-items: center; margin-top: 2px; }
.k-status { margin-top: 6px; font-size: 11px; color: var(--text-label); }
.state { min-height: 160px; display: flex; align-items: center; justify-content: center; color: var(--text-label); }
.state.error { color: var(--sem-alert); }
</style>
