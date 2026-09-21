/** 增量4 单测：Agent 回复视图模型（四态）+ 整改看板三列归并 */
import { describe, expect, it } from 'vitest'
import { buildReplyView, groupTasks, kanbanColumn, KANBAN_TITLES } from '../agentCards'
import type { ChatResp, RpaTask } from '../types'

const base = { intent: 'dashboard', confidence: 0.92, layer: 'rule',
  classifier: 'none', params: {}, clarification: null }

describe('buildReplyView（Agent 抽屉四态）', () => {
  it('澄清态：缺参数时原样展示澄清文案', () => {
    const r = { ...base, clarification: '请问要分析哪个产品？', result: null } as ChatResp
    const v = buildReplyView(r)
    expect(v.kind).toBe('clarify')
    expect((v as { text: string }).text).toContain('哪个产品')
  })

  it('四入口态：意图不明时给出 choices 卡片', () => {
    const r = { ...base, intent: null, result: {
      message: '我没完全理解您的意图',
      choices: [{ intent: 'report', name: '智能报告', description: '生成月度成本分析报告' }],
    } } as unknown as ChatResp
    const v = buildReplyView(r)
    expect(v.kind).toBe('choices')
    expect((v as { choices: unknown[] }).choices).toHaveLength(1)
  })

  it('看板卡片：单位成本/环比/告警数原样摆放', () => {
    const r = { ...base, result: { ok: true, intent: 'dashboard', scene: '看板速览',
      data: { unit_cost: 11.21, mom_pct: 2.8, alerts: 1 } } } as ChatResp
    const v = buildReplyView(r)
    expect(v.kind).toBe('card')
    const lines = (v as { lines: string[] }).lines.join('|')
    expect(lines).toContain('11.21')
    expect(lines).toContain('+2.8%')
    expect(lines).toContain('1 条')
  })

  it('错误态：场景失败如实展示 error', () => {
    const r = { ...base, result: { ok: false, intent: 'report', error: 'ValueError: 缺数据' } } as ChatResp
    const v = buildReplyView(r)
    expect(v.kind).toBe('error')
    expect((v as { text: string }).text).toContain('缺数据')
  })

  it('整改卡片：无任务时展示后端 note（幂等说明）', () => {
    const r = { ...base, result: { ok: true, intent: 'rectify', scene: '整改任务',
      data: { tasks: [], note: '全部告警任务此前已发送（幂等跳过，不重复下发）' } } } as ChatResp
    const v = buildReplyView(r)
    expect((v as { lines: string[] }).lines[0]).toContain('幂等')
  })
})

describe('整改看板三列归并', () => {
  it('状态映射：completed→已复核，received/confirmed/in_progress→整改中，其余→待下发', () => {
    expect(kanbanColumn('completed')).toBe('done')
    expect(kanbanColumn('received')).toBe('doing')
    expect(kanbanColumn('confirmed')).toBe('doing')
    expect(kanbanColumn('in_progress')).toBe('doing')
    expect(kanbanColumn('created')).toBe('todo')
    expect(kanbanColumn('dispatch_failed')).toBe('todo')  // 失败任务回待下发列重发
    expect(kanbanColumn(undefined)).toBe('todo')
  })

  it('groupTasks：按列分组且保持原顺序', () => {
    const tasks = [
      { task_id: 'A', status: 'received' },
      { task_id: 'B', status: 'created' },
      { task_id: 'C', status: 'completed' },
      { task_id: 'D', status: 'in_progress' },
    ] as RpaTask[]
    const g = groupTasks(tasks)
    expect(g.todo.map((t) => t.task_id)).toEqual(['B'])
    expect(g.doing.map((t) => t.task_id)).toEqual(['A', 'D'])
    expect(g.done.map((t) => t.task_id)).toEqual(['C'])
  })

  it('列标题与选型一致：待下发/整改中/已复核', () => {
    expect(KANBAN_TITLES).toEqual({ todo: '待下发', doing: '整改中', done: '已复核' })
  })
})
