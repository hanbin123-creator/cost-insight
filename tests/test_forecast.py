"""预测层测试：有界性 / 置信带包含 / 展示坐标对齐 / 发散 clip / 方法学性质。"""
import pytest

from app import config as C
from app.compute import CostCalculator
from app.forecast import FORECAST_MONTHS, MONTHS_2026, Forecaster
from app.ingest import init_store


@pytest.fixture(scope="module")
def fc():
    store, _ = init_store()
    return Forecaster(CostCalculator(store))


def test_forecast_structure(fc):
    d = fc.forecast("银黄口服液")
    assert d["months_ext"] == MONTHS_2026 + FORECAST_MONTHS
    assert len(d["point"]) == len(d["lower"]) == len(d["upper"]) == 3
    assert d["note"].startswith("演示级")
    assert "Holt" in d["method"]


def test_forecast_bounds_all_products(fc):
    """有界性：预测点恒在历史区间 [min*0.5, max*1.5] 内且不为负。"""
    for product in C.PRODUCTS:
        d = fc.forecast(product)
        lo, hi = min(d["history"]) * 0.5, max(d["history"]) * 1.5
        for v in d["point"]:
            assert v > 0 and lo - 1e-9 <= v <= hi + 1e-9, f"{product} 越界 {v}"
        # 置信带包含点预测
        for l, p, u in zip(d["lower"], d["point"], d["upper"]):
            assert l <= p + 1e-9 and p <= u + 1e-9


def test_display_coords_alignment(fc):
    """展示坐标预计算：虚线从最后历史点起画，置信带仅覆盖预测区。"""
    d = fc.forecast("银黄口服液")
    assert d["forecast_line"][:5] == [None] * 5
    assert d["forecast_line"][5] == d["history"][-1]
    assert d["forecast_line"][6:] == d["point"]
    assert d["band_lower_line"][:6] == [None] * 6
    # 堆叠差值 ≡ upper - lower（前端只做 stack，不做减法）
    for l, u, diff in zip(d["lower"], d["upper"], d["band_diff_line"][6:]):
        assert abs((u - l) - diff) <= 0.02  # 两位舍入快照容差
    assert d["yoy_line"][5] == d["history"][-1]


def test_holt_detects_trend(fc):
    """方法学性质：单调上升序列 → Holt 预测继续上升（非随机数生成器）。"""
    point, lower, upper = fc._holt([1.0, 1.2, 1.4, 1.6, 1.8, 2.0], 3)
    assert point[0] > 2.0 and point[2] >= point[0]
    assert all(l < p < u for l, p, u in zip(lower, point, upper))


def test_holt_flat_series(fc):
    """常数序列 → 预测≈常数，区间窄。"""
    point, lower, upper = fc._holt([5.0] * 6, 3)
    assert all(abs(p - 5.0) < 0.1 for p in point)


def test_clip_on_divergence(fc, monkeypatch):
    """护栏：Holt 发散（如异常序列外推出负成本）→ clip 并标记。"""
    # 注意第三个值必须在银黄口服液历史区间内（min*0.5≈5.35, max*1.5≈16.05），否则同样触发 clip
    monkeypatch.setattr(fc, "_holt", lambda h, s: ([-3.0, 999.0, 11.0], [-4.0] * 3, [1000.0] * 3))
    d = fc.forecast("银黄口服液")
    lo, hi = min(d["history"]) * 0.5, max(d["history"]) * 1.5
    assert d["clipped"][0] and d["clipped"][1] and not d["clipped"][2]
    assert d["point"][0] == round(lo, C.MONEY_NDIGITS)
    assert d["point"][1] == round(hi, C.MONEY_NDIGITS)
    # 展示值经两位舍入，比较容差放宽到半个分位（护栏逻辑在舍入前的原始值上执行）
    assert all(l >= lo - 0.006 and u <= hi + 0.006 for l, u in zip(d["lower"], d["upper"]))


def test_yoy_reference_reasonable(fc):
    """同比对照线与现值同量级（防单位/方向错误）。"""
    d = fc.forecast("六味地黄胶囊")
    last = d["history"][-1]
    for v in d["yoy_line"][6:]:
        assert 0.5 * last <= v <= 1.5 * last
