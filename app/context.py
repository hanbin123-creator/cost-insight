"""AnalysisContext：场景间传递的轻量上下文（竞赛版最小集）。

手册定位"全流程唯一数据载体"；竞赛版裁决（实现态审计 C2）：不强行回灌既有板块
（report_data._Bundle 已是报告链路的局部载体、MetricsPack 是计算链载体），
本类只服务 Pipeline 编排与 agent 意图分发的入参/出参传递。
企业演进版全量编排器落地时，本类是收口点。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AnalysisContext:
    """一次分析请求的输入与结果载体。"""
    product: str
    month: str
    params: dict = field(default_factory=dict)   # 场景附加参数（如 rectify 的 speed 后缀）
    result: dict = field(default_factory=dict)   # 场景产出
