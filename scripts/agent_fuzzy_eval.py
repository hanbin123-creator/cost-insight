"""模糊语义有效性评估（A12 前置验证）：口语化/指代/域外用例实测路由表现。

回答的问题：分类角色模型（小模型三件套，未配置时回退主模型）对
"不像指令的人话"能不能正确路由。

用法：
  python scripts/agent_fuzzy_eval.py             # 原 26 条，LLM 主线实弹
  python scripts/agent_fuzzy_eval.py --no-llm    # 纯规则兜底对照组
  python scripts/agent_fuzzy_eval.py --extended  # 原 26 + 104 条留出题，共 130 条

判定口径（路由正确性 ≠ 场景执行成功）：
- pass = 意图命中 + 行为类别符合预期（exec/clarify/nav-any/out）
- 扩展题若声明 expect_params，还必须通过 view/anchor/product/month 逐项对账
- result.ok 另记为执行信息，不因外部服务（如 RPA mock）可用性误判路由

输出 docs/_fuzzy_eval/fuzzy_eval_<mode>_<timestamp>.json + 控制台汇总表。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import route
from app.charts import ChartBuilder
from app.compute import CostCalculator
from app.ingest import init_store
from app.pipeline import Deps, Pipeline

LATEST = "2026-06"
KB_DOCS = ["GMP法规核心摘要_2010修订版.pdf", "产品配方文档_六味地黄胶囊.pdf",
           "产品配方文档_板蓝根颗粒.pdf", "产品配方文档_银黄口服液.pdf",
           "数据飞轮_整改经验记录.txt", "生产工艺文档_中药一厂.pdf",
           "药品生产质量管理规范GMP.pdf", "车间设备清单_中药一厂.pdf"]

# expect 行为类别：exec=应直接产出结果 / clarify=应给澄清chips /
# nav-any=意图应为nav（锚点命中或chips皆可）/ out=应判域外
CASES = [
    # A 口语化场景意图（规则关键词表外的"人话"，主考 LLM/小模型分类）
    {"group": "A-口语意图", "text": "最近成本咋样啊",
     "intent": "dashboard", "expect": "clarify"},
    {"group": "A-口语意图", "text": "板蓝根上个月成本走势如何",
     "intent": "dashboard", "expect": "exec"},
    {"group": "A-口语意图", "text": "跟二厂比起来我们差多少",
     "intent": "benchmark", "expect": "clarify"},
    {"group": "A-口语意图", "text": "帮我瞅瞅六味地黄跟人家的差距",
     "intent": "benchmark", "expect": "clarify"},
    {"group": "A-口语意图", "text": "银黄口服液三月份对标一下",
     "intent": "benchmark", "expect": "exec"},
    {"group": "A-口语意图", "text": "出个报告呗",
     "intent": "report", "expect": "clarify"},
    {"group": "A-口语意图", "text": "把二季度的报告搞出来",
     "intent": "report", "expect": "clarify"},
    {"group": "A-口语意图", "text": "生成六味地黄胶囊的一季度报告",
     "intent": "report", "expect": "exec"},
    {"group": "A-口语意图", "text": "催一下整改进度",
     "intent": "rectify", "expect": "clarify"},
    {"group": "A-口语意图", "text": "把板蓝根颗粒五月份超支的活儿派下去",
     "intent": "rectify", "expect": "exec"},
    {"group": "A-口语意图", "text": "为啥五月份成本突然蹿上去了",
     "intent": "qa", "expect": "exec"},
    {"group": "A-口语意图", "text": "GMP 对物料管理是咋规定的",
     "intent": "qa", "expect": "exec"},
    {"group": "A-口语意图", "text": "超标了一般要走啥流程",
     "intent": "qa", "expect": "exec"},
    # B 模糊指代（"那个/这张/红的"，view 上下文下的内容级目标解析）
    {"group": "B-模糊指代", "text": "打开那个瀑布图", "view": "dashboard",
     "expect": "nav-any"},
    {"group": "B-模糊指代", "text": "打开热力图", "view": "dashboard",
     "expect": "nav-any"},
    {"group": "B-模糊指代", "text": "把那个红的打开看看", "view": "dashboard",
     "expect": "nav-any"},
    {"group": "B-模糊指代", "text": "打开知识库里银黄的配方文档", "view": "kb",
     "expect": "nav-any"},
    {"group": "B-模糊指代", "text": "去看整改追踪", "expect": "nav-any"},
    {"group": "B-模糊指代", "text": "切换到对标分析", "expect": "nav-any"},
    # C 域外拒绝（域围栏：不许硬归四意图）
    {"group": "C-域外", "text": "今天天气怎么样", "expect": "out"},
    {"group": "C-域外", "text": "给我讲个笑话呗", "expect": "out"},
    {"group": "C-域外", "text": "帮我写个请假条", "expect": "out"},
    {"group": "C-域外", "text": "食堂中午吃啥", "expect": "out"},
    # D 边界混淆（设计口径压力点：无跳转动词不归 nav，归场景意图）
    {"group": "D-边界", "text": "看看热力图",
     "intent": "dashboard", "expect": "clarify"},
    {"group": "D-边界", "text": "那张趋势图给我瞅瞅", "view": "dashboard",
     "intent": "dashboard", "expect": "clarify"},
    {"group": "D-边界", "text": "下个月成本会不会涨",
     "intent": "qa", "expect": "exec"},
]


def _behavior(out: dict) -> str:
    if out["layer"] == "llm-out-of-scope":
        return "out"
    r = out.get("result")
    if isinstance(r, dict) and r.get("choices"):
        return "choices"
    if out.get("clarification"):
        return "clarify"
    if r is not None:
        return "exec"
    return "other"


def _param_mismatch(case: dict, out: dict) -> dict:
    """扩展集的严格目标校验：view/anchor/product/month 逐项对账。"""
    actual = out.get("params") or {}
    return {k: {"expect": v, "actual": actual.get(k)}
            for k, v in (case.get("expect_params") or {}).items()
            if actual.get(k) != v}


def _pass(case: dict, out: dict, beh: str, use_llm: bool) -> bool:
    if _param_mismatch(case, out):
        return False
    exp = case["expect"]
    if exp == "nav-any":
        return out["intent"] == "nav" and beh in ("exec", "clarify")
    if exp == "out":
        # 无 LLM 时域外只能靠双不命中落四入口，同样是正确处置
        return beh == "out" if use_llm else beh == "choices"
    return out["intent"] == case["intent"] and beh == exp


def _arg_int(name: str, default: int) -> int:
    """--from/--to 分段参数（1 起含端点）：本地小模型评估慢，支持分段前台跑。"""
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            return int(sys.argv[i + 1])
    return default


def main() -> int:
    use_llm = "--no-llm" not in sys.argv
    extended = "--extended" in sys.argv
    cases = CASES
    if extended:
        from agent_fuzzy_extended_cases import EXTRA_CASES
        cases = CASES + EXTRA_CASES       # 104 条留出题；原 26 条顺序保持不变
    mode = ("extended-" if extended else "") + ("llm" if use_llm else "rule-only")
    lo, hi = _arg_int("--from", 1), _arg_int("--to", len(cases))
    store, _ = init_store()
    calc = CostCalculator(store)
    out_dir = Path("docs/_fuzzy_eval")
    out_dir.mkdir(parents=True, exist_ok=True)
    pipeline = Pipeline(Deps(calc=calc, charts=ChartBuilder(calc), out_dir=out_dir))
    llm = None
    if use_llm:
        from app.llm import LLMClient
        llm = LLMClient(role="classification")
        # 本地 CPU 小模型单次推理可达 20-40s：评估期放宽超时（角色档案 30s 面向云端）
        if llm.role_actual == "small-model":
            llm.timeout = 180.0
        print(f"classifier role_actual = {llm.role_actual}  model = {llm.model}"
              f"  timeout = {llm.timeout}", flush=True)

    rows = []
    jsonl = out_dir / f"fuzzy_rows_{mode}.jsonl"   # 增量落盘：超时中断不丢已完成行
    for i, case in enumerate(cases, 1):
        if not (lo <= i <= hi):
            continue
        t0 = time.perf_counter()
        out = route(case["text"], pipeline, llm=llm, latest_month=LATEST,
                    view=case.get("view"), kb_docs=KB_DOCS)
        ms = round((time.perf_counter() - t0) * 1000)
        beh = _behavior(out)
        mismatch = _param_mismatch(case, out)
        ok = _pass(case, out, beh, use_llm)
        r = out.get("result") or {}
        rows.append({
            "no": i, "group": case["group"], "text": case["text"],
            "expect_intent": case.get("intent"), "expect": case["expect"],
            "expect_params": case.get("expect_params"),
            "intent": out["intent"], "confidence": out["confidence"],
            "layer": out["layer"], "classifier": out.get("classifier"),
            "behavior": beh, "pass": ok, "param_mismatch": mismatch,
            "latency_ms": ms, "params": out.get("params"), "exec_ok": r.get("ok"),
            "anchor": (out.get("params") or {}).get("anchor"),
        })
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {i:02d} {case['group']} | {case['text']!r} → "
              f"intent={out['intent']} layer={out['layer']} beh={beh} "
              f"conf={out['confidence']} {ms}ms"
              + (f" mismatch={mismatch}" if mismatch else ""), flush=True)
        with jsonl.open("a", encoding="utf-8") as fp:   # 逐行落盘，中断可续
            fp.write(json.dumps(rows[-1], ensure_ascii=False) + "\n")

    total = len(rows)
    passed = sum(1 for r in rows if r["pass"])
    span = f"（分段 {lo}-{hi}）" if (lo, hi) != (1, len(cases)) else ""
    print(f"\n===== {mode} 汇总{span}：{passed}/{total} = {passed / total:.1%} =====")
    groups: dict[str, list[bool]] = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r["pass"])
    for g, ps in groups.items():
        print(f"  {g}: {sum(ps)}/{len(ps)}")
    layers: dict[str, int] = {}
    for r in rows:
        layers[r["layer"]] = layers.get(r["layer"], 0) + 1
    print(f"  路由层分布: {layers}")
    if use_llm:
        lat = [r["latency_ms"] for r in rows]
        print(f"  延迟: avg={sum(lat) // len(lat)}ms max={max(lat)}ms")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_r{lo}-{hi}" if (lo, hi) != (1, len(cases)) else ""
    path = out_dir / f"fuzzy_eval_{mode}_{ts}{suffix}.json"
    path.write_text(json.dumps({
        "mode": mode, "ts": ts, "latest_month": LATEST,
        "suite_size": len(cases), "held_out_cases": 104 if extended else 0,
        "classifier": rows[0]["classifier"] if rows else None,
        "pass": passed, "total": total, "rate": round(passed / total, 4),
        "groups": {g: f"{sum(ps)}/{len(ps)}" for g, ps in groups.items()},
        "layers": layers, "cases": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细已存: {path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
