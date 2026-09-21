"""模块二图表数据预计算层：下游永不计算——前端只渲染本模块产出的坐标。

产出四类图表数据（全部 JSON 可序列化，直接供 API 返回）：
- series_data：近 6 月单位成本+三要素折线序列
- waterfall_data：瀑布图（含 ECharts 堆叠所需的透明基底坐标，方向与数值分离）
- structure_data：嵌套环形图（内环三要素，外环原材料明细展开直接材料）
- heatmap_data：产品×月份×要素环比矩阵（首月 None 显式传播，前端渲染"—"）
"""
from __future__ import annotations

from . import config as C
from .compute import CostCalculator, _pct, _prev_month as _prev, _r

MONTHS_2026 = [f"2026-{m:02d}" for m in range(1, 7)]


class ChartBuilder:
    def __init__(self, calc: CostCalculator):
        self.calc = calc
        self.store = calc.store

    # ---------- 趋势图 ----------
    def series_data(self, product: str) -> dict:
        """近 6 月四线序列：单位成本 + 三要素（元/盒）。"""
        rows = [self.store.summary(product, m) for m in MONTHS_2026]
        out = {"product": product, "months": MONTHS_2026,
               "unit_cost": [], "series": {n: [] for n in C.ELEMENT_SHORT.values()}}
        for r in rows:
            out["unit_cost"].append(_r(float(r[C.COL_UNIT_COST]), C.MONEY_NDIGITS))
            for col in C.COST_ELEMENTS:
                out["series"][C.ELEMENT_SHORT[col]].append(_r(float(r[col]), C.MONEY_NDIGITS))
        return out

    # ---------- 瀑布图 ----------
    def waterfall_data(self, product: str, month: str) -> dict:
        """瀑布段：上月 → 各要素变动 → 本月。

        每段给出 start/end 运行水位与 value（带符号），ECharts 堆叠柱所需：
        transparent_base = min(start, end)，visible = abs(value)，方向决定颜色——
        全部由后端算好，前端零计算。负贡献段（D7）direction 如实标记。"""
        prev_m = _prev(month)
        if prev_m is None:
            raise ValueError("首月无瀑布图（无上月基期）")
        prev = self.store.summary(product, prev_m)
        cur = self.store.summary(product, month)

        base_total = float(prev[C.COL_UNIT_COST])
        running = base_total
        segments = [{"name": f"上月({prev_m})", "type": "total",
                     "start": 0.0, "end": round(base_total, C.MONEY_NDIGITS),
                     "value": round(base_total, C.MONEY_NDIGITS), "direction": "base",
                     "transparent_base": 0.0, "visible": round(base_total, C.MONEY_NDIGITS)}]
        for col in C.COST_ELEMENTS:
            name = C.ELEMENT_SHORT[col]
            delta = round(float(cur[col]) - float(prev[col]), C.MONEY_NDIGITS)
            start, end = running, running + delta
            segments.append({"name": name, "type": "delta",
                             "start": round(start, C.MONEY_NDIGITS),
                             "end": round(end, C.MONEY_NDIGITS),
                             "value": delta,
                             "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
                             "transparent_base": round(min(start, end), C.MONEY_NDIGITS),
                             "visible": round(abs(delta), C.MONEY_NDIGITS)})
            running = end
        cur_total = float(cur[C.COL_UNIT_COST])
        segments.append({"name": f"本月({month})", "type": "total",
                         "start": 0.0, "end": round(cur_total, C.MONEY_NDIGITS),
                         "value": round(cur_total, C.MONEY_NDIGITS), "direction": "base",
                         "transparent_base": 0.0, "visible": round(cur_total, C.MONEY_NDIGITS)})
        return {"product": product, "month": month,
                "total_change": round(cur_total - base_total, C.MONEY_NDIGITS),
                "waterfall_close_gap": round(running - cur_total, 4),  # 舍入闭合差（应≈0）
                "segments": segments}

    # ---------- 结构图 ----------
    def structure_data(self, product: str, month: str) -> dict:
        """嵌套环形：内环三要素（元/盒），外环把直接材料展开为原材料明细，
        直接人工/制造费用外环为单段。外环合计 = 内环合计 = 单位成本（对账进测试）。"""
        cur = self.store.summary(product, month)
        inner = [{"name": C.ELEMENT_SHORT[col],
                  "value": _r(float(cur[col]), C.MONEY_NDIGITS)} for col in C.COST_ELEMENTS]
        mats = self.store.query(
            f'SELECT {C.COL_MAT_NAME}, "{C.COL_MAT_UNIT_COST}" FROM materials '
            f'WHERE {C.COL_PRODUCT}=? AND {C.COL_MONTH}=?', (product, month))
        outer = [{"name": r[C.COL_MAT_NAME],
                  "value": _r(float(r[C.COL_MAT_UNIT_COST]), C.MONEY_NDIGITS),
                  "parent": "直接材料"} for _, r in mats.iterrows()]
        for name in ("直接人工", "制造费用"):
            v = next(i["value"] for i in inner if i["name"] == name)
            outer.append({"name": name, "value": v, "parent": name})
        return {"product": product, "month": month, "inner": inner, "outer": outer,
                "unit_cost": _r(float(cur[C.COL_UNIT_COST]), C.MONEY_NDIGITS)}

    # ---------- 热力图 ----------
    def heatmap_data(self) -> dict:
        """3 产品 × 6 月 × 3 要素环比矩阵。首月 None（前端渲染"—"，不补 0）。"""
        rows = [f"{p}·{C.ELEMENT_SHORT[col]}" for p in C.PRODUCTS for col in C.COST_ELEMENTS]
        data = []  # [month_idx, row_idx, mom_pct|None]
        for r_idx, (product, col) in enumerate((p, c) for p in C.PRODUCTS for c in C.COST_ELEMENTS):
            for m_idx, month in enumerate(MONTHS_2026):
                prev_m = _prev(month)
                if prev_m is None:
                    data.append([m_idx, r_idx, None])
                    continue
                cur = float(self.store.summary(product, month)[col])
                prev = float(self.store.summary(product, prev_m)[col])
                data.append([m_idx, r_idx, _r(_pct(cur, prev), C.PCT_NDIGITS)])
        return {"months": MONTHS_2026, "rows": rows, "data": data}
