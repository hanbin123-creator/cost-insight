"""消融实验（A4）：逐路关闭召回通道，量化四路贡献（MRR / Top1 对比表）。

口径：与 eval_retrieval.py 同一评估集（16 条域内断言），逐路关闭
vector / bm25 / graph / exact，对照全开基线。输出直接进评测报告附录。

用法：python scripts/ablation_check.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))          # scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 仓库根

from eval_retrieval import EVAL_CASES, _get_retriever, run_eval   # noqa: E402
from app.retrieve import ALL_CHANNELS                             # noqa: E402

_CONFIGS = [("全开（基线）", ALL_CHANNELS)] + [
    (f"关闭 {ch}", tuple(c for c in ALL_CHANNELS if c != ch)) for ch in ALL_CHANNELS]


def main() -> int:
    r = _get_retriever()
    rows = []
    for label, channels in _CONFIGS:
        res = run_eval(r, EVAL_CASES, channels=channels)
        rows.append((label, res))
    base = rows[0][1]
    print(f"消融实验（评估集 {base['n']} 条，rerank 开启，Top5 命中口径）\n")
    print(f"{'配置':<14}{'MRR':>8}{'Top1':>8}{'Top5':>8}{'ΔMRR':>9}")
    for label, res in rows:
        delta = res["mrr"] - base["mrr"]
        print(f"{label:<14}{res['mrr']:>8.4f}{res['top1']:>5}/{res['n']}"
              f"{res['top5']:>5}/{res['n']}{delta:>+9.4f}")
    print("\n读法：ΔMRR 越负，该通道贡献越大；近零说明该通道在当前评估集上冗余。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
