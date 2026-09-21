/** 全局选择状态：产品/月份由顶部筛选条控制，各视图共享（避免每页一套筛选器） */
import { reactive } from 'vue'
import { api } from './api'

export const store = reactive({
  products: [] as string[],
  months: [] as string[],
  product: '银黄口服液',
  month: '2026-05',
  /** 数据截至标注（条款 4：时间戳必标）= 月份列表最大值 */
  dataThrough: '',
  ready: false,
  loadError: null as string | null,
})

export async function initStore() {
  try {
    const d = await api.products()
    store.products = d.products
    store.months = d.months
    store.dataThrough = d.months.length ? d.months[d.months.length - 1] : ''
    if (d.products.length && !d.products.includes(store.product)) store.product = d.products[0]
    if (d.months.length && !d.months.includes(store.month)) store.month = d.months[d.months.length - 1]
    store.ready = true
  } catch (e) {
    // 后端未启动：保持默认选择，各面板走三态错误卡（不白屏、不静默）
    store.loadError = e instanceof Error ? e.message : String(e)
  }
}
