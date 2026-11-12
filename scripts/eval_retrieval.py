"""检索评估集（A5）：40 条域内断言 + 10 条域外拒答验证，输出 Top1/MRR。

从原 6 条波动事件（tests/test_retrieve.py RECALL_CASES）两次扩充：
第一次扩至 16 条（编号精确查询/工艺参数/设备台账/GMP 合规），
2026-11-12 第二次扩至 40 条域内 + 10 条域外——达到"50 条黄金评估集"
工程惯例下限；每条查询均对照源文档实际内容编写（成本数值/工艺参数/
设备编号/法规条文/飞轮任务号均可查），8 篇知识文档每篇≥2 条；
10 条域外查询验证"得分显著低于域内"的拒答依据（评测报告取数处）。

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
    # —— 第二次扩充 24 条（2026-11-12）：每篇文档≥2 条，全部对照源文档内容 ——
    # 银黄配方（金银花单支 0.64 元 / 有效期 24 个月 / V2.0 蔗糖 1.60→1.50 降本）
    ("金银花单支成本是多少", "产品配方文档_银黄口服液"),
    ("银黄口服液的有效期是多久", "产品配方文档_银黄口服液"),
    ("蔗糖处方量为什么从1.60调整到1.50", "产品配方文档_银黄口服液"),
    # 板蓝根配方（单盒约 5.16 元 / 甘肃陇西 / 单袋 6.67g 原药材）
    ("板蓝根颗粒每盒材料成本约多少", "产品配方文档_板蓝根颗粒"),
    ("板蓝根药材的产地在哪里", "产品配方文档_板蓝根颗粒"),
    ("板蓝根颗粒单袋含多少克原药材", "产品配方文档_板蓝根颗粒"),
    # 六味配方（单盒理论 2.20 元 / 牡丹皮中风险）
    ("六味地黄胶囊单盒材料成本理论值是多少", "产品配方文档_六味地黄胶囊"),
    ("牡丹皮价格波动属于什么风险等级", "产品配方文档_六味地黄胶囊"),
    # 生产工艺（灭菌 115℃30min / 提取收率≥85% / 灯检 0.38 元 / 16 目筛 / 电耗）
    ("银黄口服液灭菌的温度和时间是多少", "生产工艺文档_中药一厂"),
    ("水提取工序的收率要求是多少", "生产工艺文档_中药一厂"),
    ("灯检工序的单盒人工成本是多少", "生产工艺文档_中药一厂"),
    ("板蓝根制粒工序用多少目的筛网", "生产工艺文档_中药一厂"),
    ("口服液车间每万盒耗电量是多少", "生产工艺文档_中药一厂"),
    # 设备台账（提取罐 45 万 / 灭菌柜山东新华 / 全厂月折旧 80,667 / 灌封机维修 15,000）
    ("多功能提取罐的原值和月折旧是多少", "车间设备清单_中药一厂"),
    ("湿热灭菌柜是哪个厂家生产的", "车间设备清单_中药一厂"),
    ("全厂设备月折旧合计多少钱", "车间设备清单_中药一厂"),
    ("2025年11月灌封一体机故障的维修费用", "车间设备清单_中药一厂"),
    # GMP 规范全文（质量受权人放行 / 召回系统 / 留样包装）
    ("质量受权人在产品放行中的职责", "药品生产质量管理规范GMP"),
    ("药品召回系统的要求是什么", "药品生产质量管理规范GMP"),
    ("成品留样的包装应当与什么相同", "药品生产质量管理规范GMP"),
    # GMP 核心摘要（QC 检验费 0.10–0.35 元/盒 / 洁净区空调=动力费）
    ("QC检验费用每批产品大约多少元每盒", "GMP法规核心摘要"),
    ("洁净区空调系统能耗属于哪类成本", "GMP法规核心摘要"),
    # 数据飞轮（TASK-2026-0002 整改建议 / 金银花异常触发任务）
    ("TASK-2026-0002-FAST 的整改建议是什么", "数据飞轮_整改经验记录"),
    ("金银花行情异常累计涨幅触发了哪个整改任务", "数据飞轮_整改经验记录"),
]

# 域外查询（10 条）：知识库不覆盖，top1 得分应显著低于域内——拒答依据
OOD_CASES: list[str] = [
    "量子计算对制药成本的影响",
    "如何做一道红烧狮子头",
    "比特币最新价格走势如何",
    "2026年世界杯冠军会是哪支球队",
    "北京到上海的高铁时刻表",
    "雅思考试怎么备考效率高",
    "多肉植物怎么浇水养护",
    "房贷提前还款划算吗",
    "太阳系一共有几大行星",
    "重庆两日游怎么安排",
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
