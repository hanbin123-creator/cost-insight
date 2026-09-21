"""板块② 数据计算：全部数字的唯一产地。

纪律：全程 float64 计算，只在输出层 ROUND_HALF_UP；大模型与前端永不自行算数。
列名一律走 config 常量（D2 红线），本文件不出现表头字面量。
"""
from __future__ import annotations

import pandas as pd

from . import config as C
from .ingest import Store
from .schemas import Alert, Decomposition, DiffRow, DiffTree, ElementMetric, MetricsPack


def _r(x: float | None, ndigits: int) -> float | None:
    return None if x is None or pd.isna(x) else round(float(x), ndigits)


def _pct(new: float | None, old: float | None) -> float | None:
    """变动率 %；旧值为 0/None 时返回 None（除零保护）。"""
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old * 100


def _prev_month(month: str) -> str | None:
    y, m = int(month[:4]), int(month[5:])
    return f"{y}-{m-1:02d}" if m > 1 else None


def _yoy_month(month: str) -> str:
    return f"{int(month[:4]) - 1}-{month[5:]}"


# SQL 片段（含括号的中文列名在 SQL 中须双引号包裹）
_SQL_MATS = (f'SELECT {C.COL_MAT_NAME}, "{C.COL_MAT_UNIT_COST}" FROM materials '
             f'WHERE {C.COL_PRODUCT}=? AND {C.COL_MONTH}=?')
_SQL_MKT = f"SELECT {C.COL_HERB}, {C.COL_MONTH}, {C.COL_MKT_PRICE} FROM market_long"


class CostCalculator:
    def __init__(self, store: Store):
        self.store = store

    # ---------- 主入口：指标包 ----------
    def metrics(self, product: str, month: str) -> MetricsPack:
        cur = self.store.summary(product, month)
        prev_m = _prev_month(month)
        prev = self.store.summary(product, prev_m) if prev_m else None
        yoy_row = self._safe_summary(product, _yoy_month(month))
        budget = self._budget(product, month)

        total_change = None
        if prev is not None:
            total_change = cur[C.COL_UNIT_COST] - prev[C.COL_UNIT_COST]

        elements: dict[str, ElementMetric] = {}
        for col in C.COST_ELEMENTS:
            name = C.ELEMENT_SHORT[col]
            c, p = float(cur[col]), (float(prev[col]) if prev is not None else None)
            y = float(yoy_row[col]) if yoy_row is not None else None
            b = self._budget_value(budget, name)
            contrib = None
            if total_change is not None and abs(total_change) > 1e-9 and p is not None:
                contrib = (c - p) / total_change * 100
            elements[name] = ElementMetric(
                current=_r(c, C.MONEY_NDIGITS), prev_month=_r(p, C.MONEY_NDIGITS),
                prev_year=_r(y, C.MONEY_NDIGITS), budget=_r(b, C.MONEY_NDIGITS),
                mom_pct=_r(_pct(c, p), C.PCT_NDIGITS),
                yoy_pct=_r(_pct(c, y), C.PCT_NDIGITS),
                budget_dev_pct=_r(_pct(c, b), C.PCT_NDIGITS),
                contribution_pct=_r(contrib, C.PCT_NDIGITS),
            )

        alerts = self._collect_alerts(product, month, elements)

        cur_uc = float(cur[C.COL_UNIT_COST])
        y_uc = float(yoy_row[C.COL_UNIT_COST]) if yoy_row is not None else None
        b_uc = self._budget_value(budget, "单位成本")
        return MetricsPack(
            product=product, month=month,
            output_qty=int(cur[C.COL_OUTPUT]),
            unit_cost=_r(cur_uc, C.MONEY_NDIGITS),
            total_cost=_r(float(cur[C.COL_TOTAL_COST]), C.MONEY_NDIGITS),
            elements=elements,
            unit_cost_mom_pct=_r(_pct(cur_uc, float(prev[C.COL_UNIT_COST]) if prev is not None else None),
                                 C.PCT_NDIGITS),
            unit_cost_yoy_pct=_r(_pct(cur_uc, y_uc), C.PCT_NDIGITS),
            unit_cost_budget_dev_pct=_r(_pct(cur_uc, b_uc), C.PCT_NDIGITS),
            decomposition=self.decompose(product, month),
            alerts=alerts,
        )

    # ---------- 三级告警（D6 优化：赛题字面口径 + 数据实际量级 + 官方示例口径） ----------
    def _collect_alerts(self, product: str, month: str,
                        elements: dict[str, ElementMetric]) -> list[Alert]:
        """通道①要素环比±10%（赛题 5.2.3 字面）；通道②原材料环比±8%（数据实际波动量级）；
        通道③行情累计涨幅±10%（年初→当月，对齐官方归因示例'金银花+12%超阈值'口径）。"""
        alerts: list[Alert] = []
        # 通道①：要素环比（保留赛题字面要求，即使当前数据不触发也必须存在）
        for n, e in elements.items():
            if e.mom_pct is not None and abs(e.mom_pct) > C.ALERT_THRESHOLD * 100:
                alerts.append(Alert(channel="要素环比", element=n, mom_pct=e.mom_pct,
                                    message=f"{n}环比变动{e.mom_pct:+.1f}%，超出±10%阈值"))
        prev_m = _prev_month(month)
        if prev_m is None:
            return alerts
        # 通道②：原材料级环比 ±8%
        mats_c = self.store.query(_SQL_MATS, (product, month))
        mats_p = self.store.query(_SQL_MATS, (product, prev_m))
        pmap = dict(zip(mats_p[C.COL_MAT_NAME], mats_p[C.COL_MAT_UNIT_COST]))
        for _, r in mats_c.iterrows():
            pv = pmap.get(r[C.COL_MAT_NAME])
            rate = _pct(float(r[C.COL_MAT_UNIT_COST]), float(pv) if pv is not None else None)
            if rate is not None and abs(rate) > C.ALERT_MATERIAL_MOM:
                alerts.append(Alert(channel="原材料环比", element=r[C.COL_MAT_NAME],
                                    mom_pct=_r(rate, C.PCT_NDIGITS),
                                    message=f"{r[C.COL_MAT_NAME]}单位消耗成本环比{rate:+.1f}%，"
                                            f"超出±{C.ALERT_MATERIAL_MOM:.0f}%原材料级阈值"))
        # 通道③：行情累计涨幅 ±10%（仅本产品用到的药材）
        mkt = self.store.query(_SQL_MKT)
        price = {(r[C.COL_HERB], r[C.COL_MONTH]): float(r[C.COL_MKT_PRICE]) for _, r in mkt.iterrows()}
        for name in mats_c[C.COL_MAT_NAME]:
            base, cur_p = price.get((name, C.YEAR_BASE_MONTH)), price.get((name, month))
            rate = _pct(cur_p, base)
            if rate is not None and abs(rate) > C.ALERT_CUMULATIVE and month != C.YEAR_BASE_MONTH:
                alerts.append(Alert(channel="累计涨幅", element=name,
                                    mom_pct=_r(rate, C.PCT_NDIGITS),
                                    message=f"{name}行情价年初至当月累计{rate:+.1f}%，"
                                            f"超出±{C.ALERT_CUMULATIVE:.0f}%累计阈值"))
        return alerts

    # ---------- 量差价差分解 ----------
    def decompose(self, product: str, month: str) -> list[Decomposition]:
        """单耗 = 单位消耗成本 ÷ 当月行情价；价差=Δ价×本月单耗；量差=Δ单耗×上月价。
        行情未覆盖的辅料（包材/纯化水，D5）走稳价假设通道：价格稳定辅料的成本变动
        判为纯量差（用量/损耗），method 与 note 显式标注假设口径，绝不假装有行情价。"""
        prev_m = _prev_month(month)
        if prev_m is None:
            return []
        cur = self.store.query(_SQL_MATS, (product, month))
        prev = self.store.query(_SQL_MATS, (product, prev_m))
        cur.columns = ["material", "cost"]
        prev.columns = ["material", "cost"]
        mkt = self.store.query(_SQL_MKT)
        price = {(r[C.COL_HERB], r[C.COL_MONTH]): float(r[C.COL_MKT_PRICE]) for _, r in mkt.iterrows()}

        out = []
        prev_map = dict(zip(prev["material"], prev["cost"]))
        for _, row in cur.iterrows():
            name, c_cost = row["material"], float(row["cost"])
            p_cost = prev_map.get(name)
            pc, pp = price.get((name, month)), price.get((name, prev_m))
            if pc and pp and p_cost is not None:
                q_c, q_p = c_cost / pc, p_cost / pp
                out.append(Decomposition(
                    material=name, method="market_price", price_prev=pp, price_curr=pc,
                    qty_prev=_r(q_p, 4), qty_curr=_r(q_c, 4),
                    price_effect=_r((pc - pp) * q_c, 4),
                    qty_effect=_r((q_c - q_p) * pp, 4), covered=True,
                    note="按市场行情价分解"))
            elif p_cost is not None:
                # D5 优化：稳价辅料假设——价格不变，变动全部归因用量
                out.append(Decomposition(
                    material=name, method="stable_price_assumption",
                    price_prev=None, price_curr=None, qty_prev=None, qty_curr=None,
                    price_effect=0.0, qty_effect=_r(c_cost - p_cost, 4), covered=False,
                    note="行情未覆盖的稳价辅料，假设价格不变，变动全部按用量差异处理（假设口径）"))
            else:
                out.append(Decomposition(material=name, method="uncovered",
                                         price_prev=None, price_curr=None, qty_prev=None,
                                         qty_curr=None, price_effect=None, qty_effect=None,
                                         covered=False, note="行情未覆盖且无上月数据，不分解"))
        return out

    # ---------- 对标三步法（第一、二步） ----------
    @staticmethod
    def _diff_description(element: str, m: float, b: float,
                          rate: float | None, rev: float | None) -> str:
        """代码预生成无歧义双向口径描述，下游只读不算（基期为零则退回绝对值表述）。"""
        if rate is None or rev is None:
            return f"{element}：一厂 {m:.2f} 元/盒 vs 二厂 {b:.2f} 元/盒（基期为零，仅列绝对值）"
        if abs(m - b) < 1e-9:
            return f"{element}：一厂与二厂持平（均为 {m:.2f} 元/盒）"
        if m < b:
            return (f"{element}：一厂 {m:.2f} vs 二厂 {b:.2f} 元/盒，"
                    f"一厂比二厂低 {abs(rate):.1f}%（即二厂比一厂高 {rev:.1f}%）")
        return (f"{element}：一厂 {m:.2f} vs 二厂 {b:.2f} 元/盒，"
                f"一厂比二厂高 {rate:.1f}%（即二厂比一厂低 {abs(rev):.1f}%）")

    def benchmark(self, product: str, month: str) -> DiffTree:
        main = self.store.summary(product, month, C.FACTORY_MAIN)
        bench = self.store.summary(product, month, C.FACTORY_BENCH)
        rows = []
        for col in C.COST_ELEMENTS + [C.COL_UNIT_COST]:
            m, b = float(main[col]), float(bench[col])
            d = m - b
            rate = d / b * 100 if b else None          # 对二厂口径
            rev = -d / m * 100 if m else None          # 反向口径：(二厂−一厂)÷一厂
            name = C.ELEMENT_SHORT.get(col, "单位成本")
            rows.append(DiffRow(
                element=name,
                main=_r(m, C.MONEY_NDIGITS), bench=_r(b, C.MONEY_NDIGITS),
                diff=_r(d, C.MONEY_NDIGITS),
                diff_rate_pct=_r(rate, C.PCT_NDIGITS),
                reverse_rate_pct=_r(rev, C.PCT_NDIGITS),
                direction="优势" if d < 0 else ("劣势" if d > 0 else "持平"),
                description=self._diff_description(name, m, b,
                                                   _r(rate, C.PCT_NDIGITS),
                                                   _r(rev, C.PCT_NDIGITS))))
        # 第二步：材料差异下钻（一厂明细 vs 二厂按材料成本差占比估算，标注估算口径）
        mats = self.store.query(
            f'SELECT {C.COL_MAT_NAME}, "{C.COL_MAT_UNIT_COST}", "{C.COL_MAT_SHARE}" '
            f'FROM materials WHERE {C.COL_PRODUCT}=? AND {C.COL_MONTH}=?',
            (product, month))
        mats.columns = ["material", "unit_cost", "share_pct"]
        mat_diff = rows[0].diff or 0.0
        detail = [{"material": r["material"],
                   "main_unit_cost": round(float(r["unit_cost"]), 2),
                   "share_pct": float(r["share_pct"]),
                   "est_diff": round(mat_diff * float(r["share_pct"]) / 100, 3)}
                  for _, r in mats.iterrows()]
        return DiffTree(product=product, month=month, rows=rows, material_detail=detail)

    # ---------- 季度聚合（缺口 G2 补救：加权口径） ----------
    QUARTER_MONTHS = {"Q1": ["2026-01", "2026-02", "2026-03"],
                      "Q2": ["2026-04", "2026-05", "2026-06"]}

    def quarter_metrics(self, product: str, quarter_months: list[str]) -> dict:
        """季度单位成本 = Σ总成本 ÷ Σ产量（加权），不是月单位成本的算术平均。"""
        rows = [self.store.summary(product, m) for m in quarter_months]
        qty = sum(float(r[C.COL_OUTPUT]) for r in rows)
        total = sum(float(r[C.COL_TOTAL_COST]) for r in rows)
        return {"product": product, "months": quarter_months,
                "output_qty": int(qty), "total_cost": _r(total, C.MONEY_NDIGITS),
                "unit_cost_weighted": _r(total / qty, C.MONEY_NDIGITS) if qty else None}

    def quarter_pack(self, product: str, quarter: str) -> MetricsPack:
        """季度主题完整指标包（赛题 5.1.3 三主题之"季度"）。

        口径纪律：一切比率按季度加权值重算——要素单位成本按产量加权
        （Σ要素×产量÷Σ产量），环比=对上季度同口径，同比=对 2025 同季度（缺数据则 None）。
        预算口径季度表未给出，budget 系列置 None（显示层"—"），不编造。
        告警=季度内各月告警并集，message 前缀月份保持可溯源。"""
        months = self.QUARTER_MONTHS[quarter]
        rows = [self.store.summary(product, m) for m in months]
        qty = sum(float(r[C.COL_OUTPUT]) for r in rows)
        if qty <= 0:
            raise ValueError(f"{product} {quarter} 季度产量为 0，无法加权")
        total = sum(float(r[C.COL_TOTAL_COST]) for r in rows)

        # 上季度 / 去年同季度（同加权口径；数据缺则 None）
        q_prev = {"Q1": None, "Q2": "Q1"}[quarter]
        prev_rows = [self.store.summary(product, m) for m in self.QUARTER_MONTHS[q_prev]] \
            if q_prev else None
        yoy_months = [f"2025-{m[5:]}" for m in months]
        yoy_rows = [s for s in (self._safe_summary(product, m) for m in yoy_months)
                    if s is not None]
        yoy_rows = yoy_rows if len(yoy_rows) == 3 else None  # 缺一不做季度同比，口径残缺不硬算

        def _w(rows_, col) -> float | None:
            if not rows_:
                return None
            q = sum(float(r[C.COL_OUTPUT]) for r in rows_)
            return sum(float(r[col]) * float(r[C.COL_OUTPUT]) for r in rows_) / q if q else None

        cur_uc = _w(rows, C.COL_UNIT_COST)
        prev_uc = _w(prev_rows, C.COL_UNIT_COST) if prev_rows else None
        yoy_uc = _w(yoy_rows, C.COL_UNIT_COST) if yoy_rows else None

        elements: dict[str, ElementMetric] = {}
        total_change = (cur_uc - prev_uc) if (prev_uc is not None) else None
        for col in C.COST_ELEMENTS:
            name = C.ELEMENT_SHORT[col]
            c = _w(rows, col)
            p = _w(prev_rows, col) if prev_rows else None
            y = _w(yoy_rows, col) if yoy_rows else None
            contrib = None
            if total_change is not None and abs(total_change) > 1e-9 and p is not None:
                contrib = (c - p) / total_change * 100
            elements[name] = ElementMetric(
                current=_r(c, C.MONEY_NDIGITS), prev_month=_r(p, C.MONEY_NDIGITS),
                prev_year=_r(y, C.MONEY_NDIGITS), budget=None,
                mom_pct=_r(_pct(c, p), C.PCT_NDIGITS),
                yoy_pct=_r(_pct(c, y), C.PCT_NDIGITS),
                budget_dev_pct=None,
                contribution_pct=_r(contrib, C.PCT_NDIGITS))

        alerts: list[Alert] = []
        for m in months:
            for a in self._collect_alerts(product, m,
                                          self.metrics(product, m).elements):
                alerts.append(Alert(channel=a.channel, element=a.element,
                                    mom_pct=a.mom_pct, message=f"[{m}] {a.message}"))

        return MetricsPack(
            product=product, month=f"2026-{quarter}",
            output_qty=int(qty), unit_cost=_r(cur_uc, C.MONEY_NDIGITS),
            total_cost=_r(total, C.MONEY_NDIGITS), elements=elements,
            unit_cost_mom_pct=_r(_pct(cur_uc, prev_uc), C.PCT_NDIGITS),
            unit_cost_yoy_pct=_r(_pct(cur_uc, yoy_uc), C.PCT_NDIGITS),
            unit_cost_budget_dev_pct=None,
            decomposition=[],   # 季度量差价差=月度分解的滚动叠加，口径另立；本期不做不硬凑
            alerts=alerts)

    # ---------- 内部 ----------
    def _safe_summary(self, product: str, month: str) -> pd.Series | None:
        try:
            return self.store.summary(product, month)
        except KeyError:
            return None

    def _budget(self, product: str, month: str) -> pd.Series | None:
        df = self.store.query(
            f"SELECT * FROM budget WHERE {C.COL_PRODUCT}=? AND {C.COL_MONTH}=?", (product, month))
        return None if df.empty else df.iloc[0]

    @staticmethod
    def _budget_value(budget: pd.Series | None, element: str) -> float | None:
        if budget is None:
            return None
        return float(budget[C.BUDGET_COLS[element]])
