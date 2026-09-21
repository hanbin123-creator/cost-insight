/** Agent 抽屉与整改看板的纯函数视图模型（vitest 主战场；组件只渲染）。
 *  所有文案由后端字段摆放而成，数字不做任何再计算。 */
import type { ChatResp, RpaTask } from './types'

export type ReplyView =
  | { kind: 'clarify'; text: string }
  | { kind: 'choices'; message: string; choices: { intent: string; name: string; description: string }[] }
  | { kind: 'card'; scene: string; title: string; lines: string[] }
  | { kind: 'error'; text: string }

const signed = (v: unknown) =>
  typeof v === 'number' ? `${v > 0 ? '+' : ''}${v}` : '—'

/** 把 /api/chat 的响应映射为抽屉可渲染的视图模型（四态：卡片/澄清/四入口/错误） */
export function buildReplyView(r: ChatResp): ReplyView {
  if (r.clarification) return { kind: 'clarify', text: r.clarification }
  const res = r.result
  if (!res) return { kind: 'error', text: '场景无产出（未注册意图）' }
  if (res.choices) return { kind: 'choices', message: res.message ?? '', choices: res.choices }
  if (res.ok === false) return { kind: 'error', text: res.error ?? '场景执行失败' }

  const d = res.data ?? {}
  switch (res.intent) {
    case 'dashboard':
      return {
        kind: 'card', scene: 'dashboard', title: '看板速览',
        lines: [
          `单位成本 ${d.unit_cost ?? '—'} 元/盒（环比 ${signed(d.mom_pct)}%）`,
          `当前月告警 ${d.alerts ?? 0} 条`,
        ],
      }
    case 'benchmark': {
      const rows = (d.rows ?? []) as Array<{ element: string; main: number; bench: number; diff_rate_pct: number | null }>
      return {
        kind: 'card', scene: 'benchmark', title: '对标分析（一厂 vs 二厂）',
        lines: rows.map((x) =>
          `${x.element}：${x.main} vs ${x.bench}（${signed(x.diff_rate_pct)}%·对二厂）`),
      }
    }
    case 'report': {
      const v = (d.verification ?? {}) as { verdict?: string }
      const verdict = { pass: '校验通过', auto_fixed: '通过（含自动补全）', rejected: '已拦截' }[v.verdict ?? ''] ?? '未知'
      return {
        kind: 'card', scene: 'report', title: `报告已生成（${d.theme ?? '—'}）`,
        lines: [
          `Word：${d.docx ?? '—'}`,
          d.pdf ? `PDF：${d.pdf}` : 'PDF：未产出（见后端警告）',
          `校验：${verdict}`,
        ],
      }
    }
    case 'rectify': {
      const tasks = (d.tasks ?? []) as Array<{ task_id?: string; dispatch?: string }>
      const failed = tasks.filter((t) => t.dispatch === 'dispatch_failed').length
      return {
        kind: 'card', scene: 'rectify', title: '整改任务下发',
        lines: tasks.length
          ? [`装配任务 ${tasks.length} 个${failed ? `（${failed} 个 RPA 不可达落库）` : '，已发送'}`,
             ...tasks.slice(0, 3).map((t) => t.task_id ?? '').filter(Boolean)]
          : [(d.note as string) ?? '本月无告警任务'],
      }
    }
    default:
      return { kind: 'card', scene: res.intent ?? '?', title: res.scene ?? '场景产出', lines: [JSON.stringify(d)] }
  }
}

/** F7 看板三列归并：RPA 原生状态 → 待下发/整改中/已复核 */
export type KanbanCol = 'todo' | 'doing' | 'done'
export function kanbanColumn(status: string | undefined): KanbanCol {
  switch (status) {
    case 'completed':
      return 'done'
    case 'received':
    case 'confirmed':
    case 'in_progress':
      return 'doing'
    default:  // created/generated/pending/dispatch_failed/未知 → 待下发（含失败重发）
      return 'todo'
  }
}

/** 看板分组（保持 RPA 返回顺序，不排序不加工） */
export function groupTasks(tasks: RpaTask[]): Record<KanbanCol, RpaTask[]> {
  const out: Record<KanbanCol, RpaTask[]> = { todo: [], doing: [], done: [] }
  for (const t of tasks) out[kanbanColumn(t.status)].push(t)
  return out
}

export const KANBAN_TITLES: Record<KanbanCol, string> = {
  todo: '待下发', doing: '整改中', done: '已复核',
}
