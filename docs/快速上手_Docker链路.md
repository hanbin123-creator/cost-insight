# 快速上手 · Docker 链路（评委 / 演示专用）

> 这条路只需要 Docker Desktop，不需要装 Python / Node。
> 全程约 5–10 分钟（首次构建镜像占大头）。另一条路（本地源码开发）见
> [快速上手_本地开发链路.md](快速上手_本地开发链路.md)。

## 前置检查（30 秒）

打开终端（Windows 用 PowerShell 或 CMD，macOS 用终端），执行：

```bash
docker version
```

- **能看到 Client 和 Server 两段版本信息** → 通过，继续。
- 报 `error during connect` / `dockerDesktopLinuxEngine` → Docker Desktop 装了但**没启动**，先打开 Docker Desktop 等鲸鱼图标变绿。
- 报 `不是内部或外部命令` / `command not found` → 没装 Docker Desktop，先去 https://www.docker.com/products/docker-desktop/ 安装。

## 第 1 步：克隆并进入项目目录（后面所有命令都在这个目录里执行）

```bash
git clone https://github.com/hanbin123-creator/cost-insight.git
cd cost-insight
```

⚠️ `cd cost-insight` 不能省——后面所有命令都假设你站在这个目录里。

## 第 2 步：放好考题数据包

数据包属赛题保密资源，**不在仓库里**，需单独获取并放到本仓库的**同级目录**：

```
你的文件夹/
├── cost-insight/            ← 刚克隆的仓库
└── 创灵境_考题模拟数据/      ← 考题数据包放这里（与仓库同级）
```

放别处也可以，启动前设环境变量 `COST_INSIGHT_DATA_DIR` 指向数据包目录即可。

**没有数据包也想先看界面？** 跳到本节末尾的"无数据包预览"。

## 第 3 步：一条命令启动

```bash
docker compose up --build
```

首次构建镜像约 5–10 分钟（取决于网络）。国内网络构建过慢时，先 `Ctrl+C` 停掉，换加速参数重跑：

```bash
docker compose build --build-arg APT_MIRROR=mirrors.aliyun.com \
    --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    --build-arg NPM_REGISTRY=https://registry.npmmirror.com
docker compose up
```

**需要演示整改闭环（告警→任务→RPA→微信推送）时**，叠加数据包自带的 mock RPA：

```bash
docker compose -f docker-compose.yml -f docker-compose.rpa.yml up --build
```

## 第 4 步：确认启动成功

看到日志出现 `Application startup complete` 且不再滚动报错后：

| 检查 | 方法 | 预期 |
|---|---|---|
| 看板页面 | 浏览器打开 http://localhost/ | 出现"成本看板"，KPI/趋势/结构图正常渲染 |
| 数据就位 | 看板产品与月份 | 3 个产品 × 6 个月，不是空页面 |
| API | 浏览器打开 http://localhost:8000/docs | FastAPI 文档页 |
| 报告模板 | 报告中心生成一份月报 | 正常出 Word/PDF（模板由启动脚本自动从数据包复制） |

## 可选：接入大模型

不接也能跑（意图路由降级规则兜底、报告降级模板生成、界面如实标注降级层，**不放假数据**）。
要接：在 `cost-insight/` 目录新建 `.env` 文件，写入：

```
LLM_BASE_URL=<OpenAI 兼容接口地址>
LLM_API_KEY=<密钥>
LLM_MODEL=<模型名>
```

`.env` 已在 gitignore 中，不会被提交。

## 无数据包预览（合成占位数据）

```bash
docker compose -f docker-compose.yml -f docker-compose.ci.yml up --build
```

界面功能完整可看，数据为 `placeholder-data/` 合成数据，仅演示用。

## 停止与清理

```bash
docker compose down          # 停止
docker compose down -v       # 停止并删除数据卷（想从干净状态重来时用）
```

## 撞坑速查表

| 报错原文 / 现象 | 原因 | 解法 |
|---|---|---|
| `error during connect: ... dockerDesktopLinuxEngine ...` | Docker Desktop 没启动 | 打开 Docker Desktop，等图标就绪后重跑 |
| `Bind for 0.0.0.0:80 failed: port is already allocated` | 80 端口被别的程序占了 | 关掉占用者（常见于 IIS/其他 nginx），或改用 8080：编辑 `docker-compose.yml` 里 web 的 ports 为 `"8080:80"`，访问 http://localhost:8080/ |
| 构建卡在下载依赖、速度仅几十 KB/s | 默认海外源被限速 | 用第 3 步的镜像加速参数重建 |
| 换过数据后界面还是旧数据 | 数据卷残留 | `docker compose down -v` 后重新 `up --build` |
| 报告接口报"报告模板缺失" | 数据包没放好，模板复制失败 | 检查第 2 步的目录层级，或确认 `COST_INSIGHT_DATA_DIR` 指向正确 |
| 看板打开是 404 / 白屏 | web 容器没起来或旧前端缓存 | `docker compose ps` 查状态；浏览器 `Ctrl+F5` 强刷 |
