"""板块3 报告上下文组装器（生产者驱动 + L1 标准字段版）：101 占位符 ← 全部由代码算好。

结构（模板自适应与可复用方案 3.0 + 3.2）：
- 代码内只认**内部标准字段 id**（report.title / material.cost.current / rows.*）；
  模板键名（本月产量 等）只存在于 config/placeholder_map.yaml ——换模板/换行业 = 改配置
- _Bundle：共享计算前置（metrics/summary/预算/人工/制造费用/对标 一次算好，各组只读）
- 组生产者：每组静态声明 provides（标准字段）+ 可选 extras（注册表外保险字段），
  fn(bundle) -> dict 恰好产出声明的字段——多一个少一个都在运行时炸
- 导入时校验：本模块 _validate_groups()（组声明自洽 + 无争抢）；
  app/mapping.py MAPPING（YAML 键 == 注册表、YAML 值 == 本模块声明）——双层互为保险
- _assert_coverage 保留为运行时兜底：防模板漂移与绕路改码

口径：环比/同比/预算偏差沿用 compute._pct；预算缺失显示"—"由 render 层处理
（本层给 None，render 层格式化——显示格式化豁免计算禁令）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from . import config as C
from .compute import CostCalculator, _pct, _prev_month, _r, _yoy_month
from .report_registry import DYNAMIC_TABLE_PLACEHOLDERS, SCALAR_PLACEHOLDERS

# 告警通道 → 整改任务责任部门/优先级（赛题模块四：规则映射责任部门）
_DEPT_RULES = {
    "原材料环比": ("采购部", "高"),
    "累计涨幅": ("采购部", "高"),
    "要素环比": ("生产部", "中"),
    "预算偏差": ("财务部", "中"),
}

# 制造费用五类（模板 3.3 表固定行序）：键 = 模板行名；值 = (标准字段前缀, DB 类别关键词)
_OVERHEAD_CATS = ["折旧费", "动力费", "间接人工", "检验费", "其他"]
_OVERHEAD_FIELD = {"折旧费": "overhead.depreciation", "动力费": "overhead.power",
                   "间接人工": "overhead.indirect", "检验费": "overhead.inspection",
                   "其他": "overhead.other"}
_OVERHEAD_MATCH = {"折旧费": "折旧", "动力费": "动力", "间接人工": "间接",
                   "检验费": "检验", "其他": "其他"}

# extras 保险字段 → 直出模板键（现模板无此占位符，docxtpl 静默忽略；
# 模板变体若引入 {{波动告警描述}}，届时在 YAML 加一行映射即生效）
_EXTRAS_LEGACY_KEY = {"alerts.description": "波动告警描述"}


def _f(x: float | None) -> float | None:
    """金额两位舍入（与全系统 MONEY_NDIGITS 口径一致）。"""
    return _r(x, C.MONEY_NDIGITS) if x is not None else None


# ---------- Bundle：共享计算前置 ----------


@dataclass
class _Bundle:
    """一次 build 的共享计算结果；各组生产者只读不重算。"""
    calc: CostCalculator
    store: Any
    product: str
    month: str          # 月度表查询锚点（季度主题=季末月）
    label: str          # 展示口径标签：2026-05 / 2026-Q1
    theme: str          # monthly / quarterly / topical
    prev_m: str | None
    yoy_m: str
    m: Any          # MetricsPack（季度主题=quarter_pack 加权包）
    cur: Any        # 本期 summary 行（季度=产量加权合成行）
    prev: Any       # 上期 summary 行（首月/首季为 None）
    yoy: Any        # 去年同期 summary 行（季度口径缺 2025 全年则为 None）
    budget: Any     # 预算行（缺失为 None）
    lab: Any
    lab_prev: Any
    ov: dict
    ov_prev: dict
    diff: Any       # 对标树（季度主题=季末月口径）


def _labor(store, product: str, month: str | None):
    if month is None:
        return None
    df = store.query(
        "SELECT * FROM labor WHERE 产品名称=? AND 月份=?", (product, month))
    return None if df.empty else df.iloc[0]


def _overhead(store, product: str, month: str | None) -> dict:
    if month is None:
        return {}
    df = store.query(
        'SELECT "费用类别", "单位费用(元/盒)" FROM overhead WHERE 产品名称=? AND 月份=?',
        (product, month))
    out = {}
    for _, r in df.iterrows():
        cat = str(r["费用类别"])
        for want, kw in _OVERHEAD_MATCH.items():
            if kw in cat:  # 关键词匹配：DB 实际类别如 "人工(间接)"/"动力费(水电气)"
                out[want] = float(r["单位费用(元/盒)"])
    return out


def _make_bundle(calc: CostCalculator, product: str, month: str) -> _Bundle:
    store = calc.store
    prev_m = _prev_month(month)
    return _Bundle(
        calc=calc, store=store, product=product, month=month,
        label=month, theme="monthly",
        prev_m=prev_m, yoy_m=_yoy_month(month),
        m=calc.metrics(product, month),
        cur=store.summary(product, month),
        prev=store.summary(product, prev_m) if prev_m else None,
        yoy=store.summary(product, _yoy_month(month)),
        budget=calc._budget(product, month),
        lab=_labor(store, product, month),
        lab_prev=_labor(store, product, prev_m) if prev_m else None,
        ov=_overhead(store, product, month),
        ov_prev=_overhead(store, product, prev_m) if prev_m else {},
        diff=calc.benchmark(product, month),
    )


def _weighted_row(store, product: str, months: list[str]) -> dict:
    """季度合成行：产量/总成本求和，单位成本与要素按产量加权（与 quarter_pack 同口径）。"""
    import pandas as pd
    rows = [store.summary(product, m) for m in months]
    qty = sum(float(r[C.COL_OUTPUT]) for r in rows)
    out: dict = {C.COL_OUTPUT: qty,
                 C.COL_TOTAL_COST: sum(float(r[C.COL_TOTAL_COST]) for r in rows),
                 "产品规格": str(rows[-1]["产品规格"])}
    for col in [C.COL_UNIT_COST] + C.COST_ELEMENTS:
        out[col] = sum(float(r[col]) * float(r[C.COL_OUTPUT]) for r in rows) / qty
    return pd.Series(out)


def _make_quarter_bundle(calc: CostCalculator, product: str, quarter: str) -> _Bundle:
    """季度主题 bundle（赛题 5.1.3）：合成行产量加权；季末月作为月度明细表锚点；
    上季度仅 Q2→Q1 可比（Q1 无上季，prev=None→显示层"—"）；预算表无季度口径置 None。"""
    store = calc.store
    months = calc.QUARTER_MONTHS[quarter]
    end_m = months[-1]
    q_prev = {"Q1": None, "Q2": "Q1"}[quarter]
    prev = _weighted_row(store, product, calc.QUARTER_MONTHS[q_prev]) if q_prev else None
    return _Bundle(
        calc=calc, store=store, product=product, month=end_m,
        label=f"2026-{quarter}", theme="quarterly",
        prev_m=_prev_month(end_m), yoy_m="",
        m=calc.quarter_pack(product, quarter),
        cur=_weighted_row(store, product, months),
        prev=prev, yoy=None,                    # 2025 季度数据未提供，同比留空不硬算
        budget=None,                            # 预算表仅月度口径，季度置 None（显示"—"）
        lab=_labor(store, product, end_m),      # 人工/制造费用明细表取季末月口径，
        lab_prev=None,                          # 季度环比在指标包层已加权表达
        ov=_overhead(store, product, end_m), ov_prev={},
        diff=calc.benchmark(product, end_m),
    )


# ---------- 标准字段声明（声明由辅助函数生成，笔误风险压到最低） ----------


def _metric_fields(base: str) -> tuple[str, ...]:
    """2.1 指标行七字段模式：current/prev/mom/yoy_value/yoy/budget/budget_dev。"""
    return tuple(f"{base}.{a}" for a in
                 ("current", "prev", "mom", "yoy_value", "yoy", "budget", "budget_dev"))


_ELEM21_FIELDS = tuple(f"{e}.cost.{a}" for e in ("material", "labor", "overhead")
                       for a in ("current", "prev", "mom", "budget", "budget_dev"))
# 2.2 结构行（labor.struct.mom 归人工组 labor.unit.mom·人工表实测口径；
# overhead.struct.mom 与 overhead.cost.mom 同值同字段，不重复声明）
_ELEM22_FIELDS = ("material.struct.amount", "material.struct.share",
                  "material.struct.mom", "material.struct.contribution",
                  "labor.struct.amount", "labor.struct.share",
                  "labor.struct.contribution",
                  "overhead.struct.amount", "overhead.struct.share",
                  "overhead.struct.contribution")
_LABOR_FIELDS = ("labor.unit.current", "labor.unit.prev", "labor.unit.mom") + tuple(
    f"labor.{k}.{a}" for k in ("hours", "wage", "efficiency")
    for a in ("current", "prev", "mom"))
_OVERHEAD_FIELDS = tuple(
    f"{_OVERHEAD_FIELD[cat]}.{a}" for cat in _OVERHEAD_CATS
    for a in ("current", "prev", "mom", "note")) + \
    ("overhead.total.current", "overhead.total.prev", "overhead.total.mom")


# ---------- 组生产者：标量 ----------


def _g_cover(b: _Bundle) -> dict:
    _TYPE = {"monthly": "月度", "quarterly": "季度", "topical": "专题"}
    t = _TYPE[b.theme]
    return {"report.title": f"{b.product}{b.label}{t}成本分析报告",
            "report.type": t, "report.month": b.label,
            "report.product": b.product, "report.date": date.today().isoformat()}


def _metric_values(base: str, cur_v, prev_v, yoy_v, bud_v) -> dict:
    return {f"{base}.current": _f(cur_v),
            f"{base}.prev": _f(prev_v),
            f"{base}.mom": _r(_pct(cur_v, prev_v), 2),
            f"{base}.yoy_value": _f(yoy_v),
            f"{base}.yoy": _r(_pct(cur_v, yoy_v), 2),
            f"{base}.budget": _f(bud_v),
            f"{base}.budget_dev": _r(_pct(cur_v, bud_v), 2)}


def _g_metrics(b: _Bundle) -> dict:
    yoy = b.yoy  # 季度主题 yoy=None（2025 季度数据未提供），显示层出"—"
    d = {"product.spec": str(b.cur["产品规格"])}
    d.update(_metric_values(
        "output", float(b.cur[C.COL_OUTPUT]),
        float(b.prev[C.COL_OUTPUT]) if b.prev is not None else None,
        float(yoy[C.COL_OUTPUT]) if yoy is not None else None,
        float(b.budget["预算产量(盒)"]) if b.budget is not None else None))
    d.update(_metric_values(
        "unit_cost", b.m.unit_cost,
        float(b.prev[C.COL_UNIT_COST]) if b.prev is not None else None,
        float(yoy[C.COL_UNIT_COST]) if yoy is not None else None,
        float(b.budget["预算单位成本(元/盒)"]) if b.budget is not None else None))
    d.update(_metric_values(
        "total_cost", b.m.total_cost,
        float(b.prev[C.COL_TOTAL_COST]) if b.prev is not None else None,
        float(yoy[C.COL_TOTAL_COST]) if yoy is not None else None,
        float(b.budget["预算总成本(元)"]) if b.budget is not None else None))
    return d


def _g_elements(b: _Bundle) -> dict:
    elem_field = {"直接材料(元/盒)": "material", "直接人工(元/盒)": "labor",
                  "制造费用(元/盒)": "overhead"}
    d: dict = {}
    for elem, fp in elem_field.items():
        e = b.m.elements[C.ELEMENT_SHORT[elem]]
        d[f"{fp}.cost.current"] = _f(e.current)
        d[f"{fp}.cost.prev"] = _f(e.prev_month)
        d[f"{fp}.cost.mom"] = _r(e.mom_pct, 2) if e.mom_pct is not None else None
        d[f"{fp}.cost.budget"] = _f(e.budget)
        d[f"{fp}.cost.budget_dev"] = (_r(e.budget_dev_pct, 2)
                                      if e.budget_dev_pct is not None else None)
        # —— 2.2 成本结构 ——
        d[f"{fp}.struct.amount"] = _f(e.current)
        d[f"{fp}.struct.share"] = (_r(e.current / b.m.unit_cost * 100, 1)
                                   if b.m.unit_cost else None)
        d[f"{fp}.struct.contribution"] = (_r(e.contribution_pct, 1)
                                          if e.contribution_pct is not None else None)
        if fp == "material":
            # labor 的环比归人工组（人工表实测口径）；overhead 与 cost.mom 同值同字段
            d["material.struct.mom"] = (_r(e.mom_pct, 2)
                                        if e.mom_pct is not None else None)
    d["unit_cost.value"] = _f(b.m.unit_cost)
    d["unit_cost.total_mom"] = (_r(b.m.unit_cost_mom_pct, 2)
                                if b.m.unit_cost_mom_pct is not None else None)
    # extras 保险字段（现模板无占位符，直出兼容键；见 _EXTRAS_LEGACY_KEY）
    d["alerts.description"] = ("；".join(a.message for a in b.m.alerts)
                               if b.m.alerts else "本月各要素波动均在阈值内，无告警。")
    return d


def _g_labor(b: _Bundle) -> dict:
    lab, lab_prev = b.lab, b.lab_prev
    d = {"labor.unit.current": _f(lab["单位人工成本(元/盒)"]),
         "labor.unit.prev": (_f(lab_prev["单位人工成本(元/盒)"])
                             if lab_prev is not None else None),
         "labor.unit.mom": _r(_pct(lab["单位人工成本(元/盒)"],
                                   lab_prev["单位人工成本(元/盒)"]
                                   if lab_prev is not None else None), 2)}
    for key, col in (("hours", "人工工时(h/万盒)"), ("wage", "平均小时工资(元/h)"),
                     ("efficiency", "人工效率(盒/人·日)")):
        cv = float(lab[col]) if lab is not None else None
        pv = float(lab_prev[col]) if lab_prev is not None else None
        d[f"labor.{key}.current"] = _f(cv)
        d[f"labor.{key}.prev"] = _f(pv)
        d[f"labor.{key}.mom"] = _r(_pct(cv, pv), 2)
    return d


def _g_overhead(b: _Bundle) -> dict:
    d: dict = {}
    for cat in _OVERHEAD_CATS:
        fp = _OVERHEAD_FIELD[cat]
        cv = b.ov.get(cat)
        pv = b.ov_prev.get(cat)
        d[f"{fp}.current"] = _f(cv)
        d[f"{fp}.prev"] = _f(pv)
        d[f"{fp}.mom"] = _r(_pct(cv, pv), 2)
        d[f"{fp}.note"] = _overhead_note(cat, cv, pv)
    ov_total = sum(v for v in b.ov.values() if v is not None)
    ov_total_prev = (sum(v for v in b.ov_prev.values() if v is not None)
                     if b.ov_prev else None)
    d["overhead.total.current"] = _f(ov_total)
    d["overhead.total.prev"] = _f(ov_total_prev)
    d["overhead.total.mom"] = _r(_pct(ov_total, ov_total_prev), 2)
    return d


# ---------- 组生产者：动态表行数据 ----------


def _rows_materials(b: _Bundle) -> dict:
    """3.1.1 原材料成本明细表。"""
    mats = b.store.query(
        f'SELECT "{C.COL_MAT_NAME}", "{C.COL_MAT_UNIT_COST}" FROM materials '
        f'WHERE {C.COL_PRODUCT}=? AND {C.COL_MONTH}=?', (b.product, b.month))
    mats_prev = b.store.query(
        f'SELECT "{C.COL_MAT_NAME}", "{C.COL_MAT_UNIT_COST}" FROM materials '
        f'WHERE {C.COL_PRODUCT}=? AND {C.COL_MONTH}=?', (b.product, b.prev_m)) \
        if b.prev_m else None
    prev_price = ({r[C.COL_MAT_NAME]: float(r[C.COL_MAT_UNIT_COST])
                   for _, r in mats_prev.iterrows()} if mats_prev is not None else {})
    rows = []
    for i, (_, r) in enumerate(mats.iterrows()):
        name = r[C.COL_MAT_NAME]
        cv = float(r[C.COL_MAT_UNIT_COST])
        pv = prev_price.get(name)
        rows.append([str(i + 1), name, _f(cv), _f(pv) if pv is not None else "—",
                     (f"{_pct(cv, pv):+.1f}%" if pv else "—"),
                     _mat_reason(name)])
    return {"rows.materials": rows}


def _rows_trend(b: _Bundle) -> dict:
    """4.1 近6个月成本趋势表（沿 _prev_month 链跨年回溯；数据空洞月跳过不编造）。"""
    trend_months = [b.month]
    while len(trend_months) < 6:
        pm = _prev_month(trend_months[-1])
        if pm is None:
            break
        trend_months.append(pm)
    trend_months.reverse()
    rows = []
    prev_uc = None
    for mth in trend_months:
        s = b.calc._safe_summary(b.product, mth)
        if s is None:
            continue  # 数据空洞月（如 2025-12）跳过，不编造
        uc = float(s[C.COL_UNIT_COST])
        rows.append([mth, int(s[C.COL_OUTPUT]),
                     _f(float(s["直接材料(元/盒)"])), _f(float(s["直接人工(元/盒)"])),
                     _f(float(s["制造费用(元/盒)"])), _f(uc),
                     (f"{_pct(uc, prev_uc):+.1f}%" if prev_uc else "—")])
        prev_uc = uc
    return {"rows.trend": rows}


def _rows_price(b: _Bundle) -> dict:
    """4.3 原材料价格跟踪表（行情覆盖的药材）。"""
    rows = []
    for d in b.m.decomposition:
        if d.price_curr is None:
            continue
        jan = _market_price(b.store, d.material, f"{b.month[:4]}-01")
        chg = _pct(d.price_curr, jan) if jan else None
        rows.append([d.material, _f(jan) if jan else "—", _f(d.price_curr),
                     (f"{chg:+.1f}%" if chg is not None else "—"),
                     _market_trend(b.store, d.material),
                     _price_impact(d)])
    return {"rows.price": rows}


def _rows_benchmark(b: _Bundle) -> dict:
    """5.1 对标差异表（双向口径描述直接引用 description）。"""
    rows = [[r.element, _f(r.main), _f(r.bench), _f(r.diff),
             f"{r.diff_rate_pct:+.2f}%", r.direction] for r in b.diff.rows]
    return {"rows.benchmark": rows}


def _rows_rectify(b: _Bundle) -> dict:
    """6.4 整改任务表（规则直出：告警→任务，五字段赛题模块四契约）。"""
    return {"rows.rectify": _rectify_tasks(b.product, b.month, b.m.alerts)}


def _rows_suggest(b: _Bundle) -> dict:
    """6.3 改进建议表（规则兜底行；LLM 在 report_gen.py 中可覆盖措辞）。"""
    return {"rows.suggest": _suggestion_rows(b.m.alerts)}


# ---------- 行数据辅助（供动态表组调用） ----------


def _market_price(store, material: str, month: str) -> float | None:
    df = store.query(
        'SELECT "市场价" FROM market_long WHERE 药材名称=? AND 月份=?', (material, month))
    return None if df.empty else float(df.iloc[0]["市场价"])


def _market_trend(store, material: str) -> str:
    df = store.query(
        'SELECT "趋势分析" FROM market WHERE 药材名称=?', (material,))
    return "" if df.empty else str(df.iloc[0]["趋势分析"])


def _mat_reason(material: str) -> str:
    return "详见 4.3 价格跟踪与 3.1.2 归因"


def _overhead_note(cat: str, cv, pv) -> str:
    if cv is None or pv is None:
        return "—"
    mom = _pct(cv, pv)
    if mom is None:
        return "—"
    if abs(mom) < 3:
        return "正常波动"
    return "增幅超3%，需关注" if mom > 0 else "降幅超3%，核查计量口径"


def _price_impact(d) -> str:
    if d.price_effect is None:
        return d.note or "—"
    return f"价差影响 {d.price_effect:+.3f} 元/盒"


def _rectify_tasks(product: str, month: str, alerts) -> list[list]:
    """告警 → 整改任务五字段（任务编号/标题/责任人/优先级/来源/截止时间）。"""
    y, mth = int(month[:4]), int(month[5:7])
    deadline = f"{y}-{mth + 1:02d}-25" if mth < 12 else f"{y + 1}-01-25"
    rows = []
    for i, a in enumerate(alerts, 1):
        dept, prio = _DEPT_RULES.get(a.channel, ("财务部", "中"))
        rows.append([f"ZG-{month}-{i:02d}",
                     f"核查{a.element}异常（{a.channel}）",
                     dept, prio, f"成本告警·{product} {month}", deadline])
    return rows or [["—", "本月无整改任务", "—", "—", "—", "—"]]


def _suggestion_rows(alerts) -> list[list]:
    """规则兜底建议（无 LLM 时）：每条告警一条，责任部门/优先级同源规则。"""
    rows = []
    for i, a in enumerate(alerts, 1):
        dept, prio = _DEPT_RULES.get(a.channel, ("财务部", "中"))
        action = ("核查采购合同调价条款，评估锁价备货" if "采购" in dept
                  else "排查对应工序单耗与收率波动")
        rows.append([str(i), f"{a.element}异常：{action}", dept, prio,
                     "抑制成本异常涨幅", "次月25日前"])
    return rows or [["1", "维持现行成本管控节奏，持续跟踪行情", "财务部", "低",
                     "保持成本稳定", "持续"]]


# ---------- 组注册表 + 导入时校验 ----------


@dataclass(frozen=True)
class _Group:
    """一个生产者组：name 用于报错定位；provides 为标准字段声明；
    extras 为注册表外保险字段（模板变体引入对应占位符后经 YAML 生效）。"""
    name: str
    provides: tuple[str, ...]
    fn: Callable[[_Bundle], dict]
    extras: tuple[str, ...] = ()


_SCALAR_GROUPS: tuple[_Group, ...] = (
    _Group("封面组",
           ("report.title", "report.type", "report.month",
            "report.product", "report.date"),
           _g_cover),
    _Group("2.1核心指标组",
           ("product.spec",)
           + _metric_fields("output")
           + _metric_fields("unit_cost")
           + _metric_fields("total_cost"),
           _g_metrics),
    _Group("要素与结构组",
           _ELEM21_FIELDS + _ELEM22_FIELDS + ("unit_cost.value", "unit_cost.total_mom"),
           _g_elements, extras=("alerts.description",)),
    _Group("3.2人工组", _LABOR_FIELDS, _g_labor),
    _Group("3.3制造费用组", _OVERHEAD_FIELDS, _g_overhead),
)

_DYNAMIC_GROUPS: tuple[_Group, ...] = (
    _Group("动态表·原材料成本明细", ("rows.materials",), _rows_materials),
    _Group("动态表·近6个月成本趋势", ("rows.trend",), _rows_trend),
    _Group("动态表·原材料价格跟踪", ("rows.price",), _rows_price),
    _Group("动态表·对标差异", ("rows.benchmark",), _rows_benchmark),
    _Group("动态表·整改任务", ("rows.rectify",), _rows_rectify),
    _Group("动态表·改进建议", ("rows.suggest",), _rows_suggest),
)

# 代码声明的标准字段全集（mapping.py 第②层校验的对账基准）
ALL_SCALAR_FIELDS = frozenset(k for g in _SCALAR_GROUPS for k in g.provides)
ALL_ROW_FIELDS = frozenset(k for g in _DYNAMIC_GROUPS for k in g.provides)


def _validate_groups(scalar_groups: tuple[_Group, ...] | None = None,
                     dynamic_groups: tuple[_Group, ...] | None = None) -> None:
    """导入时校验（本模块 import 即执行；测试用假数据复验）：
    组声明自洽（无争抢、并集 == 声明全集）——任一不符即 ImportError 并打印差集。"""
    scalar_groups = _SCALAR_GROUPS if scalar_groups is None else scalar_groups
    dynamic_groups = _DYNAMIC_GROUPS if dynamic_groups is None else dynamic_groups

    seen: dict[str, str] = {}
    for g in scalar_groups:
        for k in g.provides:
            if k in seen:
                raise ImportError(f"标准字段 {k!r} 被两组争抢: {seen[k]} / {g.name}")
            seen[k] = g.name
    if set(seen) != ALL_SCALAR_FIELDS:
        missing = sorted(ALL_SCALAR_FIELDS - set(seen))
        extra = sorted(set(seen) - ALL_SCALAR_FIELDS)
        raise ImportError(f"标量字段声明对不上账: 缺 {missing} 多 {extra}")

    dyn_seen: dict[str, str] = {}
    for g in dynamic_groups:
        for k in g.provides:
            if k in dyn_seen:
                raise ImportError(f"动态表字段 {k!r} 被两组争抢: {dyn_seen[k]} / {g.name}")
            dyn_seen[k] = g.name
    if set(dyn_seen) != ALL_ROW_FIELDS:
        missing = sorted(ALL_ROW_FIELDS - set(dyn_seen))
        extra = sorted(set(dyn_seen) - ALL_ROW_FIELDS)
        raise ImportError(f"动态表字段声明对不上账: 缺 {missing} 多 {extra}")


_validate_groups()  # ← 导入即校验：声明缺键/错键/争抢在此刻爆炸


# ---------- 主入口 ----------


class ReportContextBuilder:
    def __init__(self, calc: CostCalculator):
        self.calc = calc
        self.store = calc.store

    def build(self, product: str, month: str, theme: str = "monthly",
              quarter: str | None = None) -> dict:
        """返回 docxtpl context：标准字段经 L1 映射翻译为模板键（89 标量 + 6 动态表）。
        theme=quarterly 时 quarter 必填（Q1/Q2），数据走季度加权合成口径。"""
        if theme == "quarterly":
            if quarter not in ("Q1", "Q2"):
                raise ValueError(f"季度主题须指定 quarter=Q1/Q2: {quarter}")
            bundle = _make_quarter_bundle(self.calc, product, quarter)
        else:
            bundle = _make_bundle(self.calc, product, month)
        values: dict = {}
        for g in _SCALAR_GROUPS + _DYNAMIC_GROUPS:
            d = g.fn(bundle)
            want = set(g.provides) | set(g.extras)
            if set(d) != want:
                raise AssertionError(
                    f"{g.name} 产出字段集与声明不符: "
                    f"缺 {sorted(want - set(d))} 多 {sorted(set(d) - want)}")
            values.update(d)

        from .mapping import MAPPING  # 延迟导入避免环（mapping 校验需本模块声明集）
        ctx = MAPPING.scalar_context(values)
        for field_id, legacy_key in _EXTRAS_LEGACY_KEY.items():
            ctx[legacy_key] = values[field_id]
        self._assert_coverage(ctx)  # 运行时兜底：防模板漂移与绕路改码
        return ctx

    # ---------- 覆盖自检（兜底，设计上永不触发） ----------
    @staticmethod
    def _assert_coverage(ctx: dict) -> None:
        """注册表完备性：89 标量缺一不可；6 动态表行数据缺一不可。"""
        missing = [k for k in SCALAR_PLACEHOLDERS if k not in ctx]
        if missing:
            raise AssertionError(f"标量占位符缺 {len(missing)} 个: {missing[:8]}")
        missing_t = [k for k in DYNAMIC_TABLE_PLACEHOLDERS if f"__rows__{k}" not in ctx]
        if missing_t:
            raise AssertionError(f"动态表格行数据缺失: {missing_t}")
