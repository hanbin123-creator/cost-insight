"""成本预测（加分项）——兼容转发模块。

实现主体在 forecast.py（Forecaster：Holt 双指数平滑 + 同比参照带）。
本模块仅保留手册登记名 predict.py → forecast.py 的转发，消除 C1 双文件双轨
（实现态审计 2026-09-19）。新代码请直接 import app.forecast。
"""
from __future__ import annotations

from .forecast import Forecaster

__all__ = ["Forecaster"]
