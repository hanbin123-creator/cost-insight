"""板块①测试：加载、校验、派生。"""
import pytest

from app.ingest import derive_labor, load_all


@pytest.fixture(scope="module")
def loaded():
    return load_all()


def test_load_all_passes_validation(loaded):
    dfs, warnings = loaded
    assert set(dfs) >= {"summary_2026", "summary_2025", "bench_2026", "materials",
                        "overhead", "budget", "labor", "market", "market_long"}
    assert len(dfs["summary_2026"]) == 18   # 3产品×6月
    assert len(dfs["materials"]) == 108
    print("\n[ingest warnings]", *warnings, sep="\n  ")


def test_percent_column_normalized(loaded):
    dfs, _ = loaded
    col = dfs["materials"]["占总材料成本比例"]
    assert col.dtype == float
    assert col.between(0, 100).all()


def test_store_persistent_connection(tmp_path):
    """D8 回归：持久连接可连续查询且可显式关闭。"""
    from app.ingest import Store, init_store
    store, _ = init_store()
    for _ in range(10):  # 连续查询复用同一连接，不再每次开关
        row = store.summary("银黄口服液", "2026-01")
        assert row["单位成本(元/盒)"] > 0
    store.close()


def test_material_share_sums_to_100(loaded):
    dfs, _ = loaded
    share = dfs["materials"].groupby(["产品名称", "月份"])["占总材料成本比例"].sum()
    assert ((share - 100).abs() <= 0.6).all(), share[(share - 100).abs() > 0.6]


def test_labor_derivation_formulas(loaded):
    dfs, _ = loaded
    l = dfs["labor"]
    row = l[(l["产品名称"] == "银黄口服液") & (l["月份"] == "2026-01")].iloc[0]
    assert row["单位人工成本(元/盒)"] == pytest.approx(68400 / 45000)
    assert row["人工工时(h/万盒)"] == pytest.approx(1344 / 45000 * 10000)
    assert row["平均小时工资(元/h)"] == pytest.approx(68400 / 1344)
    assert row["人工效率(盒/人·日)"] == pytest.approx(45000 / (8 * 21))


def test_market_long_shape(loaded):
    dfs, _ = loaded
    ml = dfs["market_long"]
    assert set(ml.columns) == {"药材名称", "月份", "市场价"}
    assert len(ml) == 13 * 6
