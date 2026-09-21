"""模板占位符提取脚本（模板自适应方案 3.1）——换模板第一道工序，一条命令。

用法（项目根目录下）：
  python scripts/extract_placeholders.py --check          # 漂移检测：模板 vs 注册表（CI/测试用）
  python scripts/extract_placeholders.py --write          # 重建 app/report_registry.py
  python scripts/extract_placeholders.py --template 路径  # 指定模板（默认 assets/report_template.docx）

--check：模板与注册表不一致时打印差集并以退出码 1 失败。
--write：按启发式分类重建注册表并打印分类清单——落盘前请人工核对分类
        （独立段落"表格"结尾→动态表；其余独立段落→待判别（--assign）；句中/表格内→标量）。
--init-yaml：从模板 + 现有 placeholder_map.yaml 生成映射骨架（同名键复用旧映射、
        别名规则自动预填、其余标 TODO），换模板时改骨架比从零写 YAML 快且不易漂移。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.template_scan import (classify_with_registry, diff_against_registry,  # noqa: E402
                               extract_placeholders)

DEFAULT_TEMPLATE = ROOT / "assets" / "report_template.docx"
REGISTRY = ROOT / "app" / "report_registry.py"

_HEADER = '''"""官方报告模板占位符注册表（{total} 个，由 assets/report_template.docx 实测提取）。

本文件由 scripts/extract_placeholders.py --write 生成；test_report.py 会对模板做漂移检测。
动态表格占位符：渲染时替换为哨兵文本，再由 python-docx 插入真实表格。
文本段落占位符：LLM 声明制生成或代码模板句兜底（标注来源）。
"""

'''


def _fmt_set(name: str, keys: set[str]) -> str:
    body = "\n".join(f'    "{k}",' for k in sorted(keys))
    return f"{name} = frozenset({{\n{body}\n}})\n"


def _suggest_command(args, unknown, mode: str = "--write") -> str:
    """改5：拒绝落盘时给出可复制的完整命令骨架——人工步压缩到一次复制粘贴。"""
    cmd = f"python scripts/extract_placeholders.py {mode}"
    if Path(args.template) != DEFAULT_TEMPLATE:
        cmd += f' --template "{args.template}"'
    for a in args.assign:
        cmd += f' --assign "{a}"'
    for k in sorted(unknown):
        cmd += f' --assign "{k}=??"'
    return cmd


def _init_yaml(args, cls) -> int:
    """--init-yaml：换模板时生成映射骨架（同名键复用旧映射 + 别名预填 + TODO 标记）。

    漂移从"不可见"变"可审计"：骨架是活标本，运维改完 diff 一下就知道动了什么。"""
    import re as _re

    import yaml
    old_path = ROOT / "config" / "placeholder_map.yaml"
    old = yaml.safe_load(old_path.read_text(encoding="utf-8")) \
        if old_path.exists() else {}
    old = old or {}
    old_scalars = dict(old.get("scalars") or {})
    alias_rules = [(_re.compile(a["pattern"]), a["replace"])
                   for a in (old.get("aliases") or [])
                   if "pattern" in a and "replace" in a]

    def _lookup(key: str) -> str:
        if key in old_scalars:
            return old_scalars[key]                 # 同名键：直接复用旧映射
        for pat, rep in alias_rules:                # 别名规则：自动预填
            cand = pat.sub(rep, key, count=1)
            if cand != key and cand in old_scalars:
                return old_scalars[cand]
        return "TODO  # ← 请填标准字段 id（见 app/report_data.py ALL_SCALAR_FIELDS）"

    out = {
        "scalars": {k: _lookup(k) for k in sorted(cls["scalars"])},
        "dynamic_tables": {k: dict(old.get("dynamic_tables") or {}).get(
            k, "TODO  # ← 请填 rows.* 字段 id") for k in sorted(cls["dynamic_tables"])},
        "text_sections": {k: dict(old.get("text_sections") or {}).get(
            k, "TODO  # ← 请填 section.* 字段 id") for k in sorted(cls["text_sections"])},
        "aliases": old.get("aliases") or [],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = "# 由 extract_placeholders.py --init-yaml 生成的映射骨架\n" \
           "# 同名键已复用旧映射；标 TODO 的请对照 app/report_data.py 声明集补齐，\n" \
           "# 补齐后重命名为 config/placeholder_map.yaml（Mapping 导入时会做双层校验）。\n" \
           + yaml.safe_dump(out, allow_unicode=True, sort_keys=False)
    out_path.write_text(text, encoding="utf-8")
    n_todo = text.count("TODO  # ←")   # 只数映射项里的待补标记，不数头注释
    print(f"已生成映射骨架 {out_path}（TODO {n_todo} 处待人工补齐）")
    if n_todo:
        print("下一步：补齐 TODO → 重命名为 config/placeholder_map.yaml → "
              "启动任意模块触发 Mapping 双层校验")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="漂移检测（退出码报结果）")
    ap.add_argument("--write", action="store_true", help="重建 report_registry.py")
    ap.add_argument("--init-yaml", action="store_true",
                    help="生成 placeholder_map 映射骨架（同名复用+别名预填+TODO 标记）")
    ap.add_argument("--out", default=str(ROOT / "config" / "placeholder_map.generated.yaml"),
                    help="--init-yaml 的输出路径")
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--assign", action="append", default=[],
                    metavar="键=scalar|dynamic|text",
                    help="人工指定独立段落新键的归类（可多次；消防演习/模板改版用）")
    args = ap.parse_args()
    if not (args.check or args.write or args.init_yaml):
        ap.error("必须指定 --check、--write 或 --init-yaml")
    assignments = dict(a.split("=", 1) for a in args.assign)

    found = extract_placeholders(Path(args.template))
    cls = classify_with_registry(found, assignments)
    print(f"模板提取：共 {len(found['all'])} 个占位符 = "
          f"标量 {len(cls['scalars'])} + 动态表 {len(cls['dynamic_tables'])} "
          f"+ 文本段 {len(cls['text_sections'])}"
          + (f" + 待人工判别 {len(cls['unknown'])}" if cls["unknown"] else ""))

    if args.check:
        diff = diff_against_registry(found)
        if not any(diff.values()):
            print("--check 通过：模板与注册表一致，无漂移")
            return 0
        print("--check 失败：检测到模板漂移！")
        if diff["missing"]:
            print("  模板新增（注册表缺失）:", diff["missing"])
        if diff["stale"]:
            print("  模板删除（注册表残留）:", diff["stale"])
        if diff["misclassified"]:
            print("  分类不一致:", diff["misclassified"])
        return 1

    if args.init_yaml:
        if cls["unknown"]:
            print("待判别键未归类，请先补 --assign：")
            print("  " + _suggest_command(args, cls["unknown"], "--init-yaml"))
            return 2
        return _init_yaml(args, cls)

    # --write
    if cls["unknown"]:
        print("拒绝落盘：以下独立段落键无法自动归类（文本段还是独立标量？）")
        print("请复制下面命令，把每个 ?? 改成 scalar 或 text 后重跑：")
        print("  " + _suggest_command(args, cls["unknown"]))
        return 2
    content = (_HEADER.format(total=len(found["all"]))
               + _fmt_set("SCALAR_PLACEHOLDERS", cls["scalars"]) + "\n"
               + _fmt_set("DYNAMIC_TABLE_PLACEHOLDERS", cls["dynamic_tables"]) + "\n"
               + _fmt_set("TEXT_SECTION_PLACEHOLDERS", cls["text_sections"]))
    print("分类清单（落盘前请人工核对）：")
    print("  动态表:", sorted(cls["dynamic_tables"]))
    print("  文本段:", sorted(cls["text_sections"]))
    REGISTRY.write_text(content, encoding="utf-8")
    print(f"已重建 {REGISTRY.name}（{len(found['all'])} 键）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
