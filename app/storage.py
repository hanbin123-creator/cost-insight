"""存储层：SQLite（竞赛版）→ PostgreSQL（企业版）的隔离点。

决策记录（四段式）：
- 决策：竞赛版用标准库 sqlite3 + pandas.read_sql，而非 SQLAlchemy
- 优点：零新增依赖，任何 Python 环境直接可跑；SQL 语句与 PG 高度兼容
- 缺点：企业版切 PG 时需在本层做方言适配（连接与占位符），多约 0.5 人日
- 裁决：值得——本层是唯一允许感知数据库的文件，业务代码只调 query()/execute()
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from . import config


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def query(sql: str, params: tuple = (), conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """业务代码取数的唯一入口。"""
    own = conn is None
    conn = conn or connect()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        if own:
            conn.close()


def execute(sql: str, params: tuple = (), conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or connect()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        if own:
            conn.close()


def write_df(df: pd.DataFrame, table: str, conn: sqlite3.Connection) -> None:
    df.to_sql(table, conn, if_exists="replace", index=False)
