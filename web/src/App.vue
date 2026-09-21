<template>
  <!-- F1 V1：左侧深紫导航栏 + 顶部筛选条；内容区按 hash 路由切换视图。
       侧栏可折叠（用户要求）：默认展开，收起为纯图标栏，状态存 localStorage -->
  <div class="shell">
    <aside class="sidebar" :class="{ collapsed: effectiveCollapsed }">
      <div class="brand">
        <div class="brand-name">{{ effectiveCollapsed ? '创灵境' : '创灵境 · 成本洞察' }}</div>
        <div v-if="!effectiveCollapsed" class="brand-sub">制药成本智能分析</div>
      </div>
      <nav>
        <a v-for="r in navItems" :key="r.name" class="nav-item"
           :class="{ active: route.current === r.name }"
           :href="'#/' + r.name" :title="effectiveCollapsed ? r.title : ''">
          <svg class="icon" viewBox="0 0 16 16" fill="none" stroke="currentColor"
               stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
               v-html="r.icon"></svg><span v-if="!effectiveCollapsed">{{ r.title }}</span>
        </a>
      </nav>
      <!-- A1 变体 v3（用户要求"靠近弹出、离开收回"）：梯形默认缩进侧栏内不可见，
           外层热区覆盖滑出/收回两种状态的全部占用范围，避免滑出后鼠标脱悬闪烁 -->
      <div class="edge-hotspot">
        <button class="collapse-tab" @click="toggle" :title="collapsed ? '展开导航' : '收起导航'">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:10px;height:10px">
            <path v-if="collapsed" d="M6 3l5 5-5 5"/>
            <path v-else d="M10 3L5 8l5 5"/>
          </svg>
        </button>
      </div>
    </aside>

    <div class="main-col">
      <header class="topbar">
        <h1>{{ ROUTE_TITLES[route.current] }}</h1>
        <div class="controls">
          <select v-model="store.product" aria-label="产品选择">
            <option v-for="p in store.products" :key="p" :value="p">{{ p }}</option>
          </select>
          <select v-model="store.month" aria-label="月份选择">
            <option v-for="m in store.months" :key="m" :value="m">{{ m }}</option>
          </select>
          <!-- 条款 4：数据时间戳必标 -->
          <span class="data-through">数据截至 {{ store.dataThrough || '—' }}</span>
        </div>
      </header>

      <div v-if="store.loadError" class="backend-err">
        后端连接失败（各面板将显示错误卡）：{{ store.loadError }}
      </div>

      <main class="content">
        <DashboardView v-if="route.current === 'dashboard'" />
        <BenchmarkView v-else-if="route.current === 'benchmark'" />
        <PlaceholderView v-else-if="route.current === 'rectify'" title="整改追踪"
          plan="V1 看板列（待下发/整改中/已复核）＋ V5 告警卡内嵌联动（数据：/api/rectify/* 已就绪）"
          hint="增量 4 落地。告警卡下发整改后自动生成看板卡，RPA 状态如实展示。" />
        <PlaceholderView v-else-if="route.current === 'reports'" title="报告中心"
          plan="V3 时间轴归档 ＋ V4 首页最新报告卡（数据：/api/report 月报/季报/专题已就绪）"
          hint="增量 5 落地。顶部新建报告操作条（类型按钮→参数弹窗→进度→入轴）。" />
        <PlaceholderView v-else-if="route.current === 'kb'" title="知识库"
          plan="V4 检索优先（RAG 透明化）＋ V1 文档列表管理（数据：/api/kb/documents 已就绪）"
          hint="增量 5 落地。检索结果带引用片段与出处文档；上传后后台重建索引。" />
      </main>
    </div>

    <!-- B1（用户选定）：Agent 右下角悬浮球（微软 Copilot DAB 范式）。
         F5 增量落地抽屉对话前，点击给出确定性反馈而非静默 -->
    <button class="agent-fab" title="问 Agent（F5 增量落地）" @click="pingFab">
      <svg viewBox="0 0 16 16" fill="currentColor" style="width:20px;height:20px">
        <path d="M8 1.5l1.7 4.8 4.8 1.7-4.8 1.7L8 14.5 6.3 9.7 1.5 8l4.8-1.7z"/>
      </svg>
    </button>
    <div v-if="fabToast" class="fab-toast">Agent 对话面板将在 F5 增量落地（右侧抽屉 + 决策卡片流）</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { navigate, ROUTE_TITLES, useRoute, type RouteName } from './router'
import { initStore, store } from './store'
import DashboardView from './views/DashboardView.vue'
import BenchmarkView from './views/BenchmarkView.vue'
import PlaceholderView from './components/PlaceholderView.vue'

const route = useRoute()

// 侧栏折叠：默认展开，用户可收起；选择持久化到 localStorage（下次进入记住）
const collapsed = ref(false)
try { collapsed.value = localStorage.getItem('ci-sidebar') === 'collapsed' } catch { /* 隐私模式等异常静默 */ }
function toggle() {
  collapsed.value = !collapsed.value
  try { localStorage.setItem('ci-sidebar', collapsed.value ? 'collapsed' : 'expanded') } catch { /* 同上 */ }
}

// 真·窄屏（≤560px 手机）下忽略持久化的收起态：横向平铺的侧栏必须带文字标签，
// 否则 collapsed 的 60px 宽度会压过媒体查询的 100%，渲染成"紫色树桩"（实测缺陷）
const narrowMq = window.matchMedia('(max-width: 560px)')
const narrow = ref(narrowMq.matches)
const onNarrow = (e: MediaQueryListEvent) => { narrow.value = e.matches }
onMounted(() => narrowMq.addEventListener('change', onNarrow))
onUnmounted(() => narrowMq.removeEventListener('change', onNarrow))
const effectiveCollapsed = computed(() => collapsed.value && !narrow.value)

// Agent FAB：F5 前的确定性反馈（点击不静默）
const fabToast = ref(false)
let fabTimer: ReturnType<typeof setTimeout> | undefined
function pingFab() {
  fabToast.value = true
  clearTimeout(fabTimer)
  fabTimer = setTimeout(() => { fabToast.value = false }, 2200)
}

// 单色 SVG 图标（currentColor 跟随导航文字色——emoji 彩色方块违反色彩纪律，已淘汰）
const navItems: { name: RouteName; title: string; icon: string }[] = [
  { name: 'dashboard', title: '成本看板', icon: '<rect x="1.5" y="8" width="3.5" height="6.5" rx="1"/><rect x="6.25" y="4.5" width="3.5" height="10" rx="1"/><rect x="11" y="1.5" width="3.5" height="13" rx="1"/>' },
  { name: 'benchmark', title: '对标分析', icon: '<rect x="2" y="3.5" width="4.5" height="9" rx="1"/><rect x="9.5" y="6.5" width="4.5" height="6" rx="1"/>' },
  { name: 'rectify', title: '整改追踪', icon: '<circle cx="8" cy="8" r="6.2"/><path d="M5.2 8.2l1.9 1.9 3.7-4.2"/>' },
  { name: 'reports', title: '报告中心', icon: '<rect x="3.2" y="1.8" width="9.6" height="12.4" rx="1.4"/><path d="M5.6 5.4h4.8M5.6 8h4.8M5.6 10.6h3.2"/>' },
  { name: 'kb', title: '知识库', icon: '<path d="M3 2.6h6.8A2.2 2.2 0 0112 4.8v8.6H5.2A2.2 2.2 0 013 11.2V2.6z"/><path d="M5.4 5.8h4.2M5.4 8.4h4.2"/>' },
]

onMounted(initStore)
// navigate 供后续程序化跳转（告警卡→整改页等），当前模板用 hash 链接
void navigate
</script>

<style scoped>
.shell { display: flex; min-height: 100vh; }

/* F1 V1：深紫侧栏（04 号参考图血统）；可折叠为 60px 图标栏 */
.sidebar {
  width: 200px; flex-shrink: 0; background: var(--nav); color: var(--nav-text);
  display: flex; flex-direction: column; position: sticky; top: 0; height: 100vh;
  transition: width 0.2s ease;
}
.sidebar.collapsed { width: 60px; }
.sidebar.collapsed .brand { padding: 20px 8px 16px; text-align: center; }
.sidebar.collapsed .brand-name { font-size: 12px; }
.sidebar.collapsed .nav-item { justify-content: center; padding: 11px 0; }
.brand { padding: 20px 18px 16px; border-bottom: 1px solid rgba(255, 255, 255, 0.12); }
.brand-name { font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; }
.brand-sub { font-size: 11px; color: var(--nav-text-dim); margin-top: 3px; }
nav { flex: 1; padding: 12px 10px; display: flex; flex-direction: column; gap: 4px; }
.nav-item {
  display: flex; align-items: center; gap: 9px; padding: 10px 12px; border-radius: 9px;
  color: var(--nav-text); text-decoration: none; font-size: 13.5px; white-space: nowrap;
}
.nav-item:hover { background: var(--nav-hover); }
.nav-item.active { background: var(--nav-active); font-weight: 600; }
.icon { width: 15px; height: 15px; flex-shrink: 0; }

/* A1 变体 v3：边缘热区 + 弹出式梯形握把——默认缩进侧栏内完全不可见（translateX(-14px)），
   鼠标进入右缘 28px 热区时滑出（0.18s），离开热区自动收回。
   热区包住两种状态的全部占用范围，杜绝"滑出→脱悬→收回→再悬停"的闪烁循环 */
.edge-hotspot {
  position: absolute; right: -14px; top: 50%; transform: translateY(-50%);
  width: 28px; height: 96px; z-index: 30; cursor: pointer;
}
.collapse-tab {
  position: absolute; right: 0; top: 50%;
  width: 14px; height: 84px; border: none; cursor: pointer;
  background: var(--nav); color: var(--nav-text-dim);
  clip-path: polygon(0 0, 100% 10%, 100% 90%, 0 100%);
  display: flex; align-items: center; justify-content: center;
  transform: translateY(-50%) translateX(-14px);
  opacity: 0;
  transition: transform 0.18s ease, opacity 0.18s ease, color 0.15s ease;
}
.edge-hotspot:hover .collapse-tab {
  transform: translateY(-50%) translateX(0);
  opacity: 1; color: var(--nav-text);
}

/* B1：Agent 悬浮球（紫系渐变=AI 身份，语义色之外的唯一品牌渐变色） */
.agent-fab {
  position: fixed; right: 24px; bottom: 24px; width: 48px; height: 48px;
  border-radius: 50%; border: none; cursor: pointer; color: #fff; z-index: 40;
  background: linear-gradient(135deg, #3b2f75, #9163cb);
  box-shadow: 0 6px 18px rgba(59, 47, 117, 0.4);
  display: flex; align-items: center; justify-content: center;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.agent-fab:hover { transform: translateY(-2px); box-shadow: 0 8px 22px rgba(59, 47, 117, 0.5); }
.fab-toast {
  position: fixed; right: 24px; bottom: 82px; z-index: 40;
  background: #2c3e50; color: #fff; font-size: 12px; padding: 9px 14px;
  border-radius: 10px; box-shadow: var(--shadow-lg);
}

.main-col { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topbar {
  display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;
  gap: 10px; padding: 20px 24px 14px;
}
.topbar h1 { font-size: 19px; margin: 0; letter-spacing: 0.01em; }
.controls { display: flex; gap: 8px; align-items: center; }
.controls select {
  padding: 8px 14px; border-radius: 10px; border: none;
  background: var(--card); font-size: 13.5px; box-shadow: var(--shadow);
  color: var(--text-num); cursor: pointer;
}
.data-through { font-size: 12px; color: var(--text-label); }
.backend-err {
  margin: 0 24px 10px; padding: 10px 16px; border-radius: 12px; font-size: 12px;
  background: var(--sem-alert-bg); border: none; color: #922b21;
}
/* 容器查询上下文：让视图按"内容区实际宽度"降级（感知侧栏收展），
   而不是按视口宽度（媒体查询看不见侧栏状态，实测踩坑） */
.content { padding: 0 24px 28px; container-type: inline-size; }
@media (max-width: 560px) {
  /* 仅真·手机屏进入横铺布局；560–760px 的窄桌面/侧栏面板保持桌面壳，
     否则梯形握把被误藏、KPI 与图表被过度挤压（实测 742px 面板踩坑） */
  .shell { flex-direction: column; }
  .sidebar { width: 100%; height: auto; position: static; flex-direction: row; flex-wrap: wrap; }
  nav { flex-direction: row; flex-wrap: wrap; }
  .edge-hotspot { display: none; }  /* 窄屏下侧栏已横向平铺，折叠无意义 */
}
</style>
