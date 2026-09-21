"""Milvus Lite 生产路径实机验证（C7）——在 Linux/Docker 环境运行。

用法：python scripts/verify_milvus_lite.py
流程：build_milvus_lite 灌库 → 同一组查询分别走 numpy / milvus_lite 后端 →
比对 Top5 chunk_id 重合度。百级 chunk 下期望 5/5 一致（开发日志02 D12 设计承诺）。
Windows 本机会在 MilvusClient 初始化时抛错——这是预期行为，如实报告不兜底。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as C
from app.kb import build_milvus_lite
from app.retrieve import Retriever

QUERIES = ["金银花 价格上涨", "设备故障 停机", "配方变更 2026-03",
           "GMP 质量管理", "供应商 交货延迟"]


def main() -> int:
    n = build_milvus_lite()
    print(f"[1/3] Milvus Lite 灌库完成：{n} 条")

    ref = Retriever(backend="numpy")
    lit = Retriever(backend="milvus_lite")
    print("[2/3] 双后端检索器就绪")

    mismatches = 0
    for q in QUERIES:
        a = [h.chunk_id for h in ref.search(q).hits]
        b = [h.chunk_id for h in lit.search(q).hits]
        overlap = len(set(a) & set(b))
        mark = "OK" if overlap == len(a) else f"⚠️ 重合 {overlap}/{len(a)}"
        if overlap != len(a):
            mismatches += 1
        print(f"  {q}: {mark}")
    print(f"[3/3] 验证结束：{len(QUERIES) - mismatches}/{len(QUERIES)} 查询完全一致")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
