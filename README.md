# cost-insight · 制药企业产品成本智能分析系统

[![compose-smoke](../../actions/workflows/compose-smoke.yml/badge.svg)](../../actions/workflows/compose-smoke.yml)

> 2026 年第二届重庆市 AI 大模型创新应用大赛 · 创灵境赛题
> 设计哲学：**大模型永不算数**——所有数字由代码计算（SQLite/Pandas），大模型只做意图理解与文字表达，数字与文字之间用 schema 闸门与自动对账隔离。

## 第 0 步：克隆并进入项目目录（后面所有命令都在这个目录里执行）

```bash
git clone https://github.com/hanbin123-creator/cost-insight.git
cd cost-insight        # ← 漏了这一步，后面所有命令都会报"找不到文件"
```

## 一键启动（Docker）

前置条件：Docker Desktop；考题数据包放在本仓库**同级目录**（`../创灵境_考题模拟数据`，保密数据不入库）。

```bash
# 基础两容器（app: FastAPI+LibreOffice+中文字体+向量索引全内置 / web: nginx 反代 SPA）
docker compose up --build

# 国内网络构建慢时（实测默认源仅数十 KB/s），传镜像参数加速（默认全上游源，可选）：
docker compose build --build-arg APT_MIRROR=mirrors.aliyun.com \
    --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    --build-arg NPM_REGISTRY=https://registry.npmmirror.com

# 需要整改闭环演示时，叠加官方 mock RPA（数据包自带 Dockerfile，现场构建）
docker compose -f docker-compose.yml -f docker-compose.rpa.yml up --build
```

- 浏览器打开 **http://localhost/**（成本看板）；API 文档 **http://localhost:8000/docs**
- LLM 接入（可选）：仓库根放 `.env` 写入 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`（OpenAI 兼容格式）。
  **不配也能跑**——意图路由自动降级规则兜底，报告文字降级模板生成，界面如实标注降级层，不放假数据。
- 无考题数据包也能预览界面：`docker compose -f docker-compose.yml -f docker-compose.ci.yml up --build`
  （`placeholder-data/` 为合成占位数据，仅演示用）。
- 报告模板不入库：`assets/report_template.docx` 属赛题保密资源，Docker 启动时由 entrypoint
  自动从挂载的数据包复制；本地开发请手动将数据包 `04_报告模板/月度成本分析报告模板.docx`
  复制为该路径。缺模板时报告接口给出明确中文报错，其余功能不受影响。

每次 push 由 GitHub Actions 真机执行 `compose build + up --wait + curl 冒烟`（见顶部徽章），
一键启动可达性由 CI 持续背书。

## 开源致谢

本项目代码为原创；第三方开源组件（Noto Sans SC 字体 OFL-1.1、bge-small-zh-v1.5 模型 MIT、
FastAPI/Pandas/Vue/ECharts 等依赖）的来源与许可证见 [NOTICE.md](NOTICE.md)。

## 本地开发启动

> 确认终端已在 `cost-insight/` 目录内（第 0 步）。前端需**另开一个终端**窗口。
> 知识库索引**首次启动自动构建**（约 30 秒，日志可见）；手动重建用 `python -m app.kb`。

```bash
pip install -r requirements.txt
python -m uvicorn app.api:app --host 127.0.0.1 --port 8000     # 后端（此窗口保持开启）

# 另开一个终端：
cd cost-insight/web && npm ci && npm run dev                   # 前端（5173，代理至 8000）

# 整改闭环需要官方 mock RPA（再开一个终端）：
cd ../创灵境_考题模拟数据/05_RPA接口文档 && python mock_rpa_server.py   # 8090
```

## 功能地图

| 板块 | 入口 | 说明 |
|---|---|---|
| 成本看板 | `/` | KPI、趋势/结构/瀑布图、产品×月份×要素热力图（点击联动）、±10% 波动告警 |
| 对标分析 | `/benchmark` | 一厂 vs 二厂三步法差异树；双向口径代码算好 + 无歧义中文描述，下游只读不算 |
| 整改追踪 | `/rectify` | 告警→任务装配（schema 闸不过不发）→RPA 下发→微信推送→状态追踪；幂等双向核实 |
| 报告中心 | `/reports` | 月度/季度/专题 Word+PDF；LLM 撰文、代码对账，校验不过不出货 |
| 知识库 | `/kb` | RAG 结构化切片 + 图谱化检索 + 编号级精确通道；文档热更新 |
| Agent 助手 | 右下角抽屉 | 意图路由三层：LLM 主线 → 规则兜底 → 低置信规则仲裁（rule-arb）；域外显式拒答、不明给四入口——不猜、不编造参数 |

## 测试与质量

- 后端 **174 项 pytest**（167 个测试函数含参数化展开；计算对账误差 0、路由仲裁边界、schema 闸、幂等核实）：`pytest tests/`
- 前端 **76 项 vitest**（视图模型纯函数）：`cd web && npm run test`
- 断网韧性：LLM/RPA 缺席自动降级且如实标注，服务不炸（CI 冒烟环境即无 LLM 密钥，顺带验证此路径）

## 目录速览

```
app/            后端六大板块：ingest / compute / retrieve+kb / generate / render / act
  config.py     全部配置唯一出处 · agent.py 意图路由 · pipeline.py 场景编排
web/            Vue3 + ECharts 前端（五页面 + Agent 抽屉）
scripts/        工具链（占位数据生成 / 实弹检查 / 消防演练）
placeholder-data/  合成占位数据（非考题数据，供 CI 与无数据包预览）
docs/           开发日志（每个增量的决策/优点/缺点/验证四段式）
docker-compose.yml / .rpa.yml / .ci.yml   一键启动三件套
```

## 合规说明

- 考题数据包与 LLM 密钥**不入库**：数据只读挂卷、密钥运行时注入（`.env` 已 gitignore）
- 开源依赖全为 MIT/Apache/BSD 系；细节见 `docs/` 各开发日志
