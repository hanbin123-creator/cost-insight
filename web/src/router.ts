/** 极简 hash 路由（决策：不引 vue-router）
 * 优点：零新依赖（评审环境离线可装）、20 行可测、与 nginx 静态托管无 history fallback 配置冲突；
 * 缺点：无嵌套路由/路由守卫——本项目 5 个平级页面用不到；企业演进期页面 >10 个再换 vue-router，
 * 迁移成本仅 router.ts 一个文件（视图组件不感知路由实现）。 */
import { reactive } from 'vue'

export const ROUTES = ['dashboard', 'benchmark', 'rectify', 'reports', 'kb'] as const
export type RouteName = (typeof ROUTES)[number]

export const ROUTE_TITLES: Record<RouteName, string> = {
  dashboard: '成本看板',
  benchmark: '对标分析',
  rectify: '整改追踪',
  reports: '报告中心',
  kb: '知识库',
}

/** 解析 hash 字符串 → 路由名；空/未知一律回 dashboard（确定性，不抛错）。
 * 纯函数：不依赖 window，node 环境可单测 */
export function parseHash(hash: string): RouteName {
  const name = hash.replace(/^#\/?/, '').split('?')[0]
  return (ROUTES as readonly string[]).includes(name) ? (name as RouteName) : 'dashboard'
}

// 浏览器侧状态与监听：node 测试环境无 window，守卫跳过（路由解析逻辑由 parseHash 单测覆盖）
const isBrowser = typeof window !== 'undefined'
const state = reactive({ current: isBrowser ? parseHash(window.location.hash) : 'dashboard' as RouteName })

if (isBrowser) {
  window.addEventListener('hashchange', () => {
    state.current = parseHash(window.location.hash)
  })
}

export function useRoute() {
  return state
}

export function navigate(to: RouteName) {
  if (isBrowser) window.location.hash = `#/${to}`
}
