/** 数据 → ECharts option 纯函数映射层（vitest 主战场；组件只做薄渲染）。
 *  纪律：分析数字已在后端算好，本层只做"摆放"，不做任何计算。
 *
 *  色彩纪律（条款 2/6，开发日志 09 D4/D7）：
 *  图表 token（数据角色）与语义 token（状态）分层——本文件只定义图表 token。
 *  分类色板基于 Tableau 10（CIELAB 感知均匀）：中等饱和、色相拉开；
 *  红/绿不进分类板，只给方向信号（瀑布涨跌、热力偏离）。 */
import type {
  BenchmarkResp, ForecastResp, SeriesResp, StructureResp, WaterfallResp,
} from '../types'

/** 图表 token（数据角色层）。语义状态色见 tokens.css --sem-*，两层禁止混用 */
export const CT = {
  main: '#1f4e79',                          // 单位成本主线：深海军蓝（压阵主角，与材料钢蓝拉开明度）
  element: {
    直接材料: '#4e79a7',   // 钢蓝
    直接人工: '#76b7b2',   // 青
    制造费用: '#f28e2c',   // 橙
  } as Record<string, string>,
  // 外环族内浅化：同族明度阶梯（组内可区分、组间色相分明）
  elementTint: {
    直接材料: ['#9ec2e3', '#c9def2', '#7aa7d2', '#b4d0ea', '#6491c2', '#d8e7f5'],
    直接人工: ['#b5d8d5'],
    制造费用: ['#ffd3a1'],
  } as Record<string, string[]>,
  fallback: ['#af7aa1', '#9c755f', '#bab0ab'],  // 未知要素/物料：紫/棕/灰（Tableau 尾色）
  peer: '#9ec2e3',                            // 对标方（二厂）：主色同族浅蓝，明度区分两方
  forecast: '#7a6fb5',                        // 预测（哑紫，与主色明确区分）
  forecastBand: 'rgba(122, 111, 181, 0.12)',  // 置信带：预测色 12% 透明铺底
  yoy: '#a8b4be',                             // 同比对照：浅灰虚线，不抢戏
  up: '#c0392b',                              // 方向信号：成本上升（不利）
  down: '#27a06c',                            // 方向信号：成本下降（有利）
  base: '#54687a',                            // 瀑布总量柱：深板岩灰蓝（D7 加深——淡色无存在感）
  heat: ['#5aa88f', '#f7f9fa', '#cd6f62'],    // 热力发散：中低饱和绿-白-红
  text: '#5d6d7e',
  axisLabel: '#8496a5',
  axisLine: '#d5dde5',
  splitLine: '#edf1f5',
} as const

/** 要素色：知名要素取 Tableau 分类色；未知名按字符码确定性落到 fallback（稳定不乱跳） */
export function elementColor(name: string): string {
  const hit = CT.element[name]
  if (hit) return hit
  const code = [...name].reduce((a, c) => a + c.charCodeAt(0), 0)
  return CT.fallback[code % CT.fallback.length]!
}

/** 坐标轴/文字公共样式（灰阶，不做视觉噪音） */
const axisCommon = {
  axisLabel: { color: CT.axisLabel },
  axisLine: { lineStyle: { color: CT.axisLine } },
}
const yAxisCommon = {
  ...axisCommon,
  splitLine: { lineStyle: { color: CT.splitLine } },
}
const textStyle = { color: CT.text }

export function trendOption(s: SeriesResp, f?: ForecastResp | null,
                            alertMark?: { month: string; count: number } | null) {
  const lines = [
    { name: '单位成本', data: s.unit_cost },
    ...Object.entries(s.series).map(([name, data]) => ({ name, data })),
  ]
  const withForecast = f != null
  // 有预测时 x 轴扩展到 9 个月，历史线尾部补 null 占位（纯摆放，不涉计算）
  const months = withForecast ? f.months_ext : s.months
  const padTail = (arr: number[]) =>
    withForecast ? [...arr, ...Array(f.months_ext.length - arr.length).fill(null)] : arr
  // F3 V4 联动：当前月有告警时，在单位成本主线上钉红色 pin（数量即告警条数）
  const alertIdx = alertMark ? s.months.indexOf(alertMark.month) : -1
  const alertPin = alertMark && alertIdx >= 0 ? {
    symbol: 'pin', symbolSize: 36,
    itemStyle: { color: CT.up },
    label: { formatter: String(alertMark.count), color: '#fff', fontSize: 11 },
    data: [{ coord: [alertMark.month, s.unit_cost[alertIdx]],
             name: `${alertMark.month} 触发 ${alertMark.count} 条告警` }],
  } : null
  const series: unknown[] = lines.map((l, i) => ({
    name: l.name, type: 'line', smooth: true, data: padTail(l.data),
    // 主角深海军蓝加粗；要素线取 Tableau 分类色（与环形图内环同色，跨图可追踪）
    lineStyle: i === 0 ? { color: CT.main, width: 2.5 } : { color: elementColor(l.name), width: 1.8 },
    itemStyle: { color: i === 0 ? CT.main : elementColor(l.name) },
    symbolSize: i === 0 ? 6 : 4,
    emphasis: { focus: 'series' as const },
    ...(i === 0 && alertPin ? { markPoint: alertPin } : {}),
  }))
  const legendNames = lines.map((l) => l.name)

  if (withForecast) {
    series.push(
      { // 置信带下沿：透明线，仅作堆叠基底（坐标后端预计算）
        name: 'band-lower', type: 'line', stack: 'fc-band',
        data: f.band_lower_line, lineStyle: { opacity: 0 }, symbol: 'none', silent: true,
      },
      { // 置信带厚度：upper-lower 已由后端算好，前端只做 stack
        name: '80% 置信带', type: 'line', stack: 'fc-band',
        data: f.band_diff_line, lineStyle: { opacity: 0 }, symbol: 'none', silent: true,
        areaStyle: { color: CT.forecastBand },
        itemStyle: { color: CT.forecast },  // 图例色块与带体同色（E2E 实测发现默认调色板错位）
      },
      { // Holt 点预测虚线（首段与最后历史点衔接，由后端 forecast_line 给出）
        name: 'Holt 预测', type: 'line', data: f.forecast_line,
        lineStyle: { type: 'dashed' as const, color: CT.forecast, width: 2 },
        itemStyle: { color: CT.forecast }, symbol: 'circle', symbolSize: 6,
      },
      { // 同比外推对照线：浅灰点线，仅作参照不抢视觉
        name: '同比对照', type: 'line', data: f.yoy_line,
        lineStyle: { type: 'dotted' as const, color: CT.yoy, width: 2 },
        itemStyle: { color: CT.yoy }, symbol: 'triangle', symbolSize: 6,
      },
    )
    legendNames.push('80% 置信带', 'Holt 预测', '同比对照')
  }

  return {
    textStyle,
    tooltip: { trigger: 'axis' },
    legend: { top: 0, data: legendNames, textStyle: { color: CT.text } },
    grid: { left: 48, right: 16, top: 56, bottom: 28 },  /* legend 窄宽换行时留出第二行空间（实测与刻度重叠） */
    xAxis: { type: 'category', data: months, ...axisCommon },
    yAxis: { type: 'value', name: '元/盒', ...yAxisCommon },
    series,
    ...(withForecast ? {
      graphic: [{ // 演示级水印：预测不可作决策依据（note 的看板落地）
        type: 'text', right: 12, bottom: 2,
        style: { text: '预测为演示级 · 仅供方向参考', fontSize: 10, fill: '#aab4bd' },
      }],
    } : {}),
  }
}

export function waterfallOption(w: WaterfallResp) {
  const cats = w.segments.map((s) => s.name)
  return {
    textStyle,
    tooltip: {
      trigger: 'axis',
      formatter: (ps: Array<{ dataIndex: number }>) => {
        const seg = w.segments[ps[0]?.dataIndex ?? 0]
        if (!seg) return ''
        const head = `${seg.name}<br/>水位: ${seg.start} → ${seg.end} 元/盒`
        return seg.type === 'delta'
          ? `${head}<br/>变动: ${seg.value > 0 ? '+' : ''}${seg.value}`
          : head
      },
    },
    grid: { left: 48, right: 16, top: 32, bottom: 60 },
    xAxis: { type: 'category', data: cats,
      // 窄侧列实测：全名"上月(2026-04)"必重叠——轴标签短化为"上月/本月"（全名保留在 tooltip），
      // 旋转加深 + 字号缩小，纯显示层变换不涉数据
      axisLabel: { interval: 0, rotate: 28, fontSize: 10, color: CT.axisLabel,
        formatter: (name: string) => name.replace(/^(上月|本月)\(.+\)$/, '$1') },
      axisLine: axisCommon.axisLine },
    yAxis: { type: 'value', name: '元/盒', ...yAxisCommon },
    series: [
      { // 透明基底：后端预计算的 transparent_base，前端零计算
        name: 'base', type: 'bar', stack: 'wf',
        itemStyle: { color: 'transparent' },
        emphasis: { itemStyle: { color: 'transparent' } },
        data: w.segments.map((s) => s.transparent_base),
      },
      {
        name: 'value', type: 'bar', stack: 'wf',
        // 红/绿只给方向信号（升=不利红 / 降=有利绿），总量柱中性灰蓝——本图仅有的三种色
        data: w.segments.map((s) => ({
          value: s.visible,
          itemStyle: {
            color: s.direction === 'up' ? CT.up
              : s.direction === 'down' ? CT.down : CT.base,
          },
          label: {
            show: true, position: 'top' as const, color: CT.text, fontSize: 10,
            formatter: () => (s.type === 'delta'
              ? `${s.value > 0 ? '+' : ''}${s.value}` : `${s.value}`),
          },
        })),
      },
    ],
  }
}

export function structureOption(s: StructureResp) {
  // 族内浅化计数器：同一父要素的物料切片依次取明度阶梯（组内可区分，组间色相分明）
  const tintCounter: Record<string, number> = {}
  const tintOf = (parent: string | undefined): string => {
    const fam = parent ?? ''
    const tints = CT.elementTint[fam]
    const i = (tintCounter[fam] = (tintCounter[fam] ?? 0) + 1) - 1
    return tints ? tints[i % tints.length]! : '#bab0ab'  // 未知父级落 Tableau 灰
  }
  return {
    textStyle,
    tooltip: { trigger: 'item', formatter: '{b}: {c} 元/盒' },
    // 滚动图例：窄侧列下图例只占一行（翻页箭头），不再吃掉半个图表区（实测重叠根因之一）
    legend: {
      bottom: 0, type: 'scroll' as const, itemWidth: 12, itemHeight: 12,
      textStyle: { color: CT.text, fontSize: 11 },
      pageIconColor: CT.main, pageTextStyle: { color: CT.text },
    },
    series: [
      {
        name: '成本要素', type: 'pie', radius: ['0%', '42%'],
        // 饼心上移：底部让给 legend，避免外圈标签与图例文字互叠（E2E 实测发现）
        center: ['50%', '44%'],
        // 窄饼心实测：'{b}\n{c}' 名称+数值三行必重叠——内环只放数值，
        // 名称由图例/悬浮框承担（颜色→名称映射在图例里已有，不丢信息）
        label: { position: 'inner' as const, formatter: '{c}', color: '#fff', fontSize: 11 },
        // 内环 = 三要素分类色（与趋势图要素线同色，跨图一致）
        data: s.inner.map((it) => ({
          name: it.name, value: it.value,
          itemStyle: { color: elementColor(it.name) },
        })),
      },
      {
        name: '明细', type: 'pie', radius: ['55%', '72%'],
        center: ['50%', '44%'],
        // 小份额物料（占比<5%）不显示文字标签，彻底避免标签间/标签与图例互叠；
        // 窄列下长名（如"包装材料(盒+说明书)"）截断到 72px，悬浮框保留全名与数值
        label: {
          color: CT.text, fontSize: 10, width: 72, overflow: 'truncate' as const,
          formatter: (p: { name: string; percent?: number }) =>
            (p.percent ?? 100) < 5 ? '' : p.name,
        },
        labelLayout: { hideOverlap: true },
        // 外环 = 父要素色相的浅化族：一眼看出"这些切片都属于材料"，族内靠明度阶梯区分
        data: s.outer.map((o) => ({
          name: o.name, value: o.value,
          itemStyle: { color: tintOf(o.parent) },
        })),
      },
    ],
  }
}

// 注：heatmapOption 已于"表格式热力图"改造（方案二+产品分区）移除。
// 数据端点 /api/charts/heatmap 不变；渲染由 components/HeatTable.vue + heatTable.ts 承接，
// 选中高亮与点击联动口径不变（纯函数见 heatTable.isSelCell）。

/** F9 蝶形对比图（龙卷风图）：中轴=要素，左展一厂、右展二厂。
 *  一厂值取负仅为"显示镜像"（与轴标签短化同级的展示变换，不是数据计算）；
 *  tooltip 展示绝对值与后端预生成的双向差异率（只读）。 */
export function butterflyOption(b: BenchmarkResp) {
  const rows = b.rows
  const elements = rows.map((r) => r.element)
  // 对称量程：取两方最大值的 1.12 倍留白（纯显示摆放）
  const maxV = Math.max(...rows.flatMap((r) => [r.main, r.bench]), 1)
  const pad = Math.ceil(maxV * 1.12 * 100) / 100
  const fmtRate = (v: number | null) =>
    v === null ? '—' : `${v > 0 ? '+' : ''}${v}%`
  return {
    textStyle,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' as const },
      formatter: (ps: Array<{ dataIndex: number }>) => {
        const r = rows[ps[0]?.dataIndex ?? 0]
        if (!r) return ''
        return `${r.element}<br/>一厂: ${r.main} 元/盒<br/>二厂: ${r.bench} 元/盒<br/>` +
          `差异率: ${fmtRate(r.diff_rate_pct)}（对二厂） / ${fmtRate(r.reverse_rate_pct)}（对一厂）`
      },
    },
    legend: { top: 0, data: ['一厂', '二厂'], textStyle: { color: CT.text } },
    grid: { left: 80, right: 80, top: 34, bottom: 28 },
    xAxis: {
      type: 'value', min: -pad, max: pad,
      axisLabel: { color: CT.axisLabel, formatter: (v: number) => String(Math.abs(v)) },
      splitLine: { lineStyle: { color: CT.splitLine } },
    },
    yAxis: { type: 'category', data: elements, ...axisCommon, axisTick: { show: false } },
    series: [
      {
        name: '一厂', type: 'bar', stack: 'bf',
        itemStyle: { color: CT.main, borderRadius: [4, 0, 0, 4] },
        label: { show: true, position: 'left' as const, color: CT.text, fontSize: 11,
          formatter: (p: { dataIndex: number }) => String(rows[p.dataIndex]?.main ?? '') },
        data: rows.map((r) => -r.main),  // 显示镜像：取负仅用于左展，数值本体不变
      },
      {
        name: '二厂', type: 'bar', stack: 'bf',
        itemStyle: { color: CT.peer, borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: 'right' as const, color: CT.text, fontSize: 11,
          formatter: (p: { dataIndex: number }) => String(rows[p.dataIndex]?.bench ?? '') },
        data: rows.map((r) => r.bench),
      },
    ],
  }
}
