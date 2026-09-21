"""全局数据契约（pydantic v2）。板块间传递的所有结构化数据在此定义。"""
from __future__ import annotations

from pydantic import BaseModel


class ElementMetric(BaseModel):
    """单个成本要素的四口径指标。"""
    current: float            # 本月实际（元/盒）
    prev_month: float | None  # 上月
    prev_year: float | None   # 去年同月
    budget: float | None      # 预算
    mom_pct: float | None     # 环比 %
    yoy_pct: float | None     # 同比 %
    budget_dev_pct: float | None  # 预算偏差 %
    contribution_pct: float | None  # 对总成本变动的贡献度 %


class Decomposition(BaseModel):
    """单种原材料的量差价差分解。"""
    material: str
    method: str                 # market_price=行情价分解 / stable_price_assumption=稳价假设纯量差 / uncovered=数据缺失
    price_prev: float | None   # 上月行情价（元/kg）
    price_curr: float | None   # 本月行情价
    qty_prev: float | None     # 上月单耗（kg/盒）
    qty_curr: float | None     # 本月单耗
    price_effect: float | None  # 价差影响（元/盒）
    qty_effect: float | None    # 量差影响（元/盒）
    covered: bool               # 行情表是否覆盖该药材
    note: str | None = None     # 分解口径说明（归因文本直接引用）


class Alert(BaseModel):
    channel: str      # 要素环比 / 原材料环比 / 累计涨幅
    element: str
    mom_pct: float
    message: str


class MetricsPack(BaseModel):
    """板块②产物：一次分析条件的全部指标包。"""
    product: str
    month: str
    output_qty: int
    unit_cost: float
    total_cost: float
    elements: dict[str, ElementMetric]   # key: 直接材料/直接人工/制造费用
    unit_cost_mom_pct: float | None
    unit_cost_yoy_pct: float | None
    unit_cost_budget_dev_pct: float | None
    decomposition: list[Decomposition]
    alerts: list[Alert]


class DiffRow(BaseModel):
    """三步法第一步：差异总览行。双向口径均由代码算好，下游只读不算。"""
    element: str
    main: float
    bench: float
    diff: float           # 一厂 − 二厂
    diff_rate_pct: float  # 对二厂口径：(一厂−二厂)÷二厂
    reverse_rate_pct: float | None  # 反向口径：(二厂−一厂)÷一厂
    direction: str        # 优势/劣势/持平
    description: str      # 无歧义中文描述（归因文本直接引用）


class DiffTree(BaseModel):
    """三步法第一、二步产物。"""
    product: str
    month: str
    rows: list[DiffRow]
    material_detail: list[dict]  # 原材料级下钻


class KnowledgeHit(BaseModel):
    """一次检索命中的知识块。source 字段组是给报告引用的出处。"""
    chunk_id: str
    doc_name: str        # 文档名（引用出处）
    page: int            # 起始页码（引用出处）
    section: str         # 章节标题（引用出处）
    doc_type: str        # formula / process / equipment / gmp / other
    text: str
    rrf_score: float     # RRF 融合得分
    channels: list[str]  # 命中的通道：vector / bm25


class KnowledgePack(BaseModel):
    """板块③产物：一次检索的知识包，只含带出处的命中块。"""
    query: str
    hits: list[KnowledgeHit]


class Cause(BaseModel):
    """单条归因结论。figures/citations 是声明制：模型声明用了哪些数字与出处，
    校验器拿声明与产物包对账——声明之外出现的数字/出处即幻觉。"""
    title: str                       # 结论标题，如"金银花行情上涨推高材料成本"
    detail: str                      # 论述正文（引用格式：《文档名》p页 章节）
    figures: list[float]             # 正文中使用的全部数字（声明制）
    citations: list[str]             # 引用的 chunk_id 列表


class AttributionReport(BaseModel):
    """板块④产物：归因报告。verification 是代码侧校验结果，模型不可见。"""
    product: str
    month: str
    summary: str                     # 总起段（单位成本/环比/同比/预算偏差已由代码给数）
    causes: list[Cause]
    suggestions: list[str]
    verification: dict = {}          # {"passed": bool, "errors": [...]}


# ---------- 板块⑥ 行动闭环：官方《模拟RPA接口文档 V1.0》十二字段契约 ----------
# 纪律（赛题约束原文）：RPA 任务 JSON 必须过 schema 校验才发送。

import re as _re

from pydantic import field_validator as _field_validator


class Assignee(BaseModel):
    name: str
    department: str
    role: str | None = None


class TaskSource(BaseModel):
    analysis_type: str               # 月度成本分析/季度成本分析/专题分析
    analysis_month: str              # YYYY-MM
    product: str
    finding: str                     # 分析发现的问题描述（代码告警原文）


class RectifyTask(BaseModel):
    """整改任务（官方十二字段）。task_id 官方建议格式 TASK-YYYY-NNNN，
    演示后缀 -FAST/-OVERDUE/-DONE 触发官方 mock 的自动状态机（接口文档第七节）。"""
    task_id: str
    task_title: str
    assignee: Assignee
    source: TaskSource
    priority: str                    # high / medium / low
    deadline: str                    # YYYY-MM-DD
    suggestion: str | None = None
    notify_method: str = "wechat"
    created_at: str                  # ISO 8601

    @_field_validator("task_id")
    @classmethod
    def _task_id_format(cls, v: str) -> str:
        if not _re.fullmatch(r"TASK-\d{4}-\d{4}(-(FAST|OVERDUE|DONE))?", v):
            raise ValueError(f"task_id 须为 TASK-YYYY-NNNN（可带演示后缀）: {v}")
        return v

    @_field_validator("priority")
    @classmethod
    def _priority_enum(cls, v: str) -> str:
        if v not in ("high", "medium", "low"):
            raise ValueError(f"priority 须为 high/medium/low: {v}")
        return v

    @_field_validator("deadline")
    @classmethod
    def _deadline_format(cls, v: str) -> str:
        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError(f"deadline 须为 YYYY-MM-DD: {v}")
        return v

    @_field_validator("source")
    @classmethod
    def _source_month_format(cls, v: TaskSource) -> TaskSource:
        if not _re.fullmatch(r"\d{4}-\d{2}", v.analysis_month):
            raise ValueError(f"analysis_month 须为 YYYY-MM: {v.analysis_month}")
        return v
