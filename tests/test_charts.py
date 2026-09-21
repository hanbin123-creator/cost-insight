"""模块二图表数据层测试：闭合对账 + 边界（负贡献/首月 None/嵌套合计）。"""
import pytest

from app import config as C
from app.charts import MONTHS_2026, ChartBuilder
from app.compute import CostCalculator
from app.ingest import init_store


@pytest.fixture(scope="module")
def charts():
    store, _ = init_store()
    return ChartBuilder(CostCalculator(store))


def test_series_shape_and_values(charts):
    d = charts.series_data("银黄口服液")
    assert d["months"] == MONTHS_2026 and len(d["unit_cost"]) == 6
    assert d["unit_cost"][0] == 10.70        # 实测锚定（同 test_benchmark_diff 口径）
    assert set(d["series"]) == {"直接材料", "直接人工", "制造费用"}
    assert d["series"]["直接人工"][0] == 1.52


def test_waterfall_closure(charts):
    """瀑布闭合：各变动段之和 ≡ 总变动（容差 2 位快照漂移 0.02）。"""
    for product in C.PRODUCTS:
        d = charts.waterfall_data(product, "2026-05")
        delta_sum = sum(s["value"] for s in d["segments"] if s["type"] == "delta")
        assert abs(delta_sum - d["total_change"]) <= 0.02
        assert abs(d["waterfall_close_gap"]) <= 0.02
        # ECharts 堆叠不变式：visible + transparent_base = max(start, end)
        for s in d["segments"]:
            assert abs(s["transparent_base"] + s["visible"]
                       - max(s["start"], s["end"])) < 1e-6


def test_waterfall_negative_total_month(charts):
    """负总变动月份：六味 2026-03 总变动 −0.58，三段全降（数据实证：本数据包
    无混合方向月份，D7 逆势贡献情形不显现——见开发日志06），闭合与堆叠不变式仍须成立。"""
    d = charts.waterfall_data("六味地黄胶囊", "2026-03")
    assert d["total_change"] == -0.58
    dirs = [s["direction"] for s in d["segments"] if s["type"] == "delta"]
    assert dirs == ["down", "down", "down"]
    delta_sum = sum(s["value"] for s in d["segments"] if s["type"] == "delta")
    assert abs(delta_sum - d["total_change"]) <= 0.02
    for s in d["segments"]:
        assert abs(s["transparent_base"] + s["visible"]
                   - max(s["start"], s["end"])) < 1e-6


def test_waterfall_first_month_rejected(charts):
    with pytest.raises(ValueError):
        charts.waterfall_data("银黄口服液", "2026-01")


def test_structure_nested_sums(charts):
    """嵌套环形对账：内环合计 = 外环合计 = 单位成本（容差快照漂移）。"""
    d = charts.structure_data("银黄口服液", "2026-01")
    inner_sum = sum(i["value"] for i in d["inner"])
    outer_sum = sum(o["value"] for o in d["outer"])
    assert abs(inner_sum - d["unit_cost"]) <= 0.02
    assert abs(outer_sum - d["unit_cost"]) <= 0.02
    mat_sum = sum(o["value"] for o in d["outer"] if o["parent"] == "直接材料")
    labor = next(i["value"] for i in d["inner"] if i["name"] == "直接材料")
    assert abs(mat_sum - labor) <= 0.02
    assert len([o for o in d["outer"] if o["parent"] == "直接材料"]) >= 5  # 配方材料全展开


def test_heatmap_shape_and_null_discipline(charts):
    d = charts.heatmap_data()
    assert len(d["rows"]) == 9 and len(d["months"]) == 6
    assert len(d["data"]) == 9 * 6
    # 首月（month_idx=0）全部 None——前端渲染"—"，不补 0
    first_month = [v for m, _, v in d["data"] if m == 0]
    assert all(v is None for v in first_month)
    # 锚定一个实测值：板蓝根颗粒·直接材料 2026-02 环比
    target = next(v for m, r, v in d["data"]
                  if m == 1 and d["rows"][r] == "板蓝根颗粒·直接材料")
    assert isinstance(target, float)
