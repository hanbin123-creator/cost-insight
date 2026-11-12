/** A11 内容级锚点定位：hash ?focus=<anchor> → 滚动到 data-anchor 元素并高亮闪烁。
 *  数据异步加载元素可能晚到：最多重试约 2 秒；找不到静默降级为页面级跳转（不报错）。
 *  锚点只携带位置不携带数据（大模型永不算数的前端兑现）。 */
import { nextTick, watch } from 'vue'
import { useRoute } from './router'

export function scrollToAnchor(anchor: string): boolean {
  if (typeof document === 'undefined') return false
  const el = document.querySelector(`[data-anchor="${anchor}"]`)
  if (!el) return false
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  el.classList.add('anchor-flash')
  setTimeout(() => el.classList.remove('anchor-flash'), 2000)
  return true
}

/** 视图组件 setup 里调用：路由 focus 变化（或挂载时已有 focus）→ 定位锚点 */
export function useFocusAnchor(): void {
  const route = useRoute()
  watch(() => [route.current, route.focusSeq], async () => {
    const anchor = route.focus
    if (!anchor) return
    for (let i = 0; i < 10; i++) {
      await nextTick()
      if (scrollToAnchor(anchor)) return
      await new Promise((r) => setTimeout(r, 200))
    }
  }, { immediate: true })
}
