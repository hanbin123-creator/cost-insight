# 开发日志 12 · 前端增量 4：Agent 抽屉 + 整改看板（2026-09-21 早）

对应功能选型 F5（V1 右侧抽屉 + V5 决策卡片流）与 F7（V1 看板三列 + V5 告警卡联动）。
vitest 42 项全绿（新增 agent-cards.test.ts 8 项）、vite build 通过、真后端浏览器 E2E 实测。
本增量起项目纳入 git（基线 f7425aa；.env 已移出跟踪，密钥不进版本库）。

## D1 F5 Agent 右侧抽屉（`AgentDrawer.vue`）

- **决策**：FAB 从"toast 预告"升级为真入口——点击开合 340px 右侧抽屉（0.22s 滑入）。
  每次提问自动注入当前页上下文（`store.product/month`，头部常驻标注"自动注入"），
  用户无需重复报参。回复按后端四态渲染：场景卡片（看板/对标/报告/整改）、
  澄清（缺参数原样展示）、四入口（choices 按钮点击即发送）、错误如实展示；
  卡片底部标注 意图/置信度/路由层（llm/rule/fallback），路由透明化。
- **V5 决策卡片流**：打开抽屉即按当前上下文取 /api/agent/decision——
  建议生成归因时浮出决策卡（理由 + [确认生成归因][忽略]）；确认经
  `store.attributionRequest` 计数器跨视图触发看板页生成（watch 驱动，松耦合）。
- **优点**：Agent 从"页底一个按钮"升格为全局助理；上下文注入让"看板速览"
  三个字就能得到当前产品当前月的答案（实测：规则兜底轨 conf=0.9 命中
  dashboard 场景，卡片正确）；决策建议以"卡片+确认"嵌入对话而非自动执行——
  人始终在最后确认位。
- **缺点**：消息不持久化（关抽屉/刷新即清空——会话级助理定位，企业化需落库）；
  报告场景返回的是文件路径文本而非下载按钮（F8 报告中心落地后联动改造）；
  低置信时四入口卡片依赖用户再点一次（刻意的"不猜"，不是缺陷但多一步操作）。
- **验证**：E2E——FAB 开抽屉、上下文标注正确、决策卡理由与看板横幅一致、
  发送"看板速览"返回 dashboard 卡片（单位成本 11.21 / 环比 +2.8% / 告警 1 条）。

## D2 F7 整改追踪看板（`RectifyView.vue`）

- **决策**：顶部聚合条（已生成/已送达/已确认 + 优先级分布胶囊）+ 看板三列
  （待下发/整改中/已复核，`kanbanColumn` 纯函数归并 RPA 原生状态）；
  演示速度选择器（标准/FAST/DONE/OVERDUE）+ 页内下发按钮（驱动官方 mock
  状态机，评审演示可现场闭环）；RPA 不可达 → 如实状态卡 + 恢复路径，
  **看板区不渲染任何假数据**。
- **状态归并口径**：completed→已复核；received/confirmed/in_progress→整改中；
  其余（含 dispatch_failed）→待下发——失败任务回待下发列等待重发，不消失。
- **优点**：状态真源在 RPA 侧实时拉取（与后端 tracking 契约一致）；三列归并
  是纯函数可单测；不可达时的界面本身就是"诚实降级"的评审证据。
- **缺点**：RPA 不可达时页面主体为空（只有状态卡）——信息少但诚实，mock
  启动后立即丰满；看板卡不支持拖拽改状态（RPA 是状态真源，前端无权改，
  拖拽会造假——刻意不做）；tracking 拉取在不可达时要等 RPA_TIMEOUT（约 5s）
  才返回，有等待感（加载态文案兜底）。
- **验证**：E2E——RPA 未启动时显示"RPA 服务不可达：[WinError 10061]…"状态卡
  与恢复指引，看板区零假数据；groupTasks/kanbanColumn 单测 3 项锁定归并口径。

## 本增量文件清单

- 新增：`src/components/AgentDrawer.vue`、`src/views/RectifyView.vue`、
  `src/agentCards.ts`（纯函数）、`src/__tests__/agent-cards.test.ts`（8 项）
- 修改：`src/types.ts`（Chat*/RpaTask/TrackingResp）、`src/api.ts`
  （chat/rectifyTracking/dispatch 支持 speed）、`src/store.ts`
  （attributionRequest 计数器）、`src/App.vue`（FAB 开合抽屉、整改路由接入、
  toast 退役）、`src/views/DashboardView.vue`（决策确认跨视图触发）
- 后端零改动（pytest 155 项基线不受影响）。

## 已知遗留

1. 抽屉消息不持久化（会话级定位；企业化落库）。
2. 报告场景卡片暂为文本路径，待 F8 联动为下载入口。
3. tracking 不可达时约 5s 超时等待（加载态已兜底）。
4. chunk 体积警告仍在（manualChunks 拆分排入增量 5 收尾）。
