"""板块3 报告生成测试：注册表漂移 / 上下文覆盖 / 渲染产物体检 / 校验闭环 / API。"""
import subprocess
import sys
from pathlib import Path

import docx
import pytest

from app.compute import CostCalculator
from app.ingest import init_store
from app.render import TEMPLATE, build_report
from app.report_data import ReportContextBuilder
from app.report_gen import _template_sections, generate_report_sections
from app.report_registry import (DYNAMIC_TABLE_PLACEHOLDERS,
                                 SCALAR_PLACEHOLDERS,
                                 TEXT_SECTION_PLACEHOLDERS)
from app.retrieve import Retriever

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def calc():
    store, _ = init_store()
    return CostCalculator(store)


def test_registry_covers_template():
    """漂移检测：注册表必须与官方模板实测占位符一致（模板改版即报警）。
    提取逻辑与 scripts/extract_placeholders.py 同源（app.template_scan）。"""
    from app.template_scan import extract_placeholders
    all_ph = extract_placeholders(TEMPLATE)["all"]
    assert len(all_ph) == 101
    assert all_ph == SCALAR_PLACEHOLDERS | DYNAMIC_TABLE_PLACEHOLDERS \
        | TEXT_SECTION_PLACEHOLDERS


def test_registry_partition_sizes():
    assert len(SCALAR_PLACEHOLDERS) == 89
    assert len(DYNAMIC_TABLE_PLACEHOLDERS) == 6
    assert len(TEXT_SECTION_PLACEHOLDERS) == 6


def test_producer_declarations_match_registry():
    """3.0 生产者驱动：组声明并集 == 注册表（导入时已校验一次，此处文档化复验）。"""
    from app.report_data import _validate_groups
    _validate_groups()


def test_mapping_loads_and_covers_registry():
    """3.2 L1 映射：注册表每个键都能经 YAML（含别名）解析到标准字段。"""
    from app.mapping import MAPPING
    for k in SCALAR_PLACEHOLDERS:
        assert MAPPING.field_of(k) is not None, f"{k} 未映射"


def test_mapping_missing_key_raises(tmp_path):
    """负向：YAML 删一个映射 → ImportError 人话指出缺哪个键。"""
    import yaml
    from app.mapping import _DEFAULT_PATH, Mapping
    raw = yaml.safe_load(_DEFAULT_PATH.read_text(encoding="utf-8"))
    del raw["scalars"]["本月产量"]
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ImportError, match="本月产量"):
        Mapping(p)


def test_mapping_alias_resolves_renamed_key(tmp_path):
    """模板改名场景：YAML 只有新名 + 别名归一规则 → 自动适配并留痕警告。"""
    import yaml
    from app.mapping import _DEFAULT_PATH, Mapping
    raw = yaml.safe_load(_DEFAULT_PATH.read_text(encoding="utf-8"))
    raw["scalars"].pop("本月产量")
    raw["scalars"]["当月产量"] = "output.current"
    raw.setdefault("aliases", []).append(
        {"pattern": "^本月", "replace": "当月"})
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    m = Mapping(p)
    assert m.field_of("当月产量") == "output.current"
    assert m.auto_aliased == {"本月产量": "当月产量"}
    assert any("别名归一命中" in str(w) for w in m.warnings)


def test_mapping_structure_validation_catches_misshapen_yaml(tmp_path):
    """防手抖：scalars 节写成列表 / 别名正则编译失败 → 报人话'结构校验失败'，
    不是 KeyError 天书。"""
    import yaml
    from app.mapping import _DEFAULT_PATH, Mapping
    raw = yaml.safe_load(_DEFAULT_PATH.read_text(encoding="utf-8"))
    bad = dict(raw)
    bad["scalars"] = ["本月产量", "上月产量"]
    p1 = tmp_path / "bad1.yaml"
    p1.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ImportError, match="结构校验失败"):
        Mapping(p1)
    bad2 = dict(raw)
    bad2["aliases"] = [{"pattern": "^(?u", "replace": "当月"}]
    p2 = tmp_path / "bad2.yaml"
    p2.write_text(yaml.safe_dump(bad2, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ImportError, match="正则编译失败"):
        Mapping(p2)


def test_runtime_group_reconciliation_catches_silent_drift(calc, monkeypatch):
    """缺点一核心防线：声明 provides 还在、函数体却少产出一个键 →
    import 校验全绿也救不了，必须运行期逐组对账当场炸并指名道姓。"""
    import app.report_data as report_data
    g = report_data._SCALAR_GROUPS[0]

    def lying_fn(bundle):
        d = g.fn(bundle)
        d.pop("report.date", None)
        return d

    monkeypatch.setattr(report_data, "_SCALAR_GROUPS",
                        (report_data._Group(name=g.name, provides=g.provides,
                                            fn=lying_fn, extras=g.extras),)
                        + report_data._SCALAR_GROUPS[1:])
    with pytest.raises(AssertionError, match="产出字段集与声明不符"):
        ReportContextBuilder(calc).build("银黄口服液", "2026-05")


def test_validate_groups_catches_missing_key():
    """负向：故意删一个声明键 → ImportError 并指出缺哪个键。"""
    import app.report_data as report_data
    g = report_data._SCALAR_GROUPS[0]
    broken = report_data._Group(name=g.name, provides=g.provides[:-1],
                                fn=g.fn, extras=g.extras)
    with pytest.raises(ImportError, match="缺"):
        report_data._validate_groups(
            scalar_groups=[broken] + list(report_data._SCALAR_GROUPS[1:]))


def test_validate_groups_catches_duplicate_claim():
    """负向：两组抢同一个键 → ImportError 并指出争抢。"""
    import app.report_data as report_data
    g0 = report_data._SCALAR_GROUPS[0]
    thief = report_data._Group(name="抢键组", provides=(g0.provides[0],),
                               fn=g0.fn, extras=())
    with pytest.raises(ImportError, match="争抢"):
        report_data._validate_groups(
            scalar_groups=[thief] + list(report_data._SCALAR_GROUPS))


def test_context_coverage_and_values(calc):
    """101 占位符全覆盖（_assert_coverage 内置）+ 关键数值与计算层对账。"""
    ctx = ReportContextBuilder(calc).build("银黄口服液", "2026-05")
    assert ctx["本月单位成本"] == 11.21          # 与 test_compute 同锚点
    assert ctx["去年同月产量"] == 55100
    assert ctx["材料金额"] == 7.3
    # 成本结构占比闭合：三要素占比之和 ≈ 100（±0.2 舍入容差）
    total_pct = ctx["材料占比"] + ctx["人工占比"] + ctx["制造费用占比"]
    assert abs(total_pct - 100) <= 0.2
    # 动态表行数与数据层一致（行数从库实测，不硬编码）
    n_mats = calc.store.query(
        'SELECT COUNT(*) AS n FROM materials WHERE 产品名称=? AND 月份=?',
        ("银黄口服液", "2026-05")).iloc[0]["n"]
    assert len(ctx["__rows__原材料成本明细表格"]) == n_mats
    # 趋势表：2025-12 是数据空洞月（诚实跳过不编造），2026-05 报告得 5 行；
    # 2026-06 报告恰好 6 个连续月全有数据
    assert len(ctx["__rows__近6个月成本趋势表格"]) == 5
    ctx6 = ReportContextBuilder(calc).build("银黄口服液", "2026-06")
    assert len(ctx6["__rows__近6个月成本趋势表格"]) == 6
    # 整改任务：告警月份有任务，无告警月份为"无任务"占位行
    assert ctx["__rows__整改任务表格"][0][0].startswith("ZG-2026-05")


def test_template_sections_pass_verification(calc):
    """模板句兜底：代码生成的句子必须能通过自己的校验器（零幻觉设计自证）。"""
    from app.mapping import MAPPING
    from app.report_gen import SECTION_FIELDS
    metrics = calc.metrics("银黄口服液", "2026-05")
    diff = calc.benchmark("银黄口服液", "2026-05")
    sections = _template_sections(metrics, diff, calc)
    assert set(sections) == SECTION_FIELDS
    # L1 翻译：六个字段必须能全部映射回模板键
    assert set(MAPPING.section_context(sections)) == TEXT_SECTION_PLACEHOLDERS
    for s in sections.values():
        assert s.source == "模板句·LLM未配置"
        assert s.text  # 无空段


@pytest.fixture(scope="module")
def built_report(tmp_path_factory):
    store, _ = init_store()
    calc = CostCalculator(store)
    out = tmp_path_factory.mktemp("reports")
    return build_report(calc, Retriever(), None, "银黄口服液", "2026-05", out)


def test_render_product_integrity(built_report):
    """渲染产物体检：无残留占位符/哨兵、15 表（9+6）、2 嵌图、校验非 rejected。"""
    assert built_report["verification"]["verdict"] != "rejected"
    d = docx.Document(built_report["docx"])
    full = "\n".join(p.text for p in d.paragraphs)
    assert "{{" not in full and "}}" not in full
    assert "@@TBL" not in full
    tbl_text = "\n".join(c.text for t in d.tables for r in t.rows for c in r.cells)
    assert "{{" not in tbl_text and "@@TBL" not in tbl_text
    assert len(d.tables) == 15          # 模板原有 9 表 + 动态插入 6 表
    assert len(d.inline_shapes) == 2    # 趋势图 + 结构图
    # 无 LLM 时来源标注必须保留在报告里（降级透明）
    assert any("模板句·LLM未配置" in p.text for p in d.paragraphs) or \
        any("模板句·LLM未配置" in c.text
            for t in d.tables for r in t.rows for c in r.cells)
    # 动态表表头来自代码契约
    assert any("原材料名称" in c.text for c in d.tables[0].rows[0].cells) or \
        any("原材料名称" in c.text for t in d.tables for c in t.rows[0].cells)
    assert any("任务编号" in c.text for t in d.tables for c in t.rows[0].cells)


def test_llm_track_with_mock(calc):
    """LLM 轨：MockLLM 优质输出走完整校验闭环；sections 来源标 llm。"""
    import json
    from app.llm import MockLLM
    metrics = calc.metrics("银黄口服液", "2026-05")
    mat = metrics.elements["直接材料"]
    secs = {name: {"text": f"直接材料 {mat.current} 元/盒，环比 {mat.mom_pct:+.1f}%。",
                   "figures": [mat.current, mat.mom_pct], "citations": []}
            for name in ("section.material_attribution", "section.anomaly",
                         "section.diff_structure", "section.diff_attribution",
                         "section.highlights", "section.concerns")}
    canned = json.dumps({"sections": secs,
                         "suggestions": ["核查金银花采购合同调价条款"],
                         "suggestion_figures": []}, ensure_ascii=False)
    sections, suggestions, v = generate_report_sections(
        calc, Retriever(), MockLLM(canned), "银黄口服液", "2026-05")
    assert v["verdict"] in ("pass", "auto_fixed")
    assert all(s.source == "llm" for s in sections.values())
    assert suggestions == ["核查金银花采购合同调价条款"]


def test_llm_fabrication_rejected(calc):
    """编造数字必须被拦截（白名单含舍入变体后仍守得住）。"""
    import json
    from app.llm import MockLLM
    secs = {name: {"text": "成本 999.9 元/盒。", "figures": [999.9],
                   "citations": []}
            for name in ("section.material_attribution", "section.anomaly",
                         "section.diff_structure", "section.diff_attribution",
                         "section.highlights", "section.concerns")}
    canned = json.dumps({"sections": secs, "suggestions": [],
                         "suggestion_figures": []}, ensure_ascii=False)
    sections, suggestions, v = generate_report_sections(
        calc, Retriever(), MockLLM(canned), "银黄口服液", "2026-05")
    assert v["verdict"] == "rejected"
    assert v.get("retried") is True
    assert v["errors"]
    assert any("999.9" in e for e in v["errors"])
    # 两轮不过：LLM 文本被拦截，降级模板句并如实标注
    assert all(s.source == "模板句·LLM被拦截" for s in sections.values())
    assert v.get("llm_rejected_fallback") or v.get("fallback") == "template_sections"


def test_llm_invalid_json_falls_back_to_template(calc):
    """D19 回归：两轮均不可解析 → 降级模板句并如实标注，不崩溃、不缺段。"""
    from app.llm import MockLLM
    sections, suggestions, v = generate_report_sections(
        calc, Retriever(), MockLLM("模型崩溃输出的自由文本，不是 JSON"),
        "银黄口服液", "2026-05")
    assert v.get("llm_parse_failed") is True
    assert v.get("fallback") == "template_sections"
    assert len(sections) == 6
    assert all(s.text for s in sections.values())
    assert suggestions


# ---------- PDF 转换稳定性（四层：重试/超时/守望者/收尾） ----------

class _FakeProc:
    """Popen 假身：按脚本演出——即死（带 stderr）/ 成功 / 赖着不退 / 永远卡死。"""
    def __init__(self, behavior: str, pdf: Path, err: bytes = b""):
        self.behavior, self.pdf, self.pid = behavior, pdf, 99999
        self.stderr = type("S", (), {"read": lambda self: err})()
        if behavior in ("success", "hang"):
            pdf.write_bytes(b"%PDF-1.4 fake")
        self._rc = {"success": 0, "dead": 1}.get(behavior)

    def poll(self):
        return self._rc


def _patch_popen(monkeypatch, render, scripts, pdf):
    """scripts: (行为, stderr) 队列，每次 Popen 取下一个；返回调用计数。"""
    n = [0]

    def fake_popen(cmd, **_kw):
        behavior, err = scripts[min(n[0], len(scripts) - 1)]
        n[0] += 1
        return _FakeProc(behavior, pdf, err)

    monkeypatch.setattr(render.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(render, "find_soffice", lambda: "/fake/soffice.com")
    monkeypatch.setattr(render, "_kill_tree", lambda proc: None)
    return n


def test_render_pdf_retries_once_then_succeeds(tmp_path, monkeypatch):
    """瞬时故障（profile 锁）→ 自动重试一次 → 成功留痕；不无限重试。"""
    import app.render as render
    docx_p = tmp_path / "r.docx"
    docx_p.write_text("x", encoding="utf-8")
    pdf = tmp_path / "r.pdf"
    n = _patch_popen(monkeypatch, render,
                     [("dead", b"profile lock detected"), ("success", b"")], pdf)
    log = []
    out, warn = render.render_pdf(docx_p, _log=log, _poll=0.05)
    assert out == pdf
    assert warn is None
    assert n[0] == 2
    assert any("第 1 次尝试失败" in m for m in log)
    assert any("第 2 次尝试成功" in m for m in log)


def test_render_pdf_gives_up_after_two_failures(tmp_path, monkeypatch):
    """两次均超时卡死：强制收尾进程树，如实返回原因，不静默、不无限重试。"""
    import app.render as render
    docx_p = tmp_path / "r.docx"
    docx_p.write_text("x", encoding="utf-8")
    pdf = tmp_path / "r.pdf"
    n = _patch_popen(monkeypatch, render, [("stuck", b"")], pdf)
    killed = []
    monkeypatch.setattr(render, "_kill_tree", lambda proc: killed.append(proc.pid))
    out, warn = render.render_pdf(docx_p, _timeout=0.3, _poll=0.05)
    assert out is None
    assert "两次均失败" in warn
    assert "超时" in warn
    assert n[0] == 2
    assert len(killed) == 2


def test_render_pdf_deterministic_failure_no_retry(tmp_path, monkeypatch):
    """确定性故障（非瞬时签名）：立即报错不重试——重试救不了的病不浪费时间。"""
    import app.render as render
    docx_p = tmp_path / "r.docx"
    docx_p.write_text("x", encoding="utf-8")
    pdf = tmp_path / "r.pdf"
    n = _patch_popen(monkeypatch, render,
                     [("dead", b"source file corrupt")], pdf)
    log = []
    out, warn = render.render_pdf(docx_p, _log=log, _poll=0.05)
    assert out is None
    assert "确定性故障" in warn
    assert n[0] == 1


def test_render_pdf_watcher_early_success(tmp_path, monkeypatch):
    """②号冤案平反：PDF 已转完但进程赖着不退 → 守望者确认产物即成功，
    主动收尾进程，不吃满超时。"""
    import time
    import app.render as render
    docx_p = tmp_path / "r.docx"
    docx_p.write_text("x", encoding="utf-8")
    pdf = tmp_path / "r.pdf"
    n = _patch_popen(monkeypatch, render, [("hang", b"")], pdf)
    killed = []
    monkeypatch.setattr(render, "_kill_tree", lambda proc: killed.append(proc.pid))
    t0 = time.monotonic()
    out, warn = render.render_pdf(docx_p, _timeout=30, _poll=0.05)
    elapsed = time.monotonic() - t0
    assert out == pdf
    assert warn is None
    assert n[0] == 1
    assert killed == [99999]
    assert elapsed < 5


def test_api_report_endpoint():
    from fastapi.testclient import TestClient
    from app.api import app
    c = TestClient(app)
    r = c.post("/api/report", json={"product": "板蓝根颗粒", "month": "2026-05"})
    assert r.status_code == 200
    body = r.json()
    assert body["docx"].endswith(".docx")
    assert Path(body["docx"]).exists()
    assert body["verification"]["verdict"] != "rejected"
    assert isinstance(body["warnings"], list)
    r2 = c.post("/api/report", json={"product": "不存在", "month": "2026-05"})
    assert r2.status_code == 404


# ---------- 季度/专题主题（赛题 5.1.3 三主题） ----------

def test_quarter_pack_weighted(calc):
    """季度指标包：单位成本=Σ总成本÷Σ产量（加权），Q1 无上季度环比=None。"""
    pack = calc.quarter_pack("银黄口服液", "Q1")
    assert pack.month == "2026-Q1"
    rows = [calc.store.summary("银黄口服液", m)
            for m in ("2026-01", "2026-02", "2026-03")]
    qty = sum(float(r["产量(盒)"]) for r in rows)
    total = sum(float(r["总成本(元)"]) for r in rows)
    assert pack.output_qty == int(qty)
    assert abs(pack.total_cost - total) < 0.01
    assert abs(pack.unit_cost - round(total / qty, 2)) < 0.011
    # Q1 是上季起点：环比/预算偏差为 None（显示层"—"），不硬算
    assert pack.unit_cost_mom_pct is None
    assert pack.unit_cost_budget_dev_pct is None


def test_quarter_pack_q2_has_prev(calc):
    """Q2 环比对 Q1 同口径加权值。"""
    pack = calc.quarter_pack("银黄口服液", "Q2")
    assert pack.unit_cost_mom_pct is not None
    q1 = calc.quarter_pack("银黄口服液", "Q1")
    expected = (pack.unit_cost - q1.unit_cost) / q1.unit_cost * 100
    assert abs(pack.unit_cost_mom_pct - expected) < 0.2  # 双舍入容差


def test_quarter_context_builds(calc):
    """季度主题上下文：101 占位符全覆盖（build 内 _assert_coverage 把关），
    封面词为季度，同比留空。"""
    ctx = ReportContextBuilder(calc).build("银黄口服液", "2026-05",
                                           theme="quarterly", quarter="Q2")
    # 报告标题含季度标签
    title = [v for k, v in ctx.items() if "季度成本分析报告" in str(v)]
    assert title, "季度报告标题未生成"


def test_quarter_theme_rejects_bad_quarter(calc):
    with pytest.raises(ValueError, match="Q1/Q2"):
        ReportContextBuilder(calc).build("银黄口服液", "2026-05",
                                         theme="quarterly", quarter="Q3")


def test_quarter_sections_template_fallback(calc):
    """季度主题无 LLM 兜底：措辞用'本季度'，校验不自 rejected。"""
    sections, suggestions, v = generate_report_sections(
        calc, Retriever(), None, "银黄口服液", "2026-06",
        theme="quarterly", quarter="Q2")
    assert v["verdict"] != "rejected"
    assert any("本季度" in s.text or "本季" in s.text
               for s in sections.values() if s.text)


def test_quarter_report_render(tmp_path, calc):
    """季度报告端到端渲染：docx 产出、无占位符残留、文件名带季度锚点。"""
    out = build_report(calc, Retriever(), None, "银黄口服液", "2026-06",
                       tmp_path, theme="quarterly", quarter="Q2")
    assert "2026-Q2" in out["docx"] and "季度" in out["docx"]
    d = docx.Document(out["docx"])
    full = "\n".join(p.text for p in d.paragraphs)
    assert "{{" not in full and "}}" not in full
