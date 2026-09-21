<template>
  <!-- F3（选型 V3 行动卡 + V4 图表联动）：告警从"只读横幅"升级为"可处置卡片列"。
       每条告警三个动作：确认（本地消单）/ 生成归因（联动归因面板）/ 下发整改（RPA） -->
  <section class="alert-cards" aria-label="波动告警处置">
    <header class="cards-head">
      <span class="cards-title">波动告警（{{ alerts.length }} 条待处置）</span>
      <span v-if="ackCount" class="ack-hint">已确认 {{ ackCount }} 条</span>
    </header>

    <article v-for="a in alerts" :key="alertKey(a)" class="acard" :class="{ acked: acks[alertKey(a)] }">
      <div class="acard-main">
        <div class="acard-top">
          <span class="channel">{{ a.channel }}</span>
          <span class="mom-badge" :class="momTone(a.mom_pct)">
            {{ a.mom_pct > 0 ? '+' : '' }}{{ a.mom_pct }}%
          </span>
        </div>
        <p class="msg">{{ a.message }}</p>

        <!-- 下发结果行：如实呈现 RPA 状态（dispatch_failed 不粉饰） -->
        <p v-if="dispatchOf(a).text" class="dispatch-result" :class="dispatchOf(a).phase">
          {{ dispatchOf(a).text }}
        </p>
      </div>

      <div class="acard-actions">
        <template v-if="!acks[alertKey(a)]">
          <button class="act ghost" @click="ack(a)">确认</button>
          <button class="act ghost" :disabled="attrLoading" @click="emit('generate')">
            {{ attrLoading ? '生成中…' : '生成归因' }}
          </button>
          <button class="act primary" :disabled="dispatchOf(a).phase === 'sending'"
                  @click="dispatch(a)">
            {{ dispatchOf(a).phase === 'sending' ? '下发中…' : '下发整改' }}
          </button>
        </template>
        <template v-else>
          <span class="ack-mark">✓ 已确认</span>
          <button class="act ghost" @click="unack(a)">撤销</button>
        </template>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import { api } from '../api'
import { alertKey, matchTask, momTone } from '../alerts'
import type { Alert } from '../types'

const props = defineProps<{
  alerts: Alert[]
  product: string
  month: string
  attrLoading: boolean
}>()
const emit = defineEmits<{ (e: 'generate'): void }>()

// 确认态：会话级（刷新即恢复待处置）——刻意的：告警确认不该静默永久消失
const acks = reactive<Record<string, boolean>>({})
const ackCount = computed(() => Object.values(acks).filter(Boolean).length)
function ack(a: Alert) { acks[alertKey(a)] = true }
function unack(a: Alert) { delete acks[alertKey(a)] }

interface DispatchState { phase: 'idle' | 'sending' | 'done' | 'failed'; text?: string }
const dispatchStates = reactive<Record<string, DispatchState>>({})
function dispatchOf(a: Alert): DispatchState {
  return dispatchStates[alertKey(a)] ?? { phase: 'idle' }
}

async function dispatch(a: Alert) {
  const key = alertKey(a)
  dispatchStates[key] = { phase: 'sending' }
  try {
    // 后端契约：月级幂等装配（重复下发返回 note 说明），RPA 不可达如实报 dispatch_failed
    const r = await api.rectifyDispatch(props.product, props.month)
    const task = matchTask(a, r.tasks)
    if (task) {
      dispatchStates[key] = task.dispatch === 'sent'
        ? { phase: 'done', text: `✓ 已下发 ${task.task_id} · ${task.assignee} · 截止 ${task.deadline}` +
            (task.notify === 'pushed' ? ' · 微信已推送' : ' · 微信推送失败') }
        : { phase: 'failed', text: `⚠ RPA 不可达，任务 ${task.task_id} 已落库为 dispatch_failed（恢复后可在整改追踪重发）` }
    } else {
      // 无匹配任务 = 幂等跳过或本月无告警（后端 note 原样展示）
      dispatchStates[key] = { phase: 'done', text: r.note ?? '本月告警此前已全部下发（幂等跳过）' }
    }
  } catch (e) {
    dispatchStates[key] = { phase: 'failed', text: `⚠ 下发请求失败：${e instanceof Error ? e.message : String(e)}` }
  }
}
</script>

<style scoped>
.alert-cards { margin: 0 0 14px; display: flex; flex-direction: column; gap: 10px; }
.cards-head { display: flex; justify-content: space-between; align-items: baseline; }
.cards-title { font-size: 13px; font-weight: 600; color: var(--sem-alert); letter-spacing: 0.02em; }
.ack-hint { font-size: 12px; color: var(--text-label); }

.acard {
  display: flex; justify-content: space-between; align-items: center; gap: 14px;
  background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 12px 16px 12px 14px; border-left: 4px solid var(--sem-alert);
  transition: opacity 0.15s ease;
}
.acard.acked { opacity: 0.55; border-left-color: #d5dde5; }

.acard-top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.channel {
  font-size: 11px; font-weight: 600; color: var(--sem-alert);
  background: var(--sem-alert-bg); padding: 2px 8px; border-radius: 999px;
}
.mom-badge { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 999px; }
.mom-badge.up { color: #c0392b; background: rgba(192, 57, 43, 0.1); }
.mom-badge.down { color: #1e8449; background: rgba(39, 160, 108, 0.12); }
.mom-badge.flat { color: var(--text-label); background: rgba(93, 109, 126, 0.1); }

.msg { margin: 0; font-size: 13px; color: var(--text-num); line-height: 1.55; }
.dispatch-result { margin: 6px 0 0; font-size: 12px; line-height: 1.5; }
.dispatch-result.done { color: #1e8449; }
.dispatch-result.failed { color: #c0392b; }

.acard-actions { display: flex; gap: 8px; align-items: center; flex-shrink: 0; }
.act {
  padding: 7px 14px; border-radius: 9px; border: none; cursor: pointer;
  font-size: 12.5px; transition: background 0.15s ease;
}
.act.ghost { background: rgba(93, 109, 126, 0.1); color: var(--text-unit); }
.act.ghost:hover:not(:disabled) { background: rgba(93, 109, 126, 0.18); }
.act.primary {
  background: var(--primary); color: #fff;
  box-shadow: 0 3px 10px rgba(46, 109, 164, 0.3);
}
.act.primary:hover:not(:disabled) { background: var(--primary-hover); }
.act:disabled { opacity: 0.6; cursor: wait; }
.ack-mark { font-size: 12.5px; color: #1e8449; font-weight: 600; }

@media (max-width: 700px) {
  .acard { flex-direction: column; align-items: stretch; }
  .acard-actions { justify-content: flex-end; }
}
</style>
