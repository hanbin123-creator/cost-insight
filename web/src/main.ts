import { createApp } from 'vue'
import './tokens.css'
import VueECharts from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, HeatmapChart, LineChart, PieChart } from 'echarts/charts'
import {
  GraphicComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import App from './App.vue'

use([BarChart, HeatmapChart, LineChart, PieChart,
  GraphicComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent,
  CanvasRenderer])

const app = createApp(App)
app.component('v-chart', VueECharts)

// 运行期防线：任何组件错误不导致白屏（第七章缺点①第三层）
app.config.errorHandler = (err) => {
  console.error('[errorHandler]', err)
}

app.mount('#app')
