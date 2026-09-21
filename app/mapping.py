"""L1 占位符映射（模板自适应方案 3.2）：模板键名 → 内部标准字段，外置 YAML。

- 代码内只认标准字段 id（report.title / material.cost.current / rows.* / section.*）
- config/placeholder_map.yaml 承载映射 + 别名归一规则（模板改名先归一再查表）
- 导入时双层校验（MAPPING 单例在模块底部实例化，启动即炸，报错写人话）：
  ① YAML 键（含别名命中）必须覆盖注册表全部键；缺键列出清单等人工补映射
  ② YAML 值必须等于代码声明的标准字段（report_data / report_gen 的声明集）
"""
from __future__ import annotations

import re
import os
from pathlib import Path

import yaml

from .report_registry import (DYNAMIC_TABLE_PLACEHOLDERS, SCALAR_PLACEHOLDERS,
                              TEXT_SECTION_PLACEHOLDERS)

# 映射文件路径可用 PLACEHOLDER_MAP_PATH 覆盖（消防演习/多模板场景）
_DEFAULT_PATH = Path(os.environ["PLACEHOLDER_MAP_PATH"]) \
    if os.environ.get("PLACEHOLDER_MAP_PATH") else \
    Path(__file__).resolve().parent.parent / "config" / "placeholder_map.yaml"


class Mapping:
    """占位符映射单例：加载 → 别名归一 → 双层校验 → 提供翻译。"""

    def __init__(self, path: Path | None = None):
        self.path = path or _DEFAULT_PATH
        with self.path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self._validate_structure(raw)   # 先查"写没写歪"，再查"对不对账"
        self.scalars: dict[str, str] = dict(raw.get("scalars") or {})
        self.dynamic_tables: dict[str, str] = dict(raw.get("dynamic_tables") or {})
        self.text_sections: dict[str, str] = dict(raw.get("text_sections") or {})
        self.alias_rules = [(re.compile(a["pattern"]), a["replace"])
                            for a in (raw.get("aliases") or [])]
        self.auto_aliased: dict[str, str] = {}   # 模板键 → 别名归一后命中的 YAML 键
        self.warnings: list[str] = []
        self._resolve_aliases()
        self._validate()

    @staticmethod
    def _validate_structure(raw) -> None:
        """结构校验（防手抖）：YAML 结构错误是比赛现场最高发的坑，
        必须在学校门口拦下——报"第 X 节结构错误"，而非 KeyError 天书。"""
        errors: list[str] = []
        if not isinstance(raw, dict):
            raise ImportError(
                "placeholder_map.yaml 结构校验失败：顶层必须是「节: 键值对」的映射，"
                "请检查是否整段缩进错位")
        for sec in ("scalars", "dynamic_tables", "text_sections"):
            v = raw.get(sec)
            if v is None:
                continue                # 空节由语义校验（双层对账）报缺映射
            if not isinstance(v, dict) or not all(
                    isinstance(k, str) and isinstance(val, str)
                    for k, val in v.items()):
                errors.append(
                    f"{sec} 节必须是「模板键: 标准字段」的键值对，"
                    "请检查缩进与冒号（常见：多了一层嵌套或值写成列表）")
        aliases = raw.get("aliases")
        if aliases is not None:
            if not isinstance(aliases, list):
                errors.append("aliases 节必须是列表（每条含 pattern 与 replace）")
            else:
                for i, a in enumerate(aliases, 1):
                    if not isinstance(a, dict) or "pattern" not in a \
                            or "replace" not in a:
                        errors.append(f"aliases 第 {i} 条必须含 pattern 与 replace 两键")
                    else:
                        try:
                            re.compile(a["pattern"])
                        except re.error as e:
                            errors.append(f"aliases 第 {i} 条 pattern 正则编译失败: {e}")
        if errors:
            raise ImportError("placeholder_map.yaml 结构校验失败：\n- "
                              + "\n- ".join(errors))

    def _print_warnings(self) -> None:
        for w in self.warnings:
            print(f"[placeholder_map] 警告: {w}")

    # ---- 别名归一：模板改了名的键，按规则归一到 YAML 既有键 ----
    def _resolve_aliases(self) -> None:
        for key in sorted(set(SCALAR_PLACEHOLDERS) - set(self.scalars)):
            for pat, rep in self.alias_rules:
                cand = pat.sub(rep, key, count=1)
                if cand != key and cand in self.scalars:
                    self.auto_aliased[key] = cand
                    break

    def field_of(self, template_key: str) -> str | None:
        """标量模板键 → 标准字段（含别名命中）；无映射返回 None。"""
        if template_key in self.scalars:
            return self.scalars[template_key]
        hit = self.auto_aliased.get(template_key)
        return self.scalars[hit] if hit else None

    # ---- 双层校验 ----
    def _validate(self) -> None:
        from .report_data import ALL_ROW_FIELDS, ALL_SCALAR_FIELDS
        from .report_gen import SECTION_FIELDS
        errors: list[str] = []

        # ① 键覆盖（人话报错：告诉运维补哪几个键）
        missing = sorted(k for k in SCALAR_PLACEHOLDERS if self.field_of(k) is None)
        if missing:
            errors.append(
                "以下模板键在 placeholder_map.yaml 没有映射，请在 scalars 节补充"
                "（或在 aliases 节加归一规则）: " + "、".join(missing))
        stale = sorted(set(self.scalars) - SCALAR_PLACEHOLDERS
                       - set(self.auto_aliased.values()))
        if stale:
            self.warnings.append("YAML 中存在模板已不用的键（可清理）: " + "、".join(stale))
        for name, table, reg in (("dynamic_tables", self.dynamic_tables,
                                  DYNAMIC_TABLE_PLACEHOLDERS),
                                 ("text_sections", self.text_sections,
                                  TEXT_SECTION_PLACEHOLDERS)):
            miss = sorted(set(reg) - set(table))
            if miss:
                errors.append(f"{name} 节缺映射: " + "、".join(miss))
            extra = sorted(set(table) - set(reg))
            if extra:
                self.warnings.append(f"{name} 节存在模板已不用的键: " + "、".join(extra))

        # ② 值 == 代码声明的标准字段
        used = {self.field_of(k) for k in SCALAR_PLACEHOLDERS}
        used.discard(None)
        if used != set(ALL_SCALAR_FIELDS):
            errors.append(
                "标准字段对不上账：代码声明了但 YAML 未引用 "
                f"{sorted(set(ALL_SCALAR_FIELDS) - used)}；"
                f"YAML 引用但代码未声明 {sorted(used - set(ALL_SCALAR_FIELDS))}")
        if set(self.dynamic_tables.values()) != set(ALL_ROW_FIELDS):
            errors.append(
                "动态表字段对不上账：代码声明 "
                f"{sorted(set(ALL_ROW_FIELDS) - set(self.dynamic_tables.values()))} 未被引用；"
                f"YAML 引用但未声明 "
                f"{sorted(set(self.dynamic_tables.values()) - set(ALL_ROW_FIELDS))}")
        if set(self.text_sections.values()) != set(SECTION_FIELDS):
            errors.append(
                "文本段字段对不上账：代码声明 "
                f"{sorted(set(SECTION_FIELDS) - set(self.text_sections.values()))} 未被引用；"
                f"YAML 引用但未声明 "
                f"{sorted(set(self.text_sections.values()) - set(SECTION_FIELDS))}")

        if self.auto_aliased:
            self.warnings.append(
                "别名归一命中（模板改名已自动适配，建议固化进 YAML）: "
                + "、".join(f"{k}→{v}" for k, v in sorted(self.auto_aliased.items())))
        self._print_warnings()   # 警告先于爆炸留痕：校验失败时别名命中证据不丢
        if errors:
            raise ImportError("placeholder_map.yaml 校验失败：\n- " + "\n- ".join(errors))

    # ---- 翻译：标准字段值 → docxtpl context（模板键） ----
    def scalar_context(self, values: dict) -> dict:
        ctx = {}
        for k in SCALAR_PLACEHOLDERS:
            ctx[k] = values[self.field_of(k)]
        for tpl, f in self.dynamic_tables.items():
            ctx[f"__rows__{tpl}"] = values[f]
        return ctx

    def section_context(self, sections: dict) -> dict:
        """report_gen 产出的标准字段 sections → 模板键 sections（渲染用）。"""
        return {tpl: sections[f] for tpl, f in self.text_sections.items() if f in sections}


MAPPING = Mapping()   # ← import 即双层校验：映射缺失/对不上账在此刻爆炸
