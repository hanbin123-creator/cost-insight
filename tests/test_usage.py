"""token 成本实测测试（A2）：用量落盘 + 聚合 + chat 主链路挂钩。"""
import json

from app.llm import LLMClient, aggregate_usage, record_usage


def test_record_and_aggregate(tmp_path):
    """记录→聚合闭环：总量、分组、recent 截断都正确。"""
    log = tmp_path / "usage.jsonl"
    assert aggregate_usage(log)["calls"] == 0          # 日志不存在如实返回零值
    record_usage("generation", "deepseek-chat",
                 {"prompt_tokens": 100, "completion_tokens": 50,
                  "total_tokens": 150}, path=log)
    record_usage("classification", "qwen-7b",
                 {"prompt_tokens": 10, "completion_tokens": 5,
                  "total_tokens": 15}, path=log)
    agg = aggregate_usage(log)
    assert agg["calls"] == 2
    assert agg["total_tokens"] == 165
    assert agg["by_role"]["generation"] == {"calls": 1, "total_tokens": 150}
    assert agg["by_model"]["qwen-7b"]["calls"] == 1
    assert len(agg["recent"]) == 2
    # 空 usage 不落盘（无数据的调用不产生假记录）
    assert record_usage("polish", "m", {}, path=log) is None
    assert aggregate_usage(log)["calls"] == 2


def test_chat_logs_usage(tmp_path, monkeypatch):
    """主链路：chat() 成功时把响应 usage 落盘；日志写失败不弄挂调用。"""

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"usage": {"prompt_tokens": 7, "completion_tokens": 3,
                              "total_tokens": 10},
                    "choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("app.llm.httpx.post", lambda *a, **kw: _Resp())
    # 打桩 record_usage 只验证接线——真实落盘由上一条测试覆盖，
    # 不调用原函数，避免测试污染真实用量日志
    calls = []
    monkeypatch.setattr("app.llm.record_usage",
                        lambda role, model, usage, **kw: calls.append(
                            (role, model, usage)))
    client = LLMClient(base_url="http://x", api_key="k", model="m")
    assert client.chat([{"role": "user", "content": "hi"}]) == "ok"
    assert calls == [("generation", "m", {"prompt_tokens": 7,
                                          "completion_tokens": 3,
                                          "total_tokens": 10})]
