"""模块二服务层：FastAPI 端点 + Agent 自主决策规则（加分项 6.2）。

设计要点：
- 全部图表数据来自 ChartBuilder 预计算（下游永不计算）
- Agent 决策规则：有告警 → 建议自动生成归因；无告警 → 仅刷新看板
  （规则引擎实现，确定性、可解释——这同时是 5.2.3"自动生成重点分析段落"的触发逻辑）
- LLM 未配置时归因端点返回 503 + 明确说明，不静默降级（前端据此显示演示模式入口）
- 同步 LLM 调用放线程池，不阻塞事件循环（C4 修订的落实）
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import config as C
from .charts import ChartBuilder
from .compute import CostCalculator
from .forecast import Forecaster
from .generate import generate_attribution
from .ingest import init_store
from .llm import LLMClient, LLMError
from .retrieve import Retriever


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init()
    # RPA 探活（手册"启动探活"挂点）：外部依赖不可达 → 警告降级，不拒绝启动
    from .act import probe
    if await run_in_threadpool(probe):
        print("[startup] RPA 服务在线（整改任务闭环可用）")
    else:
        print("[startup] 警告: RPA 服务不可达——整改任务下发将降级为 dispatch_failed，"
              "追踪页显示不可达。请启动官方 mock（数据包 05_RPA接口文档）")
    yield


app = FastAPI(title="创灵境成本分析 API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class _State:
    """服务级单例：启动时一次性构建（测试用 lru_cache 复用）。"""
    store = calc = charts = retriever = forecaster = None


@lru_cache(maxsize=1)
def _init() -> None:
    _State.store, _ = init_store()
    _State.calc = CostCalculator(_State.store)
    _State.charts = ChartBuilder(_State.calc)
    _State.retriever = Retriever()
    _State.forecaster = Forecaster(_State.calc)


def _try_llm(role: str = "generation"):
    """LLM 就绪则返回客户端，否则 None（不抛异常——由端点决定 503）。
    role 透传给 LLMClient 角色档案：generation / classification / polish。"""
    try:
        return LLMClient(role=role)
    except LLMError:
        return None


# ---------- 基础数据 ----------
@app.get("/api/products")
def products() -> dict:
    _init()
    return {"products": C.PRODUCTS, "months": [f"2026-{m:02d}" for m in range(1, 7)]}


@app.get("/api/series/{product}")
def series(product: str) -> dict:
    _init()
    return _State.charts.series_data(product)


@app.get("/api/charts/waterfall/{product}/{month}")
def waterfall(product: str, month: str) -> dict:
    _init()
    try:
        return _State.charts.waterfall_data(product, month)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/charts/structure/{product}/{month}")
def structure(product: str, month: str) -> dict:
    _init()
    return _State.charts.structure_data(product, month)


@app.get("/api/charts/heatmap")
def heatmap() -> dict:
    _init()
    return _State.charts.heatmap_data()


@app.get("/api/forecast/{product}")
def forecast(product: str) -> dict:
    """趋势预测延伸带（加分项 · 演示级）：Holt 阻尼趋势 + 80% 置信带 + 同比对照。"""
    _init()
    return _State.forecaster.forecast(product)


@app.get("/api/metrics/{product}/{month}")
def metrics(product: str, month: str) -> dict:
    _init()
    try:
        return _State.calc.metrics(product, month).model_dump()
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/metrics/quarter/{product}/{quarter}")
def metrics_quarter(product: str, quarter: str) -> dict:
    """季度指标包（赛题 5.1.3 季度主题）：产量加权口径，要素环比对上季度。"""
    _init()
    if quarter not in ("Q1", "Q2"):
        raise HTTPException(422, "quarter 须为 Q1/Q2")
    try:
        return _State.calc.quarter_pack(product, quarter).model_dump()
    except KeyError as e:
        raise HTTPException(404, str(e))


# ---------- Agent 自主决策（加分项 6.2） ----------
@app.get("/api/agent/decision/{product}/{month}")
def agent_decision(product: str, month: str) -> dict:
    """规则引擎决策：系统自主判断"需要生成报告还是仅更新看板"。

    规则（确定性、可解释）：
    - 存在任一通道告警 → generate_attribution（有异常需要解释）
    - 无告警但 |单位成本环比| > 3% → generate_attribution（温和异动，值得说明）
    - 其余 → dashboard_only（平稳月份不打扰）
    """
    _init()
    pack = _State.calc.metrics(product, month)
    mom = pack.unit_cost_mom_pct or 0.0
    if pack.alerts:
        action, reason = "generate_attribution", f"触发 {len(pack.alerts)} 条告警：" + \
            "；".join(a.message for a in pack.alerts[:2])
    elif abs(mom) > 3.0:
        action, reason = "generate_attribution", f"单位成本环比 {mom:+.1f}%，属温和异动"
    else:
        action, reason = "dashboard_only", f"单位成本环比 {mom:+.1f}%，运行平稳"
    return {"product": product, "month": month, "action": action,
            "reason": reason, "engine": "rule-based-v1"}


# ---------- 归因生成 ----------
class AttributionRequest(BaseModel):
    product: str
    month: str


@app.post("/api/attribution")
async def attribution(req: AttributionRequest) -> dict:
    _init()
    llm = _try_llm()
    if llm is None:
        raise HTTPException(503, "LLM 未配置（LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）；"
                                 "前端应切换演示模式展示校验机制")
    try:
        # 同步 LLM 调用放线程池，不阻塞事件循环（C4 修订落实）
        report = await run_in_threadpool(
            generate_attribution, _State.calc, _State.retriever, llm,
            req.product, req.month)
        return report.model_dump()
    except KeyError as e:
        raise HTTPException(404, str(e))


# ---------- 板块3 报告生成 ----------
class ReportRequest(BaseModel):
    product: str
    month: str = ""           # monthly/topical 必填；quarterly 忽略（锚定季末月）
    theme: str = "monthly"    # monthly / quarterly / topical（赛题 5.1.3 三主题）
    quarter: str | None = None  # theme=quarterly 时必填：Q1 / Q2


@app.post("/api/report")
async def report(req: ReportRequest) -> dict:
    """成本分析报告（docx + 可选 PDF），支持月度/季度/专题三主题。

    与归因端点不同：报告的表格/数字/嵌图全部代码算好，无 LLM 也能产出完整报告
    （叙述段落走模板句兜底并标注来源），因此无 LLM 返回 200 而非 503。"""
    _init()
    from .compute import CostCalculator
    from .render import build_report  # 延迟导入：docxtpl/matplotlib 非热路径
    if req.theme == "quarterly":
        if req.quarter not in ("Q1", "Q2"):
            raise HTTPException(422, "theme=quarterly 须指定 quarter=Q1/Q2")
        month = CostCalculator.QUARTER_MONTHS[req.quarter][-1]  # 图表/对标锚定季末月
    else:
        if not req.month:
            raise HTTPException(422, "monthly/topical 主题须指定 month（YYYY-MM）")
        month = req.month
    out_dir = Path(__file__).resolve().parent.parent / "reports"
    try:
        result = await run_in_threadpool(
            build_report, _State.calc, _State.retriever, _try_llm(),
            req.product, month, out_dir, req.theme, req.quarter)
        return result
    except KeyError as e:
        raise HTTPException(404, str(e))


# ---------- 报告归档（F8 报告中心：列表 + 下载） ----------
_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
_REPORT_SUFFIXES = (".docx", ".pdf")


def _parse_report_name(p: Path) -> dict | None:
    """'银黄口服液_2026-05_月度成本分析报告.docx' → {product, period, theme}；
    命名不符（如临时文件、图表 png）返回 None，由调用方如实列入 unknown。"""
    stem = p.name
    for suffix in ("成本分析报告.docx", "成本分析报告.pdf"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    else:
        return None
    parts = stem.rsplit("_", 2)   # 产品名不含下划线（数据包口径），右切两段最稳
    if len(parts) != 3 or not all(parts):
        return None
    return {"product": parts[0], "period": parts[1], "theme": parts[2]}


@app.get("/api/reports")
def report_list() -> dict:
    """报告归档清单：扫 reports/，docx/pdf 按同 stem 归组，mtime 倒序。
    解析失败的文件列入 unknown_files 如实暴露，不静默丢弃。"""
    _REPORTS_DIR.mkdir(exist_ok=True)
    groups: dict[str, dict] = {}
    unknown: list[str] = []
    for p in _REPORTS_DIR.iterdir():
        if p.suffix.lower() not in _REPORT_SUFFIXES:
            continue
        meta = _parse_report_name(p)
        if meta is None:
            unknown.append(p.name)
            continue
        g = groups.setdefault(p.stem, {**meta, "docx": None, "pdf": None, "mtime": 0.0})
        g[p.suffix.lower().lstrip(".")] = {
            "name": p.name, "size_kb": round(p.stat().st_size / 1024, 1)}
        g["mtime"] = max(g["mtime"], p.stat().st_mtime)
    items = sorted(groups.values(), key=lambda g: g["mtime"], reverse=True)
    return {"reports": items, "unknown_files": sorted(unknown)}


@app.get("/api/reports/{filename}")
def report_download(filename: str) -> FileResponse:
    """报告下载：只认 reports/ 下命名合规的 docx/pdf，路径穿越与改名文件一律拒绝。"""
    name = Path(filename).name   # 防路径穿越：只取文件名
    if not name.lower().endswith(_REPORT_SUFFIXES):
        raise HTTPException(422, "仅允许下载 docx/pdf 报告文件")
    target = _REPORTS_DIR / name
    if not target.exists() or _parse_report_name(target) is None:
        raise HTTPException(404, f"报告不存在: {name}")
    return FileResponse(target, filename=name)


# ---------- 板块⑥ 行动闭环（RPA 整改任务） ----------
class RectifyDispatchRequest(BaseModel):
    product: str
    month: str
    speed: str | None = None   # 演示后缀 FAST/OVERDUE/DONE（官方 mock 状态机，文档第七节）


@app.post("/api/rectify/dispatch")
async def rectify_dispatch(req: RectifyDispatchRequest) -> dict:
    """告警 → 整改任务装配（schema 闸2 不过不发）→ RPA 发送 → 微信推送 → 落库。
    RPA 不可达时任务标 dispatch_failed 如实返回，不假装成功。"""
    _init()
    from .act import dispatch
    try:
        return await run_in_threadpool(
            dispatch, req.product, req.month, _State.calc, _try_llm("polish"), req.speed)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/rectify/tracking")
def rectify_tracking() -> dict:
    """任务追踪聚合（已生成/已送达/已确认/优先级分布）——状态真源在 RPA 侧，
    实时拉取聚合；RPA 不可达如实返回，不展示假数据。"""
    from .act import tracking
    return tracking()


# ---------- Agent 意图路由（加分项 6.4） ----------
class ChatRequest(BaseModel):
    text: str
    product: str | None = None   # 显式参数优先于文本抽取
    month: str | None = None


def _latest_month() -> str:
    df = _State.store.query(
        f'SELECT MAX("{C.COL_MONTH}") AS m FROM ('
        f'SELECT "{C.COL_MONTH}" FROM summary_2026 '
        f'UNION SELECT "{C.COL_MONTH}" FROM summary_2025)')
    return str(df.iloc[0]["m"])


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict:
    """Agent 意图路由入口：LLM 主线 → 规则兜底 → 低置信四入口（不猜）。
    路由只分发永不算数；场景经 Pipeline 执行，单场景失败如实降级。"""
    _init()
    from .agent import route
    from .llm import LLMError
    from .pipeline import Deps, Pipeline
    try:
        classifier = LLMClient(role="classification")
    except LLMError:
        classifier = None                     # 无 LLM → 规则兜底轨，服务不炸
    deps = Deps(calc=_State.calc, retriever=_State.retriever,
                charts=_State.charts, llm_factory=_try_llm)
    return await run_in_threadpool(
        route, req.text, Pipeline(deps), classifier, _latest_month(),
        req.product, req.month)


# ---------- 对标分析（薄端点：算好的双向口径直接透出） ----------
@app.get("/api/benchmark/{product}/{month}")
def benchmark(product: str, month: str) -> dict:
    """成本对标三步法的一、二步数据：双向差异率 + 代码预生成无歧义描述。
    前端/报告只读不算——口径转换已在 compute 层完成（大模型永不算数）。"""
    _init()
    try:
        return _State.calc.benchmark(product, month).model_dump()
    except KeyError as e:
        raise HTTPException(404, str(e))


# ---------- 知识库热更新（加分项"行业扩展"支撑，参照 Langchain-Chatchat 路由形态） ----------
# 决策记录：上传用 JSON+base64 而非 multipart——托管运行时无 python-multipart，
# 不新增依赖。缺点：体积 +33%、不适合大文件；竞赛文档 <5MB 可接受，
# 企业演进换回 multipart（路由签名不变，只换请求体解析）。
class KbUploadRequest(BaseModel):
    filename: str             # 须以 .pdf/.txt/.docx 结尾
    content_b64: str          # base64 编码的文件内容


_KB_JOB: dict = {"state": "idle", "detail": "", "chunks": 0}
_KB_SUFFIXES = (".pdf", ".txt", ".docx", ".doc")


def _reindex_job() -> None:
    """后台重建：切分 → 嵌入 → 向量/图谱/索引三件套落盘 → 换检索器单例。
    失败如实记录状态，不影响在线服务（旧索引继续服务——重建是旁路的）。"""
    from .kb import build_index
    _KB_JOB.update(state="running", detail="")
    try:
        chunks = build_index()
        _State.retriever = Retriever()      # 索引落盘后换检索器，热更新生效
        _KB_JOB.update(state="done", chunks=len(chunks))
    except Exception as e:                  # noqa: BLE001 —— 后台任务须兜底
        _KB_JOB.update(state="failed", detail=f"{type(e).__name__}: {e}")


# ---------- 知识库（F10：检索透明化 + 文档管理） ----------
@app.get("/api/kb/query")
def kb_query(q: str, top_k: int = 5) -> dict:
    """知识库检索透明化：三路召回（向量/BM25/图谱）→ RRF 融合 → 规则精排，
    命中块连同通道标签与 RRF 分一并返回——前端只展示，不做任何计算。"""
    _init()
    q = q.strip()
    if not q:
        raise HTTPException(422, "q 不能为空")
    top_k = min(max(top_k, 1), 10)
    pack = _State.retriever.search(q, top_k=top_k)
    return {"query": pack.query, "hits": [h.model_dump() for h in pack.hits]}


@app.get("/api/kb/documents")
def kb_documents() -> dict:
    """文档清单：源目录文件 × 索引块数 × 版本，并列示索引覆盖状态。"""
    _init()
    from collections import Counter
    counts = Counter(c["doc_name"] for c in _State.retriever.chunks)
    versions = {c["doc_name"]: c["doc_version"] for c in _State.retriever.chunks}
    docs = []
    for p in sorted(C.KB_DIR.iterdir()):
        if p.suffix.lower() in _KB_SUFFIXES:
            docs.append({"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1),
                         "indexed_chunks": counts.get(p.name, 0),
                         "doc_version": versions.get(p.name),
                         "indexed": p.name in counts})
    return {"documents": docs, "total_chunks": sum(counts.values()),
            "job": dict(_KB_JOB)}


@app.post("/api/kb/documents")
async def kb_upload(req: KbUploadRequest, background: BackgroundTasks) -> dict:
    """上传文档 → 落盘 → 后台重建索引。同步返回受理，状态查 /api/kb/documents。"""
    import base64
    _init()
    name = Path(req.filename).name          # 防路径穿越：只取文件名
    if not name.lower().endswith(_KB_SUFFIXES):
        raise HTTPException(422, f"仅支持 {_KB_SUFFIXES} 格式")
    try:
        content = base64.b64decode(req.content_b64, validate=True)
    except ValueError:
        raise HTTPException(422, "content_b64 不是合法 base64")
    if _KB_JOB["state"] == "running":
        raise HTTPException(409, "索引重建进行中，请稍后重试")
    (C.KB_DIR / name).write_bytes(content)
    background.add_task(_reindex_job)
    return {"accepted": True, "filename": name, "size_kb": round(len(content) / 1024, 1),
            "note": "索引后台重建中，GET /api/kb/documents 查 job.state"}


@app.delete("/api/kb/documents/{doc_name}")
def kb_delete(doc_name: str, background: BackgroundTasks) -> dict:
    """删除文档 → 后台重建索引。删除即时生效，重建旁路进行。"""
    _init()
    target = C.KB_DIR / Path(doc_name).name
    if not target.exists():
        raise HTTPException(404, f"文档不存在: {doc_name}")
    if _KB_JOB["state"] == "running":
        raise HTTPException(409, "索引重建进行中，请稍后重试")
    target.unlink()
    background.add_task(_reindex_job)
    return {"deleted": doc_name,
            "note": "索引后台重建中，GET /api/kb/documents 查 job.state"}
