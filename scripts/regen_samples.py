"""C4：用当前代码重生成 06 目录 4 份报告样例（含 A3 页脚草稿戳）。

与 POST /api/report 走完全相同的代码路径（_init + build_report + _register_report），
只是进程内调用，免去起停 uvicorn。模板只读，不改动数据包任何文件。

用法：python scripts/regen_samples.py <产品> <月份|-> <monthly|topical|quarterly> [Q1|Q2]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.api import _init, _State, _try_llm, _register_report, _REPORTS_DIR  # noqa: E402
from app.compute import CostCalculator  # noqa: E402
from app.render import build_report  # noqa: E402


def main() -> int:
    product, month, theme = sys.argv[1], sys.argv[2], sys.argv[3]
    quarter = sys.argv[4] if len(sys.argv) > 4 else None
    if month == "-":
        month = None
    t0 = time.time()
    _init()
    print(f"init {time.time()-t0:.1f}s")

    if theme == "quarterly":
        month = CostCalculator.QUARTER_MONTHS[quarter][-1]

    llm = _try_llm()
    print(f"LLM: {'已配置（真实生成）' if llm else '未配置（模板句兜底）'}")
    t0 = time.time()
    result = build_report(_State.calc, _State.retriever, llm,
                          product, month, _REPORTS_DIR, theme, quarter)
    _register_report(Path(result["docx"]).stem)
    print(f"build {time.time()-t0:.1f}s")
    print("DOCX:", result["docx"])
    print("PDF:", result.get("pdf") or "(跳过/失败——如实记录)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
