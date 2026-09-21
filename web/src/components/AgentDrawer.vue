<template>
  <!-- F5（选型 V1 右侧抽屉 + V5 决策卡片流）：Copilot 式 Agent 面板。
       页面上下文（产品/月份）自动注入每次请求，用户无需重复报参 -->
  <transition name="slide">
    <aside v-if="open" class="drawer" aria-label="Agent 助手">
      <header class="d-head">
        <div>
          <div class="d-title">Agent 助手</div>
          <div class="d-ctx">上下文：{{ store.product }} · {{ store.month }}（自动注入）</div>
        </div>
        <button class="d-close" title="关闭" @click="emit('close')">✕</button>
      </header>

      <!-- V5 决策卡片流：系统自主判断建议，确认按钮嵌对话 -->
      <div v-if="decision && decision.action === 'generate_attribution' && !decisionDone" class="decision-card">
        <div class="dc-title">🤖 决策建议（{{ decision.engine }}）</div>
        <p class="dc-reason">{{ decision.reason }}</p>
        <div class="dc-actions">
          <button class="dc-confirm" @click="confirmAttribution">确认生成归因</button>
          <button class="dc-dismiss" @click="decisionDone = true">忽略</button>
        </div>
      </div>

      <div ref="msgBox" class="d-body">
        <div v-if="!messages.length" class="d-empty">
          试着问我：「生成 2026-05 的月度报告」「银黄口服液对标二厂差多少」「下发整改任务」
        </div>
        <template v-for="(m, i) in messages" :key="i">
          <div v-if="m.role === 'user'" class="bubble user">{{ m.text }}</div>
          <div v-else class="bubble agent">
            <!-- 四态渲染：场景卡片 / 澄清 / 四入口 / 错误 -->
            <template v-if="m.view.kind === 'card'">
              <div class="r-title">{{ m.view.title }}</div>
              <div v-for="(l, j) in m.view.lines" :key="j" class="r-line">{{ l }}</div>
              <div class="r-meta">意图 {{ m.intent }} · 置信 {{ m.confidence }} · {{ m.layer }}</div>
            </template>
            <template v-else-if="m.view.kind === 'clarify'">{{ m.view.text }}</template>
            <template v-else-if="m.view.kind === 'choices'">
              <div>{{ m.view.message }}</div>
              <button v-for="c in m.view.choices" :key="c.intent" class="choice"
                @click="send(c.description)">
                <strong>{{ c.name }}</strong>·{{ c.description }}
              </button>
            </template>
            <template v-else>⚠ {{ m.view.text }}</template>
          </div>
        </template>
        <div v-if="sending" class="bubble agent dim">路由分发中（路由只分发永不算数）…</div>
      </div>

      <footer class="d-foot">
        <input v-model="draft" placeholder="问成本、要报告、派整改…" @keyup.enter="send(draft)" />
        <button :disabled="sending || !draft.trim()" @click="send(draft)">发送</button>
      </footer>
    </aside>
  </transition>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { api } from '../api'
import { buildReplyView, type ReplyView } from '../agentCards'
import { store } from '../store'
import type { DecisionResp } from '../types'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

interface Msg { role: 'user' | 'agent'; text?: string; view: ReplyView; intent?: string; confidence?: number; layer?: string }
const messages = ref<Msg[]>([])
const draft = ref('')
const sending = ref(false)
const msgBox = ref<HTMLElement | null>(null)

// V5 决策卡片：打开抽屉时按当前上下文取系统建议（规则引擎，永不算数）
const decision = ref<DecisionResp | null>(null)
const decisionDone = ref(false)
watch(() => props.open, async (v) => {
  if (!v) return
  decisionDone.value = false
  try { decision.value = await api.decision(store.product, store.month) }
  catch { decision.value = null }
})

function confirmAttribution() {
  decisionDone.value = true
  store.attributionRequest += 1   // 跨视图触发：看板页 watch 执行生成
  messages.value.push({
    role: 'agent',
    view: { kind: 'card', scene: 'decision', title: '已派发', lines: ['归因生成请求已发送到看板页（如不在看板页，请切换查看）'] },
  })
}

async function send(text: string) {
  const t = text.trim()
  if (!t || sending.value) return
  draft.value = ''
  messages.value.push({ role: 'user', text: t, view: { kind: 'clarify', text: t } })
  sending.value = true
  try {
    const r = await api.chat(t, store.product, store.month)  // 上下文自动注入
    messages.value.push({
      role: 'agent', view: buildReplyView(r),
      intent: r.intent ?? 'none', confidence: r.confidence, layer: r.layer,
    })
  } catch (e) {
    messages.value.push({ role: 'agent', view: { kind: 'error', text: e instanceof Error ? e.message : String(e) } })
  } finally {
    sending.value = false
    await nextTick()
    msgBox.value?.scrollTo({ top: msgBox.value.scrollHeight, behavior: 'smooth' })
  }
}
</script>

<style scoped>
.drawer {
  position: fixed; top: 0; right: 0; bottom: 0; width: 340px; z-index: 50;
  background: var(--card); box-shadow: -8px 0 28px rgba(59, 47, 117, 0.16);
  display: flex; flex-direction: column;
}
.slide-enter-active, .slide-leave-active { transition: transform 0.22s ease; }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }

.d-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 16px 16px 12px; border-bottom: 1px solid #eef1f6;
}
.d-title { font-size: 15px; font-weight: 700; color: var(--text-num); }
.d-ctx { font-size: 11px; color: var(--text-label); margin-top: 3px; }
.d-close { border: none; background: none; cursor: pointer; color: var(--text-label); font-size: 14px; }

.decision-card {
  margin: 12px 12px 0; padding: 12px 14px; border-radius: 12px;
  background: #eae7f6; color: #3b2f75; font-size: 12.5px;
}
.dc-title { font-weight: 700; margin-bottom: 4px; }
.dc-reason { margin: 0 0 8px; line-height: 1.55; }
.dc-actions { display: flex; gap: 8px; }
.dc-confirm {
  border: none; border-radius: 8px; padding: 6px 12px; cursor: pointer;
  background: #3b2f75; color: #fff; font-size: 12px;
}
.dc-dismiss { border: none; background: none; cursor: pointer; color: #6b5f9e; font-size: 12px; }

.d-body { flex: 1; overflow-y: auto; padding: 14px 12px; display: flex; flex-direction: column; gap: 10px; }
.d-empty { color: var(--text-label); font-size: 12.5px; line-height: 1.8; padding: 8px 4px; }
.bubble { max-width: 88%; padding: 9px 12px; border-radius: 12px; font-size: 13px; line-height: 1.6; }
.bubble.user { align-self: flex-end; background: var(--primary); color: #fff; border-bottom-right-radius: 4px; }
.bubble.agent { align-self: flex-start; background: rgba(93, 109, 126, 0.08); color: var(--text-num); border-bottom-left-radius: 4px; }
.bubble.dim { color: var(--text-label); }
.r-title { font-weight: 700; margin-bottom: 4px; }
.r-line { font-size: 12.5px; }
.r-meta { margin-top: 6px; font-size: 10.5px; color: var(--text-label); }
.choice {
  display: block; width: 100%; margin-top: 6px; text-align: left;
  border: none; border-radius: 9px; padding: 7px 10px; cursor: pointer;
  background: #fff; color: var(--text-num); font-size: 12px; box-shadow: var(--shadow);
}
.choice:hover { background: rgba(46, 109, 164, 0.08); }

.d-foot { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #eef1f6; }
.d-foot input {
  flex: 1; border: none; border-radius: 10px; padding: 9px 12px; font-size: 13px;
  background: rgba(93, 109, 126, 0.08); outline: none;
}
.d-foot button {
  border: none; border-radius: 10px; padding: 9px 16px; cursor: pointer;
  background: var(--primary); color: #fff; font-size: 13px;
}
.d-foot button:disabled { opacity: 0.55; cursor: default; }
</style>
