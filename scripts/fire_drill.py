"""消防演习（模板自适应方案·三科目全流程计时）：赛方突然更换模板。

演习设计（安全绳优先）：
- 真实官方模板**绝不被修改**——变异发生在副本上；
- 凡 --write 真实重建 report_registry.py 的科目，全程字节级备份，
  科目结束 finally 强制恢复 + --check 复验，演习结束工作区零残留；
- 每阶段计时并打印证据，产物写入 docs/e2e/fire_drill/。

三科目（漂移的三种形态，全部实测背书）：
- 科目一·改名（情形 B）：5 个占位符改名 → 完整应急链
  （漂移报警 → 重建注册表 → 映射校验列缺键 → 别名自动适配 → 补 YAML → 实产体检）
- 科目二·删除键：模板删掉一个占位符 → 优雅降级
  （--check 报"模板删除"；运行链不受影响，报告照常产出）
- 科目三·新增键（情形 C 的拒绝链路）：模板新增一个代码里没有对应字段的占位符 →
  链条**正确地拒绝**——第一级：YAML 无映射指名道姓；第二级：即便 YAML 乱填字段，
  双层校验第②层报"代码未声明"——系统算不了的数绝不以空白/残留混进报告

用法：python scripts/fire_drill.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "assets" / "report_template.docx"
REGISTRY = ROOT / "app" / "report_registry.py"
YAML_FILE = ROOT / "config" / "placeholder_map.yaml"
EVIDENCE = ROOT / "docs" / "e2e" / "fire_drill"

# 科目一：5 个占位符改名
RENAMES = {"本月产量": "当月产量", "上月产量": "上期产量",
           "报告标题": "报告名称", "产品规格": "产品型号", "材料环比": "材料环比变动"}
ALIASABLE = {"当月产量", "上期产量"}          # 预期被别名规则自动适配
NEED_MAPPING = {"报告名称": "report.title", "产品型号": "product.spec",
                "材料环比变动": "material.struct.mom"}  # 预期需人工补映射

# 科目二：删除键；科目三：新增键（无代码字段，预期两级拒绝）
DELETE_KEY = "本月产量"
ADD_KEY = "本季度能耗"
ADD_BOGUS_FIELD = "energy.quarter.current"

_T0 = time.monotonic()
_TIMINGS: list[tuple[str, float, str]] = []


def phase(name: str, note: str) -> None:
    _TIMINGS.append((name, time.monotonic() - _T0, note))
    print(f"[{_TIMINGS[-1][1]:6.1f}s] {name}: {note}")


def _mutate_template(dst: Path, replacements: dict[str, str]) -> None:
    """zip 级替换 document.xml（跨 run 也能命中；官方模板只读不动）。"""
    with zipfile.ZipFile(TEMPLATE) as zin:
        items = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    xml = items["word/document.xml"].decode("utf-8")
    for old, new in replacements.items():
        assert old in xml, f"模板里没找到 {old}"
        xml = xml.replace(old, new)
    items["word/document.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in items.items():
            zout.writestr(name, data)


def _run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    # Windows 控制台默认 GBK：子进程中文输出会炸解码线程 → stdout 变 None。
    # 双保险：子进程强制 UTF-8 输出 + 父进程按 UTF-8 解码（errors=replace 兜底）。
    child_env = dict(env if env is not None else os.environ,
                     PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable] + cmd, cwd=ROOT, env=child_env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)


@contextmanager
def _registry_guard(tag: str):
    """凡真实重建注册表的科目：字节级备份 → finally 强制恢复 → --check 复验。"""
    backup = EVIDENCE / f"_backup_registry_{tag}.py"
    shutil.copy(REGISTRY, backup)
    try:
        yield
    finally:
        shutil.copy(backup, REGISTRY)
        backup.unlink(missing_ok=True)
        r = _run(["scripts/extract_placeholders.py", "--check"])
        assert r.returncode == 0, f"{tag} 恢复后漂移检测未通过——工作区被污染！"
        phase(f"{tag}·恢复核验", "注册表字节级恢复，--check 对官方模板通过")


def _build_and_inspect(tpl: Path, yaml_path: Path | None, tag: str) -> str:
    """用变异模板实产报告（无 LLM 模板句轨，不烧 key）并体检，返回报告文件名。"""
    env = dict(os.environ, REPORT_TEMPLATE=str(tpl))
    if yaml_path is not None:
        env["PLACEHOLDER_MAP_PATH"] = str(yaml_path)
    build_src = (
        "from pathlib import Path\n"
        "from app.compute import CostCalculator\n"
        "from app.ingest import init_store\n"
        "from app.render import build_report\n"
        "from app.retrieve import Retriever\n"
        "store,_=init_store()\n"
        "res=build_report(CostCalculator(store),Retriever(),None,"
        "'银黄口服液','2026-05',Path('docs/e2e/fire_drill'))\n"
        "print('DOCX',res['docx'])\n")
    r = _run(["-c", build_src], env=env)
    assert r.returncode == 0 and "DOCX" in r.stdout, r.stdout + r.stderr
    docx_path = Path(r.stdout.strip().split("DOCX ", 1)[1])
    # 体检：零残留占位符 + 表格数量与官方模板链一致（15 = 9 静态 + 6 动态）
    import docx
    d = docx.Document(str(docx_path))
    all_text = "\n".join(p.text for p in d.paragraphs) + "\n".join(
        c.text for t in d.tables for row in t.rows for c in row.cells)
    assert not re.findall(r"\{\{[^}]+\}\}", all_text), "有占位符未替换！"
    assert len(d.tables) == 15, f"表格数 {len(d.tables)} != 15"
    # 证据改名防科目间互相覆盖（三科目产同名报告）
    final = docx_path.with_name(f"{tag}_{docx_path.name}")
    docx_path.rename(final)
    old_pdf = docx_path.with_suffix(".pdf")
    if old_pdf.exists():
        old_pdf.rename(final.with_suffix(".pdf"))
    return final.name


# ---------- 科目一 · 改名（情形 B 完整应急链） ----------

def drill_rename() -> None:
    tpl = EVIDENCE / "report_template_drill.docx"
    drill_yaml = EVIDENCE / "placeholder_map_drill.yaml"
    with _registry_guard("科目一"):
        _mutate_template(tpl, {f"{{{{{o}}}}}": f"{{{{{n}}}}}" for o, n in RENAMES.items()})
        r = _run(["scripts/extract_placeholders.py", "--check", "--template", str(tpl)])
        assert r.returncode == 1 and "模板漂移" in r.stdout, r.stdout + r.stderr
        phase("科目一①漂移检测", "改名 5 键全部报警（退出码 1）")

        r = _run(["scripts/extract_placeholders.py", "--write",
                  "--template", str(tpl), "--assign", "报告名称=scalar"])
        assert r.returncode == 0 and "101 键" in r.stdout, r.stdout + r.stderr
        phase("科目一②重建注册表", "--write 成功；1 个独立段落新键经 --assign 人工归类")

        r = _run(["-c", "import app.mapping"], env=dict(os.environ))
        out = r.stdout + r.stderr
        assert r.returncode != 0, "原 YAML 竟然通过了？别名+缺键检查失效"
        for k in NEED_MAPPING:
            assert k in out, f"缺键清单未列出 {k}: {out}"
        for k in ALIASABLE:
            assert k in out, f"别名命中未留痕 {k}: {out}"
        phase("科目一③映射校验拦截", "3 个未映射键列入人话报错；2 个改名键被别名自动适配")

        text = YAML_FILE.read_text(encoding="utf-8")
        lines = text.splitlines()
        for new_key, field in NEED_MAPPING.items():
            old_key = next(o for o, n in RENAMES.items() if n == new_key)
            for i, ln in enumerate(lines):
                if ln.strip() == f"{old_key}: {field}":
                    lines.insert(i + 1, f"  {new_key}: {field}")
                    break
            else:
                raise AssertionError(f"YAML 里没找到 {old_key} 行")
        drill_yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")
        env = dict(os.environ, PLACEHOLDER_MAP_PATH=str(drill_yaml))
        r = _run(["-c", "import app.mapping; print('MAPPING_OK')"], env=env)
        assert r.returncode == 0 and "MAPPING_OK" in r.stdout, r.stdout + r.stderr
        phase("科目一④补映射通过", "新增 3 行 YAML 后导入校验通过（含别名警告留痕）")

        name = _build_and_inspect(tpl, drill_yaml, "科目一")
        phase("科目一⑤实产体检", f"变异模板出报告：零残留占位符、15 表齐全（{name}）")


# ---------- 科目二 · 删除键（优雅降级） ----------

def drill_delete() -> None:
    tpl = EVIDENCE / "report_template_drill_delete.docx"
    _mutate_template(tpl, {f"{{{{{DELETE_KEY}}}}}": "58000"})
    r = _run(["scripts/extract_placeholders.py", "--check", "--template", str(tpl)])
    assert r.returncode == 1 and "模板删除" in r.stdout and DELETE_KEY in r.stdout, \
        r.stdout + r.stderr
    phase("科目二①漂移检测", f"删除 {{{{{DELETE_KEY}}}}} 被识别为'模板删除'（退出码 1）")

    # 注册表/YAML 未动：删键是模板侧缩水，运行链不受影响（优雅降级的核心断言）
    r = _run(["-c", "import app.mapping; print('MAPPING_OK')"], env=dict(os.environ))
    assert r.returncode == 0 and "MAPPING_OK" in r.stdout, r.stdout + r.stderr
    phase("科目二②运行链不受影响", "映射校验照常通过——缺的只是模板里的一格")

    name = _build_and_inspect(tpl, None, "科目二")
    phase("科目二③降级实产", f"少一格的模板照常出报告：零残留、15 表齐全（{name}）")


# ---------- 科目三 · 新增键（情形 C：链条正确地拒绝） ----------

def drill_add() -> None:
    tpl = EVIDENCE / "report_template_drill_add.docx"
    drill_yaml = EVIDENCE / "placeholder_map_drill_add.yaml"
    with _registry_guard("科目三"):
        _mutate_template(tpl, {f"{{{{{DELETE_KEY}}}}}":
                               f"{{{{{DELETE_KEY}}}}}{{{{{ADD_KEY}}}}}"})
        r = _run(["scripts/extract_placeholders.py", "--check", "--template", str(tpl)])
        assert r.returncode == 1 and "模板新增" in r.stdout and ADD_KEY in r.stdout, \
            r.stdout + r.stderr
        phase("科目三①漂移检测", f"新增 {{{{{ADD_KEY}}}}} 被识别为'模板新增'（退出码 1）")

        r = _run(["scripts/extract_placeholders.py", "--write", "--template", str(tpl)])
        assert r.returncode == 0 and "102 键" in r.stdout, r.stdout + r.stderr
        phase("科目三②重建注册表", "102 键落盘（新键句中内联，启发式归标量无需 --assign）")

        # 第一级拒绝：YAML 无此键映射 → 人话报错指名道姓
        r = _run(["-c", "import app.mapping"], env=dict(os.environ))
        out = r.stdout + r.stderr
        assert r.returncode != 0 and ADD_KEY in out, \
            f"新增键未被映射校验拦截: {out}"
        phase("科目三③第一级拒绝", f"映射校验指名 '{{{ADD_KEY}}}' 无映射，启动即炸")

        # 第二级拒绝：即便运维乱填一个不存在的字段 → 双层校验第②层报"代码未声明"
        # ——情形 C 的正解：新键需要新计算逻辑，属人工开发，绝不静默产空值
        text = YAML_FILE.read_text(encoding="utf-8")
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if ln.strip() == "scalars:":
                lines.insert(i + 1, f"  {ADD_KEY}: {ADD_BOGUS_FIELD}")
                break
        drill_yaml.write_text("\n".join(lines) + "\n", encoding="utf-8")
        env = dict(os.environ, PLACEHOLDER_MAP_PATH=str(drill_yaml))
        r = _run(["-c", "import app.mapping"], env=env)
        out = r.stdout + r.stderr
        assert r.returncode != 0 and "代码未声明" in out and ADD_BOGUS_FIELD in out, \
            f"假字段未被第②层对账拦截: {out}"
        phase("科目三④第二级拒绝",
              "YAML 乱填字段被'YAML 值==代码声明'对账拦截——情形 C 必须补代码，"
              "系统算不了的数进不了报告")


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    drill_rename()
    drill_delete()
    drill_add()

    print("\n===== 消防演习计时（三科目） =====")
    for name, sec, note in _TIMINGS:
        print(f"  {sec:6.1f}s  {name}  {note}")
    print(f"全程 {_TIMINGS[-1][1]:.1f}s（含三次报告实产；与 LLM 无关，纯机械链）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
