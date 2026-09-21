/** 告警行动卡的纯函数助手（抽出来单测；组件只做渲染与事件） */
import type { Alert, RectifyTask } from './types'

/** 告警签名：本卡"确认"态的标识（同月同产品下唯一） */
export function alertKey(a: Alert): string {
  return `${a.channel}|${a.element}|${a.mom_pct}`
}

/** 在整月下发的任务列表里找本条告警对应的任务：任务标题含告警要素名。
 *  后端 dispatch 是月级幂等装配（按告警标题去重），前端只匹配不构造。 */
export function matchTask(a: Alert, tasks: RectifyTask[]): RectifyTask | null {
  if (!a.element) return null
  return tasks.find((t) => t.title.includes(a.element)) ?? null
}

/** 环比徽章的方向语义：涨=不利红 / 跌=有利绿（与瀑布图同一套方向纪律） */
export function momTone(momPct: number): 'up' | 'down' | 'flat' {
  if (momPct > 0) return 'up'
  if (momPct < 0) return 'down'
  return 'flat'
}
