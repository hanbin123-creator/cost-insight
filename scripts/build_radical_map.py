"""从 Unicode 官方 CJKRadicals.txt 生成 app/radical_map.py（D10 最优解，一次性脚本）。

用法：python scripts/build_radical_map.py
输入：data/CJKRadicals.txt（Unicode UCD 官方文件，勿手改）
输出：app/radical_map.py（完整映射：部首补充区 U+2E80-2EFF + 康熙部首区 U+2F00-2FDF）
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "CJKRadicals.txt"
OUT = ROOT / "app" / "radical_map.py"

mapping: dict[str, str] = {}
skipped: list[str] = []
for raw in SRC.read_text(encoding="utf-8").splitlines():
    line = raw.split("#")[0].strip()
    if not line:
        continue
    parts = [p.strip() for p in line.split(";")]
    if len(parts) < 3 or not all(re.fullmatch(r"[0-9A-Fa-f]+", p or " ") for p in parts[1:3]):
        skipped.append(raw)
        continue
    radical, ideograph = chr(int(parts[1], 16)), chr(int(parts[2], 16))
    if 0x2E80 <= ord(radical) <= 0x2FDF:
        mapping[radical] = ideograph

# 附录：官方表未收的简体部首变体（全库扫描实证出现，按部首编号对应统一字补齐）
# ⻄=部首146 西的变体 / ⺠=部首83 民的变体 / ⻆=部首148 角的变体 / ⻣=部首188 骨的变体
ADDENDUM = {"⻄": "西", "⺠": "民", "⻆": "角", "⻣": "骨"}
mapping.update(ADDENDUM)

header = (
    '"""CJK 部首字符 → 统一表意文字 完整映射表（自动生成，勿手改）。\n\n'
    "来源：Unicode UCD CJKRadicals.txt（官方权威数据，scripts/build_radical_map.py 生成）\n"
    "覆盖：部首补充区 U+2E80-2EFF + 康熙部首区 U+2F00-2FDF；\n"
    "      另有 4 条官方表未收的简体部首变体由脚本附录补齐（依据：部首编号对应关系）\n"
    '"""\n\n'
)
body = "RADICAL_MAP = {\n" + "".join(
    f'    "{k}": "{v}",\n' for k, v in sorted(mapping.items(), key=lambda kv: ord(kv[0]))) + "}\n"
OUT.write_text(header + body, encoding="utf-8")
print(f"生成 {OUT.name}: {len(mapping)} 条映射；跳过 {len(skipped)} 行（非映射行）")
