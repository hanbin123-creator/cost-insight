"""板块④ 生成层测试：声明制对账的正例与负例（幻觉检测）。"""
import json

import pytest

from app import prompts
from app.compute import CostCalculator
from app.generate import (generate_attribution, parse_report, verify_report,
                          _numbers_in_text, _numbers_with_units)
from app.ingest import init_store
from app.llm import LLMClient, LLMError, MockLLM
from app.retrieve import Retriever


@pytest.fixture(scope="module")
def env():
    store, _ = init_store()
    return CostCalculator(store), Retriever()


def _good_canned(calc, retriever, product="银黄口服液", month="2026-05"):
    """用真实产物包动态构造"模型优质输出"，保证正例永远自洽。"""
    metrics = calc.metrics(product, month)
    knowledge = retriever.multi_search(
        prompts.build_queries(product, month, metrics), top_k=6)
    mat = metrics.elements["直接材料"]
    hit = knowledge.hits[0]
    canned = {
        "summary": f"本月单位成本 {metrics.unit_cost} 元/盒，环比 {metrics.unit_cost_mom_pct}%。",
        "causes": [{
            "title": "材料成本上涨",
            "detail": (f"直接材料 {mat.current} 元/盒，环比 {mat.mom_pct}%，"
                       f"贡献度 {mat.contribution_pct}%。配方含金银花，"
                       f"见《{hit.doc_name}》p{hit.page}"),
            "figures": [metrics.unit_cost, metrics.unit_cost_mom_pct,
                        mat.current, mat.mom_pct, mat.contribution_pct],
            "citations": [hit.chunk_id],
        }],
        "suggestions": ["关注金银花行情，适时锁价备货"],
    }
    return json.dumps(canned, ensure_ascii=False), metrics, knowledge


def test_generate_happy_path(env):
    calc, retriever = env
    canned, _, _ = _good_canned(calc, retriever)
    report = generate_attribution(calc, retriever, MockLLM(canned),
                                  "银黄口服液", "2026-05")
    assert report.verification["passed"], report.verification["errors"]
    assert report.causes and report.suggestions


def test_decomposition_backfilled_by_code(env):
    """表格化归因（排版选型方案一）：分解明细由代码随报告回填，
    与指标包同源；模型输出里塞同名字段一律丢弃，永不采信。"""
    calc, retriever = env
    canned, metrics, _ = _good_canned(calc, retriever)
    # 模型试图在 JSON 里注入伪造分解表
    injected = json.loads(canned)
    injected["decomposition"] = [{"material": "假材料", "price_effect": 99.9}]
    report = generate_attribution(calc, retriever,
                                  MockLLM(json.dumps(injected, ensure_ascii=False)),
                                  "银黄口服液", "2026-05")
    assert report.decomposition == metrics.decomposition   # 代码原值，非注入值
    assert report.decomposition                            # 月度包非空
    assert all(d.material != "假材料" for d in report.decomposition)
    # parse_report 层面同样不采信
    parsed = parse_report(json.dumps(injected), "银黄口服液", "2026-05")
    assert parsed.decomposition == []


def test_fabricated_number_detected(env):
    """负例：模型声明了产物包里不存在的数字 → 判幻觉。"""
    calc, retriever = env
    canned, metrics, knowledge = _good_canned(calc, retriever)
    bad = json.loads(canned)
    bad["causes"][0]["detail"] += " 该材料价格已涨至 99.9 元。"
    bad["causes"][0]["figures"].append(99.9)
    report = parse_report(json.dumps(bad), "银黄口服液", "2026-05")
    v = verify_report(report, metrics, knowledge)
    assert not v["passed"] and any("99.9" in e for e in v["errors"])


def test_undeclared_fabricated_number_detected(env):
    """负例：正文出现未声明且不在产物包的数字 → 判编造（不可自愈）。"""
    calc, retriever = env
    canned, metrics, knowledge = _good_canned(calc, retriever)
    bad = json.loads(canned)
    bad["causes"][0]["detail"] += " 上月为 8.8 元/盒。"   # 8.8 不在白名单
    report = parse_report(json.dumps(bad), "银黄口服液", "2026-05")
    v = verify_report(report, metrics, knowledge)
    assert v["verdict"] == "rejected"
    assert any("未声明且不在产物包中" in e for e in v["errors"])


def test_undeclared_real_number_auto_fixed(env):
    """决策 F 加固：数字真实存在但漏声明 → 自动补全，verdict=auto_fixed 不放行硬错。"""
    calc, retriever = env
    canned, metrics, knowledge = _good_canned(calc, retriever)
    data = json.loads(canned)
    # 总产量在指标包中真实存在，但正文引用且故意不声明
    data["causes"][0]["detail"] += f" 本月产量 {metrics.output_qty} 盒。"
    report = parse_report(json.dumps(data), "银黄口服液", "2026-05")
    v = verify_report(report, metrics, knowledge)
    assert v["verdict"] == "auto_fixed" and v["passed"]
    assert any(str(metrics.output_qty) in f or str(float(metrics.output_qty)) in f
               for f in v["fixed"])
    assert metrics.output_qty in report.causes[0].figures or \
           float(metrics.output_qty) in report.causes[0].figures


class _SequenceMock:
    """第一轮返回坏输出、第二轮返回好输出：测带反馈重试。"""

    def __init__(self, bad: str, good: str):
        self.outputs = [bad, good]
        self.calls: list[list[dict]] = []

    def chat(self, messages, temperature=0.2, json_mode=False):
        self.calls.append(messages)
        return self.outputs[min(len(self.calls) - 1, 1)]


def test_retry_with_feedback_recovers(env):
    """决策 F 加固：首轮编造被拒 → 错误反馈重试 → 第二轮修正后通过。"""
    calc, retriever = env
    good, _, _ = _good_canned(calc, retriever)
    bad_data = json.loads(good)
    bad_data["causes"][0]["detail"] += " 成本暴涨 99.9 元。"
    bad_data["causes"][0]["figures"].append(99.9)
    llm = _SequenceMock(json.dumps(bad_data, ensure_ascii=False), good)
    report = generate_attribution(calc, retriever, llm, "银黄口服液", "2026-05")
    assert report.verification["passed"]
    assert report.verification.get("retried") is True
    assert len(llm.calls) == 2
    # 第二轮消息包含错误反馈与上轮输出
    assert any("未通过系统校验" in m["content"] for m in llm.calls[1]
               if m["role"] == "user")


def test_fabricated_citation_detected(env):
    """负例：编造 chunk_id → 判编造出处。"""
    calc, retriever = env
    canned, metrics, knowledge = _good_canned(calc, retriever)
    bad = json.loads(canned)
    bad["causes"][0]["citations"] = ["不存在的文档#999"]
    report = parse_report(json.dumps(bad), "银黄口服液", "2026-05")
    v = verify_report(report, metrics, knowledge)
    assert not v["passed"] and any("编造出处" in e for e in v["errors"])


def test_prompt_contract(env):
    """Prompt 契约：铁律在场、产物包原文注入、无诱导计算的措辞。"""
    calc, retriever = env
    metrics = calc.metrics("银黄口服液", "2026-05")
    knowledge = retriever.search("金银花", top_k=3)
    msgs = prompts.build_attribution_messages(metrics, knowledge)
    assert "永不计算" in msgs[0]["content"]
    assert "figures" in msgs[1]["content"] and "citations" in msgs[1]["content"]
    assert str(metrics.unit_cost) in msgs[1]["content"]   # 指标包原文注入


def test_build_query_uses_alerts(env):
    """检索查询由分析条件与告警自动构造，非写死关键词。"""
    calc, _ = env
    metrics = calc.metrics("银黄口服液", "2026-05")
    q = prompts.build_query("银黄口服液", "2026-05", metrics)
    assert "银黄口服液" in q and "金银花" in q   # 5 月告警含金银花累计涨幅


def test_build_queries_are_faceted(env):
    """决策 I：分面查询——材料面/要素面/告警面各自定向，且设备面条件触发。"""
    calc, retriever = env
    metrics = calc.metrics("银黄口服液", "2026-05")
    qs = prompts.build_queries("银黄口服液", "2026-05", metrics)
    assert len(qs) >= 3, f"分面不足: {qs}"
    assert any("处方用量" in q for q in qs)          # 材料行情面
    assert any("生产工艺" in q for q in qs)          # 要素异常面
    assert any("市场行情" in q for q in qs)          # 告警面
    # 合并检索：去重 + 多样性保护（同一文档最多 3 块）
    pack = retriever.multi_search(qs, top_k=6)
    assert len(pack.hits) <= 6
    ids = [h.chunk_id for h in pack.hits]
    assert len(ids) == len(set(ids)), "multi_search 未去重"
    from collections import Counter
    assert max(Counter(h.doc_name for h in pack.hits).values()) <= 3


def test_parse_report_tolerates_markdown_fence():
    raw = '```json\n{"summary": "s", "causes": [], "suggestions": []}\n```'
    report = parse_report(raw, "p", "2026-01")
    assert report.summary == "s"


def test_invalid_json_first_then_recovered(env):
    """实弹缺陷 D19 回归：首轮坏 JSON（DeepSeek 实测会产出）视同 rejected
    进反馈重试，第二轮修好即通过——全程不抛异常。"""
    calc, retriever = env
    good, _, _ = _good_canned(calc, retriever)
    broken = good[:-5] + ',,"causes": [}'          # 语法破损（多余逗号+错位括号）
    llm = MockLLM([broken, good])
    report = generate_attribution(calc, retriever, llm, "银黄口服液", "2026-05")
    assert report.verification["passed"]
    assert report.verification.get("retried") is True
    assert llm.calls == 2


def test_invalid_json_twice_returns_failed_not_crash(env):
    """两轮均不可解析：如实返回 passed=False 空报告，系统永不因模型失误崩溃。"""
    calc, retriever = env
    llm = MockLLM("这不是 JSON，是模型崩溃时的自由文本输出")
    report = generate_attribution(calc, retriever, llm, "银黄口服液", "2026-05")
    assert report.verification["passed"] is False
    assert report.verification.get("retried") is True
    assert any("合法 JSON" in e for e in report.verification["errors"])
    assert report.causes == [] and report.summary == ""


def test_number_extraction_exempts_dates():
    assert _numbers_in_text("2026-05 月产量 35000 盒，上涨 10.4%") == [35000.0, 10.4]


def test_number_extraction_exempts_equipment_models():
    """D20 回归：设备型号（NJP-3200/DXDK-40VI）不是数字证据——
    实弹中型号被负号正则捕获（-3200/-40）造成 auto_fixed 噪声。"""
    assert _numbers_in_text("胶囊填充机NJP-3200计量盘磨损，维修费用8,500元") == [8500.0]
    assert _numbers_in_text("颗粒分装机DXDK-40VI切刀磨损，停工8h") == [8.0]


def test_numbers_with_units_marks_money_and_pct():
    """单位标记：元/% 才带 unit=True；天/h/盒等量词整数放行（精度检查不误伤）。"""
    assert _numbers_with_units("停产 2 天，停工 16h，费用 3 元，涨幅 5%") == \
        [(2.0, False), (16.0, False), (3.0, True), (5.0, True)]


def test_precision_loss_detected_with_correct_value(env):
    """两位小数强制：正文"约 11 元"（原值 11.21）→ rejected，
    错误消息直接给出相近原值，反馈重试照抄即收敛。"""
    calc, retriever = env
    _, metrics, knowledge = _good_canned(calc, retriever)
    bad = {"summary": "s",
           "causes": [{"title": "取整引用", "detail": "本月单位成本约 11 元。",
                       "figures": [], "citations": []}],
           "suggestions": []}
    report = parse_report(json.dumps(bad, ensure_ascii=False), "银黄口服液", "2026-05")
    v = verify_report(report, metrics, knowledge)
    assert v["verdict"] == "rejected"
    assert any("精度丢失" in e and "11.21" in e for e in v["errors"])


def test_precision_loss_retry_converges(env):
    """首轮"约 11 元" → 反馈含正确值 → 第二轮改 11.21 收敛通过。"""
    calc, retriever = env
    good, _, _ = _good_canned(calc, retriever)
    bad = json.dumps({"summary": "s",
                      "causes": [{"title": "取整引用", "detail": "本月单位成本约 11 元。",
                                  "figures": [], "citations": []}],
                      "suggestions": []}, ensure_ascii=False)
    llm = MockLLM([bad, good])
    report = generate_attribution(calc, retriever, llm, "银黄口服液", "2026-05")
    assert report.verification["passed"]
    assert report.verification.get("retried") is True


def test_prompt_has_two_decimal_rule():
    """契约：两位小数硬规则在板块2/板块3 提示词同时在场。"""
    from app import report_gen
    for text in (prompts.SYSTEM_PROMPT, report_gen._SYSTEM):
        assert "原值完整引用" in text and "约 11 元" in text


def test_llm_client_requires_config(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(LLMError):
        LLMClient()
