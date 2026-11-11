"""检索评估集（A5）：16 条域内断言 + 2 条域外拒答验证，输出 Top1/MRR。

从原 6 条波动事件（tests/test_retrieve.py RECALL_CASES）扩充：覆盖三种产品、
配方/工艺/设备/GMP 四类文档、语义查询与编号查询两种形态；2 条域外查询
验证"得分显著低于域内"的拒答依据（评测报告取数处）。

用法：python scripts/eval_retrieval.py
被 ablation_check.py 复用：EVAL_CASES / OOD_CASES / run_eval。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 仓库根

from app import config as C                     # noqa: E402
from app.kb import build_index                  # noqa: E402
from app.retrieve import Retriever              # noqa: E402

# (查询, 目标文档名子串)：Top5 内必须命中；MRR/Top1 按目标文档首次出现名次计
EVAL_CASES: list[tuple[str, str]] = [
    # —— 原 6 条波动事件（与 RECALL_CASES 同口径，保持可比） ——
    ("金银花价格上涨的原因", "产品配方文档_银黄口服液"),
    ("黄芩提取物用量与成本", "产品配方文档_银黄口服液"),
    ("银黄口服液2月制造费用上升", "生产工艺文档_中药一厂"),
    ("六味地黄胶囊3月设备故障停机", "车间设备清单_中药一厂"),
    ("山茱萸市场行情涨价", "产品配方文档_六味地黄胶囊"),
    ("板蓝根颗粒5月原材料涨价", "产品配方文档_板蓝根颗粒"),
    # —— 扩充 10 条：编号精确查询 / 工艺参数 / 设备台账 / GMP 合规 ——
    ("PF-2026-LW-001 批次发生了什么", "产品配方文档_六味地黄胶囊"),
    ("NJP-3200 胶囊填充机维修记录", "车间设备清单_中药一厂"),
    ("DJ-300 粉碎机在哪个车间", "车间设备清单_中药一厂"),
    ("提取工序的工艺参数与温度控制", "生产工艺文档_中药一厂"),
    ("六味地黄胶囊的配方组成", "产品配方文档_六味地黄胶囊"),
    ("板蓝根颗粒配方变更记录", "产品配方文档_板蓝根颗粒"),
    ("洁净区温湿度与压差要求", "药品生产质量管理规范GMP"),
    ("GMP 对生产记录的要求", "GMP法规核心摘要"),
    ("熟地黄药材的市场价格走势", "产品配方文档_六味地黄胶囊"),
    ("中药一厂有哪些生产设备", "车间设备清单_中药一厂"),
]

# 域外查询（2 条）：知识库不覆盖，top1 得分应显著低于域内——拒答依据
OOD_CASES: list[str] = [
    "量子计算对制药成本的影响",
    "如何做一道红烧狮子头",
]


def run_eval(retriever: Retriever, cases: list[tuple[str, str]],
             top_k: int = 5, **search_kw) -> dict:
    """跑评估集，返回 {mrr, top1, top5, details}。命中口径：目标文档名子串。"""
    rr_total, top1, top5 = 0.0, 0, 0
    details = []
    for query, target in cases:
        pack = retriever.search(query, top_k=top_k, **search_kw)
        rank = next((i + 1 for i, h in enumerate(pack.hits)
                     if target in h.doc_name), None)
        rr_total += 1.0 / rank if rank else 0.0
        top1 += rank == 1
        top5 += rank is not None
        details.append({"query": query, "target": target, "rank": rank,
                        "top1_doc": pack.hits[0].doc_name if pack.hits else None})
    n = len(cases)
    return {"mrr": round(rr_total / n, 4), "top1": top1, "top5": top5, "n": n,
            "details": details}


def run_ood(retriever: Retriever, top_k: int = 5, **search_kw) -> list[dict]:
    """域外查询 top1 得分清单（拒答依据：与域内 top1 得分下限对比）。"""
    out = []
    for q in OOD_CASES:
        pack = retriever.search(q, top_k=top_k, **search_kw)
        out.append({"query": q,
                    "top1_score": pack.hits[0].rrf_score if pack.hits else None,
                    "top1_doc": pack.hits[0].doc_name if pack.hits else None})
    return out


def _get_retriever() -> Retriever:
    if not (C.KB_INDEX_DIR / "chunks.jsonl").exists():
        build_index()
    return Retriever()


def main() -> int:
    r = _get_retriever()
    res = run_eval(r, EVAL_CASES)
    print(f"评估集 {res['n']} 条 | MRR={res['mrr']:.4f} "
          f"Top1={res['top1']}/{res['n']} Top5={res['top5']}/{res['n']}")
    misses = [d for d in res["details"] if d["rank"] is None]
    for d in res["details"]:
        mark = "✓" if d["rank"] else "✗"
        print(f"  {mark} rank={d['rank'] or '-':>2} {d['query']} → {d['target']}"
              + ("" if d["rank"] else f"（实际 Top1: {d['top1_doc']}）"))
    ood = run_ood(r)
    print("域外查询（拒答验证）：")
    for d in ood:
        print(f"  top1_score={d['top1_score']:.4f} {d['query']}（{d['top1_doc']}）")
    top1_scores = []
    for case, _t in EVAL_CASES:
        pack = r.search(case, top_k=1)
        if pack.hits:
            top1_scores.append(pack.hits[0].rrf_score)
    floor = min(top1_scores) if top1_scores else 0.0
    ood_max = max((d["top1_score"] or 0.0) for d in ood)
    gap = (floor - ood_max) / floor * 100 if floor else 0.0
    verdict = ("可分，但余量仅 %.1f%%——阈值拒答需更大评估集支撑（如实报告）"
               % gap) if ood_max < floor else "重叠，不能作为拒答阈值依据（如实报告）"
    print(f"域内 top1 得分下限 {floor:.4f} vs 域外 top1 得分上限 {ood_max:.4f} → {verdict}")
    if misses:
        print(f"\n未命中 {len(misses)} 条——评估集须修正，不能带病交付")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
