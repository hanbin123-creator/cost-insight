"""板块②测试：公式对账（与独立手工核算值比对）、精度、边界。"""
import pytest

from app.compute import CostCalculator
from app.ingest import init_store


@pytest.fixture(scope="module")
def calc():
    store, warnings = init_store()
    print("\n[store warnings]", *warnings, sep="\n  ")
    return CostCalculator(store)


# ---- 手工核算基准值（独立推导，非代码产出） ----
# 银黄口服液 2026-01→02：材料 6.83→6.92(+0.09) 人工 1.52→1.55(+0.03)
# 制造 2.35→2.40(+0.05) 单位成本 10.70→10.87(+0.17)
def test_contribution_reconciliation(calc):
    pack = calc.metrics("银黄口服液", "2026-02")
    m = pack.elements["直接材料"]
    assert m.mom_pct == pytest.approx(1.3, abs=0.05)          # +1.32%
    assert m.contribution_pct == pytest.approx(52.9, abs=0.1)
    assert pack.elements["直接人工"].contribution_pct == pytest.approx(17.6, abs=0.1)
    assert pack.elements["制造费用"].contribution_pct == pytest.approx(29.4, abs=0.1)
    assert pack.unit_cost_mom_pct == pytest.approx(1.6, abs=0.05)  # +1.59%
    total = sum(e.contribution_pct for e in pack.elements.values())
    assert total == pytest.approx(100, abs=0.2)               # 贡献度闭合


def test_yoy_and_budget(calc):
    pack = calc.metrics("银黄口服液", "2026-06")
    assert pack.elements["直接材料"].prev_year is not None    # 同比有数
    assert pack.elements["直接材料"].budget is not None       # 预算有数
    assert pack.unit_cost_budget_dev_pct is not None


def test_first_month_no_mom(calc):
    pack = calc.metrics("银黄口服液", "2026-01")
    assert pack.elements["直接材料"].mom_pct is None          # 1月无上月
    assert pack.decomposition == []


def test_benchmark_diff(calc):
    tree = calc.benchmark("银黄口服液", "2026-01")
    unit = [r for r in tree.rows if r.element == "单位成本"][0]
    assert unit.main == 10.70 and unit.bench == 11.11
    assert unit.diff == pytest.approx(-0.41, abs=0.005)
    assert unit.diff_rate_pct == pytest.approx(-3.7, abs=0.05)
    labor = [r for r in tree.rows if r.element == "直接人工"][0]
    # 双向口径（D3 优化）：对二厂口径 −11.6%；反向口径"二厂比一厂高"+13.2%
    assert labor.diff_rate_pct == pytest.approx(-11.6, abs=0.05)
    assert labor.reverse_rate_pct == pytest.approx(13.2, abs=0.05)
    assert "低 11.6%" in labor.description and "高 13.2%" in labor.description
    assert "1.52" in labor.description and "1.72" in labor.description
    assert labor.direction == "优势"
    assert len(tree.material_detail) == 6                     # 银黄 6 种原材料


def test_decomposition_identity(calc):
    """价差+量差 ≈ 单位消耗成本变动（分解恒等式，残差来自交叉项）。"""
    pack = calc.metrics("银黄口服液", "2026-05")
    covered = [d for d in pack.decomposition if d.covered]
    assert covered, "应有行情覆盖的原材料"
    assert all(d.method == "market_price" for d in covered)
    for d in covered:
        assert d.price_effect is not None and d.qty_effect is not None
    jyh = [d for d in covered if d.material == "金银花"][0]
    assert jyh.price_curr == 138.0 and jyh.price_prev == 130.0
    assert jyh.price_effect == pytest.approx(8 * 3.5 / 138, abs=1e-3)


def test_decomposition_uncovered_stable_price(calc):
    """D5 优化：行情未覆盖的稳价辅料按纯量差处理，口径显式标注。"""
    pack = calc.metrics("银黄口服液", "2026-05")
    unc = [d for d in pack.decomposition if not d.covered]
    assert unc, "银黄应存在行情未覆盖的辅料（如包材/纯化水）"
    for d in unc:
        assert d.method == "stable_price_assumption"
        assert d.price_effect == 0.0 and d.qty_effect is not None
        assert "假设" in d.note


def test_alert_threshold(calc):
    """三级告警（D6 优化）：通道①要素环比±10%（赛题字面，允许为空但通道存在）；
    通道②原材料环比±8%；通道③行情累计±10%（对齐官方示例口径）。"""
    seen = []
    for p in ["银黄口服液", "板蓝根颗粒", "六味地黄胶囊"]:
        for m in ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]:
            pack = calc.metrics(p, m)
            for a in pack.alerts:
                seen.append((p, m, a.channel, a.element, a.mom_pct))
                assert a.element in a.message
                limit = 10.0 if a.channel in ("要素环比", "累计涨幅") else 8.0
                assert abs(a.mom_pct) > limit
    channels = {c for _, _, c, _, _ in seen}
    assert "累计涨幅" in channels, "板蓝根1→5月累计+14.3%/金银花+10.4%应触发通道③"
    # 锚定具体事件：板蓝根颗粒 2026-05 的板蓝根累计涨幅告警
    pack = calc.metrics("板蓝根颗粒", "2026-05")
    cum = [a for a in pack.alerts if a.channel == "累计涨幅" and a.element == "板蓝根"]
    assert cum and cum[0].mom_pct == pytest.approx(14.3, abs=0.1)
    print("\n[alerts found]", *seen, sep="\n  ")


def test_quarter_weighted(calc):
    """季度加权单位成本 ≠ 月单位成本算术平均（产量不同则必有差）。"""
    q1 = calc.quarter_metrics("银黄口服液", ["2026-01", "2026-02", "2026-03"])
    naive = (10.70 + 10.87 + calc.metrics("银黄口服液", "2026-03").unit_cost) / 3
    assert q1["unit_cost_weighted"] != pytest.approx(naive, abs=1e-6)
    total = q1["total_cost"]
    # 输出层统一 2 位小数（设计纪律），对账按舍入后的期望值比对
    assert q1["unit_cost_weighted"] == pytest.approx(round(total / q1["output_qty"], 2), abs=1e-9)


def test_missing_data_raises(calc):
    with pytest.raises(KeyError):
        calc.metrics("不存在的产品", "2026-01")
