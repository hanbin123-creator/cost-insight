<template>
  <!-- 表格式热力图（方案二 + 产品分区）：取代 ECharts 热力图。
       数字直读 + 色阶底色双通道；产品分带（rowspan 分区 + 粗分隔线）；
       点击格子联动看板筛选；选中 产品×月份 描边高亮（与旧热力图同口径） -->
  <div class="heat-table-wrap">
    <table class="heat-table">
      <thead>
        <tr>
          <th class="col-prod">产品</th>
          <th class="col-el">要素</th>
          <th v-for="m in h.months" :key="m">{{ m }}</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="zone in zones" :key="zone.product">
          <tr v-for="(row, idx) in zone.rows" :key="row.ri"
            :class="{ 'zone-first': idx === 0 }">
            <td v-if="idx === 0" class="zone-name" :rowspan="zone.rows.length">{{ zone.product }}</td>
            <td class="el-name">{{ row.element }}</td>
            <td v-for="(m, mi) in h.months" :key="m"
              class="cell"
              :class="{ sel: isSelCell(h, sel, row.ri, mi) }"
              :style="{ background: heatCellBg(cell(row.ri, mi), maxAbs), color: heatCellFg(cell(row.ri, mi), maxAbs) }"
              :title="`${zone.product}·${row.element} ${m} 环比：${fmtPct(cell(row.ri, mi))}`"
              @click="emit('cell-click', zone.product, m)">
              {{ fmtPct(cell(row.ri, mi)) }}
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    <div class="legend">
      <span>降 {{ -maxAbs }}%</span>
      <span class="bar"></span>
      <span>升 +{{ maxAbs }}%</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  fmtPct, heatCellBg, heatCellFg, heatCellMap, heatMaxAbs, heatZones, isSelCell,
} from '../heatTable'
import type { HeatmapResp } from '../types'

const props = defineProps<{
  h: HeatmapResp
  sel: { product?: string; month?: string }
}>()
const emit = defineEmits<{ (e: 'cell-click', product: string, month: string): void }>()

const zones = computed(() => heatZones(props.h))
const maxAbs = computed(() => heatMaxAbs(props.h))
const cellMap = computed(() => heatCellMap(props.h))
const cell = (ri: number, mi: number): number | null => cellMap.value.get(`${ri}:${mi}`) ?? null
</script>

<style scoped>
.heat-table-wrap { overflow-x: auto; }
.heat-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.heat-table th {
  padding: 7px 6px; font-weight: 600; font-size: 11px; color: var(--text-label);
  border-bottom: 1.5px solid #e2e8f0; text-align: center; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.col-prod, .col-el { text-align: left; }
.zone-name {
  padding: 8px 12px 8px 4px; font-weight: 700; color: var(--text-num); font-size: 12.5px;
  vertical-align: middle; border-right: 1.5px solid #e2e8f0; white-space: nowrap;
}
.el-name { padding: 6px 10px; color: var(--text-label); white-space: nowrap; }
.zone-first .zone-name, .zone-first .el-name, .zone-first .cell { border-top: 2px solid #d8dee8; }
tbody tr:first-child .zone-name, tbody tr:first-child .el-name, tbody tr:first-child .cell { border-top: none; }
.cell {
  text-align: center; padding: 8px 4px; min-width: 62px; cursor: pointer;
  font-variant-numeric: tabular-nums; border-bottom: 1px solid #f4f6fa;
  transition: box-shadow 0.15s ease;
}
.cell:hover { outline: 1.5px solid var(--primary); outline-offset: -1.5px; }
/* 选中高亮：与旧热力图同口径（主色描边 + 柔光晕影） */
.cell.sel { outline: 2px solid #1f4e79; outline-offset: -2px; box-shadow: 0 0 7px rgba(31, 78, 121, 0.45); }
.legend {
  display: flex; align-items: center; gap: 8px; margin-top: 10px;
  font-size: 10.5px; color: var(--text-label); font-variant-numeric: tabular-nums;
}
.legend .bar {
  width: 120px; height: 8px; border-radius: 4px;
  background: linear-gradient(to right, #5aa88f, #f7f9fa, #cd6f62);
}
</style>
