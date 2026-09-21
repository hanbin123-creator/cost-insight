"""板块① 数据整理：CSV 加载 → 规范化 → 自洽校验 → 人工指标派生 → SQLite 持久化。

设计要点：
- 加载即校验（fail-fast），任何一条不过抛 DataIntegrityError，拒绝启动
- 计算层只通过 Store 的 SQL 查询接口取数，不直接碰 CSV（企业演进换 PG 时只改连接）
- 列名一律走 config 常量（D2 红线），本文件不出现表头字面量
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from . import config as C


class DataIntegrityError(Exception):
    """数据自洽校验失败。"""


CSV_FILES = {
    "summary_2026": "01_成本明细数据/中药一厂_成本汇总_2026年1-6月.csv",
    "summary_2025": "01_成本明细数据/中药一厂_成本汇总_2025年1-6月.csv",
    "bench_2026": "01_成本明细数据/中药二厂_成本汇总_2026年1-6月.csv",
    "bench_2025": "01_成本明细数据/中药二厂_成本汇总_2025年1-6月.csv",
    "materials": "01_成本明细数据/中药一厂_原材料消耗明细_2026年1-6月.csv",
    "overhead": "01_成本明细数据/中药一厂_制造费用明细_2026年1-6月.csv",
    "budget": "01_成本明细数据/中药一厂_预算数据_2026年.csv",
    "labor": "01_成本明细数据/中药一厂_人工工时明细_2026年1-6月.csv",
    "market": "02_行业参考数据/药材市场价格行情_2026年上半年.csv",
    "industry": "02_行业参考数据/行业成本基准数据_2026.csv",
}

MONTH_COLS = [f"{m}月价格" for m in range(1, 7)]


def _read_csv(name: str) -> pd.DataFrame:
    path = C.DATA_DIR / CSV_FILES[name]
    if not path.exists():
        raise DataIntegrityError(f"数据文件缺失: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def _normalize(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """类型规范化：百分比字符串→float，月份统一 'YYYY-MM'。"""
    df = df.copy()
    for col in df.columns:
        # pandas 3.0 起字符串列 dtype 为 str 而非 object，须用 is_string_dtype 覆盖两者
        if pd.api.types.is_string_dtype(df[col]) and not pd.api.types.is_numeric_dtype(df[col]):
            vals = df[col].astype(str)
            if vals.str.endswith("%").all():
                df[col] = vals.str.rstrip("%").astype(float)
    if C.COL_MONTH in df.columns:
        df[C.COL_MONTH] = df[C.COL_MONTH].astype(str)
    return df


def _pivot_market(df: pd.DataFrame) -> pd.DataFrame:
    """行情宽表（1月价格…6月价格）转长表：药材名称, 月份, 价格。"""
    long = df.melt(id_vars=[C.COL_HERB], value_vars=MONTH_COLS,
                   var_name="月", value_name=C.COL_MKT_PRICE)
    long[C.COL_MONTH] = "2026-" + long["月"].str.rstrip("月价格").str.zfill(2)
    return long[[C.COL_HERB, C.COL_MONTH, C.COL_MKT_PRICE]]


def derive_labor(df: pd.DataFrame) -> pd.DataFrame:
    """人工工时 5 列原始数据 → 派生 4 指标（README 3.3 公式）。"""
    df = df.copy()
    df[C.COL_LABOR_UNIT_DERIVED] = df[C.COL_LABOR_TOTAL] / df[C.COL_OUTPUT]
    df["人工工时(h/万盒)"] = df[C.COL_LABOR_HOURS] / df[C.COL_OUTPUT] * 10000
    df["平均小时工资(元/h)"] = df[C.COL_LABOR_TOTAL] / df[C.COL_LABOR_HOURS]
    df["人工效率(盒/人·日)"] = df[C.COL_OUTPUT] / (df[C.COL_LABOR_HEADCOUNT] * df[C.COL_LABOR_DAYS])
    return df


def validate(dfs: dict[str, pd.DataFrame]) -> list[str]:
    """自洽校验，返回警告列表；硬错误直接抛异常。"""
    warnings: list[str] = []
    s = dfs["summary_2026"]

    # 1. 单位成本 = 三要素之和
    diff = (s[C.COST_ELEMENTS].sum(axis=1) - s[C.COL_UNIT_COST]).abs()
    bad = s[diff > C.TOL_UNIT_COST]
    if not bad.empty:
        raise DataIntegrityError(f"单位成本≠三要素之和: {bad[[C.COL_PRODUCT, C.COL_MONTH]].values.tolist()}")

    # 2. 总成本 ≈ 产量 × 单位成本（相对误差容差，允许 2 位小数快照漂移）
    rel = ((s[C.COL_OUTPUT] * s[C.COL_UNIT_COST] - s[C.COL_TOTAL_COST]).abs()
           / s[C.COL_TOTAL_COST])
    n_drift = int((rel > C.TOL_TOTAL_COST_RATIO).sum())
    if n_drift:
        warnings.append(f"总成本与产量×单位成本存在 {n_drift} 行舍入漂移(>{C.TOL_TOTAL_COST_RATIO:.4%})")

    # 3. 原材料占比合计 ≈ 100%
    share = dfs["materials"].groupby([C.COL_PRODUCT, C.COL_MONTH])[C.COL_MAT_SHARE].sum()
    bad_share = share[(share - 100).abs() > C.TOL_SHARE_SUM]
    if not bad_share.empty:
        raise DataIntegrityError(f"原材料占比合计≠100%: {bad_share.to_dict()}")

    # 4. 制造费用明细合计 = 汇总表制造费用
    o = dfs["overhead"].groupby([C.COL_PRODUCT, C.COL_MONTH])[C.COL_OVERHEAD_UNIT].sum().rename("明细合计")
    m = s.set_index([C.COL_PRODUCT, C.COL_MONTH])["制造费用(元/盒)"]
    joined = o.to_frame().join(m, how="left")
    bad_oh = joined[(joined["明细合计"] - joined["制造费用(元/盒)"]).abs() > C.TOL_OVERHEAD]
    if not bad_oh.empty:
        raise DataIntegrityError(f"制造费用明细与汇总不一致: {bad_oh.index.tolist()}")

    # 5. 人工派生：单位人工成本 与 汇总表直接人工 一致性（README 承诺严格一致）
    l = dfs["labor"].set_index([C.COL_PRODUCT, C.COL_MONTH])[C.COL_LABOR_UNIT_DERIVED]
    m2 = s.set_index([C.COL_PRODUCT, C.COL_MONTH])["直接人工(元/盒)"]
    labor_diff = (l - m2).abs()
    n_labor = int((labor_diff > 0.011).sum())
    if n_labor:
        warnings.append(f"人工派生单位成本与汇总表直接人工有 {n_labor} 行差异>0.011 元/盒（舍入漂移）")

    # 6. 行情覆盖度：原材料中有多少种能在行情表找到价格（量差价差的前提）
    mats = set(dfs["materials"][C.COL_MAT_NAME].unique())
    mkt = set(dfs["market"][C.COL_HERB].unique())
    missing = mats - mkt
    if missing:
        warnings.append(f"行情表未覆盖 {len(missing)} 种原材料: {sorted(missing)} → 这些材料无法做量差价差分解")

    return warnings


class Store:
    """数据访问层：竞赛版 SQLite；企业版换 PostgreSQL 只改连接（演进路线图 M1）。

    D8 修复：持久连接 + 锁替代每次开关连接——sqlite3 连接开销虽小，
    但 FastAPI 并发场景下频繁开关会放大；check_same_thread=False + 查询锁
    保证多线程安全（写操作仅在 rebuild 时，与查询互斥）。
    """

    def __init__(self, db_path: Path | str = C.DB_PATH):
        import threading
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.Lock()

    def rebuild(self, dfs: dict[str, pd.DataFrame]) -> None:
        with self._lock:
            for name, df in dfs.items():
                df.to_sql(name, self._conn, if_exists="replace", index=False)

    def query(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        with self._lock:
            return pd.read_sql_query(sql, self._conn, params=params)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def summary(self, product: str, month: str, factory: str = C.FACTORY_MAIN) -> pd.Series:
        table = "summary_2026" if month >= "2026-01" else "summary_2025"
        if factory == C.FACTORY_BENCH:
            table = "bench_2026" if month >= "2026-01" else "bench_2025"
        df = self.query(f"SELECT * FROM {table} WHERE {C.COL_PRODUCT}=? AND {C.COL_MONTH}=?", (product, month))
        if df.empty:
            raise KeyError(f"无数据: {factory}/{product}/{month}")
        return df.iloc[0]


def _ensure_numeric(dfs: dict[str, pd.DataFrame]) -> None:
    """V3 修复：数值列人话校验——坏值指出 文件/列/行/原值，不再裸抛 TypeError。
    必须在任何算术（派生/校验）之前调用；合法值原样转 float 写回。"""
    spec = {
        "summary_2026": [C.COL_OUTPUT, *C.COST_ELEMENTS, C.COL_UNIT_COST, C.COL_TOTAL_COST],
        "materials": [C.COL_MAT_SHARE],
        "overhead": [C.COL_OVERHEAD_UNIT],
        "labor": [C.COL_LABOR_TOTAL, C.COL_OUTPUT, C.COL_LABOR_HOURS,
                  C.COL_LABOR_HEADCOUNT, C.COL_LABOR_DAYS],
    }
    for key, cols in spec.items():
        df = dfs.get(key)
        if df is None:
            continue
        for col in cols:
            if col not in df.columns:
                continue
            coerced = pd.to_numeric(df[col], errors="coerce")
            bad = df[coerced.isna() & df[col].notna()]
            if not bad.empty:
                row0 = bad.index[0]
                raise DataIntegrityError(
                    f"数据文件 {CSV_FILES.get(key, key)} 列「{col}」第 {row0 + 2} 行 "
                    f"值「{bad.iloc[0][col]}」不是数字（表头算第 1 行）")
            df[col] = coerced


def load_all(validate_only: bool = False) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """启动入口：加载全部 CSV → 规范化 → 校验 → 派生。返回 (数据集, 警告)。"""
    dfs = {name: _normalize(_read_csv(name), name) for name in CSV_FILES}
    _ensure_numeric(dfs)                       # V3：算术前先拦非法数值（人话报错）
    dfs["labor"] = derive_labor(dfs["labor"])
    dfs["market_long"] = _pivot_market(dfs["market"])
    warnings = validate(dfs)
    return dfs, warnings


def init_store() -> tuple[Store, list[str]]:
    dfs, warnings = load_all()
    store = Store()
    store.rebuild(dfs)
    return store, warnings
