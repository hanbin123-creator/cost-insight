import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    // vendor-echarts 按需引入后仍有 576KB（gzip 193KB）：已是热力图/可视映射等
    // 必需组件的真实体积；它是长期不变的 vendor 块，长缓存一次下载终身复用。
    // 阈值提到 600 只为豁免这个已知大块；业务主块当前 55KB，
    // 若将来异常膨胀越过 600 仍会报警
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // chunk 拆分（消除 666KB 警告）：echarts/zrender 与 vue 运行时各自成块，
        // 浏览器并行加载 + 长缓存独立失效；业务代码保持主块。
        // 函数形式按包名归组——对象形式会让 zrender 漏进 vue 块
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (/node_modules[\\/](echarts|zrender)[\\/]/.test(id)) return 'vendor-echarts'
          return 'vendor-vue'
        },
      },
    },
  },
  server: {
    proxy: {
      // 后端 FastAPI；未启动时前端各面板显示错误卡片（三态防线）
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
