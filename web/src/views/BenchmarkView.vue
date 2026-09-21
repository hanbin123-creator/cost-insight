<template>
  <!-- F9 对标分析页（选型 V2 蝶形图主视图 + V1 双向对比表明细）。
       双向差异率与描述句由后端算好，本页只读不算（大模型永不算数原则延伸） -->
  <div class="bench">
    <div v-if="loading" class="state">加载中…</div>
    <div v-else-if="error" class="state error">⚠ {{ error }}</div>

    <template v-else-if="data">
      <ChartPanel title="蝶形对比 · 一厂 vs 二厂（元/盒）"
        hint="悬浮查看双向差异率"
        :option="butterflyOpt" :loading="false" :error="null" tall />

      <!-- V1 双向对比表：明细口径（差异率两个方向并列，杜绝口径歧义） -->
      <section class="panel">
        <h3>双向口径明细<span class="hint">两个方向的差异率均由后端计算，本表只读</span></h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>要素</th><th>一厂（元/盒）</th><th>二厂（元/盒）</th><th>差值</th>
                <th>差异率·对二厂</th><th>差异率·对一厂</th><th>方向</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in data.rows" :key="r.element">
                <td class="el-name">{{ r.element }}</td>
                <td class="num">{{ r.main.toFixed(2) }}</td>
                <td class="num">{{ r.bench.toFixed(2) }}</td>
                <td class="num" :class="tone(r.diff)">{{ fmtSigned(r.diff) }}</td>
                <td class="num" :class="tone(r.diff_rate_pct)">{{ fmtPct(r.diff_rate_pct) }}</td>
                <td class="num" :class="tone(r.reverse_rate_pct)">{{ fmtPct(r.reverse_rate_pct) }}</td>
                <td><span class="dir" :class="dirCls(r.direction)">{{ r.direction }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 代码预生成的无歧义描述句：可直接引用进报告/归因，措辞零歧义 -->
      <section class="panel">
        <h3>口径描述<span class="hint">代码预生成 · 可直接引用</span></h3>
        <ul class="desc-list">
          <li v-for="r in data.rows" :key="r.element">{{ r.description }}</li>
        </ul>
      </section>

      <!-- 材料差异下钻：估算口径明确标注（后端按成本占比分摊） -->
      <section class="panel">
        <h3>材料差异下钻<span class="hint">估算口径：按材料成本占比分摊总差异（后端标注），非逐料实测</span></h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>材料</th><th>一厂单价（元/盒）</th><th>成本占比</th><th>估算差异（元/盒）</th></tr>
            </thead>
            <tbody>
              <tr v-for="m in data.material_detail" :key="m.material">
                <td class="el-name">{{ m.material }}</td>
                <td class="num">{{ m.main_unit_cost.toFixed(2) }}</td>
                <td class="num">{{ m.share_pct.toFixed(1) }}%</td>
                <td class="num" :class="tone(m.est_diff)">{{ fmtSigned(m.est_diff) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import { store } from '../store'
import { butterflyOption } from '../charts/options'
import ChartPanel from '../components/ChartPanel.vue'
import type { BenchmarkResp } from '../types'

const data = ref<BenchmarkResp | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const butterflyOpt = computed(() => (data.value ? butterflyOption(data.value) : null))

// 方向语义色：一厂成本高=劣势红，低=优势绿（与瀑布涨跌同一套方向纪律）
const tone = (v: number | null) => (v === null ? '' : v > 0 ? 'neg' : v < 0 ? 'pos' : '')
const dirCls = (d: string) => (d === '优势' ? 'pos' : d === '劣势' ? 'neg' : 'flat')
const fmtSigned = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}`)
const fmtPct = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`)

async function refresh() {
  loading.value = true
  error.value = null
  try { data.value = await api.benchmark(store.product, store.month) }
  catch (e) { data.value = null; error.value = e instanceof Error ? e.message : String(e) }
  finally { loading.value = false }
}
watch(() => [store.product, store.month], refresh, { immediate: true })
</script>

<style scoped>
.bench { display: flex; flex-direction: column; gap: 14px; }
.state {
  min-height: 200px; display: flex; align-items: center; justify-content: center;
  color: var(--text-label); font-size: 13px;
}
.state.error { color: var(--sem-alert); }
.panel {
  background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 16px 18px;
}
h3 { margin: 0 0 10px; font-size: 13px; font-weight: 600; color: var(--text-unit); letter-spacing: 0.02em; }
.hint { margin-left: 8px; font-size: 11px; font-weight: 400; color: var(--text-label); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
th {
  text-align: left; color: var(--text-label); font-weight: 600; font-size: 11.5px;
  padding: 6px 10px; border-bottom: 1px solid var(--split, #edf1f5);
}
td { padding: 7px 10px; border-bottom: 1px solid #f3f6f9; }
tr:last-child td { border-bottom: none; }
.num { font-variant-numeric: tabular-nums; text-align: right; }
th:nth-child(n+2):nth-child(-n+6) { text-align: right; }
.num.pos, .dir.pos { color: #1e8449; }
.num.neg, .dir.neg { color: #c0392b; }
.dir { font-weight: 600; font-size: 12px; }
.dir.flat { color: var(--text-label); }
.el-name { font-weight: 600; color: var(--text-num); }
.desc-list { margin: 0; padding-left: 18px; font-size: 12.5px; line-height: 1.9; color: var(--text-num); }
</style>
