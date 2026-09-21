"""板块④ LLM 客户端：OpenAI 兼容协议 + 重试 + 测试用 Mock。

设计要点：
- 手写 httpx 客户端而非依赖 openai SDK：协议就是 POST /chat/completions，
  少一层依赖少一类版本断裂（D1 教训）；Kimi/DeepSeek/Qwen 均兼容该协议
- 配置走环境变量：LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，不入库不入库不入库
- MockLLM 用于离线测试：测试断言的是解析与校验逻辑，不是模型效果
"""
from __future__ import annotations

import os

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


class LLMError(Exception):
    """调用失败或返回不可解析。"""


# ---------- 多模型协作：角色档案表（唯一出处） ----------
# 每角色声明：读哪组环境变量、默认温度、超时、职责说明。
# 小模型角色（classification/polish）优先 LLM_SMALL_* 三件套；
# 未配置时回退主模型，role_actual 如实标注 "main-model-fallback"（不假装用了小模型）。
ROLE_PROFILES: dict[str, dict] = {
    "generation":    {"env": ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"),
                      "temperature": 0.2, "timeout": 60.0,
                      "duty": "报告/归因长文生成（主模型，DeepSeek 级）"},
    "classification": {"env": ("LLM_SMALL_BASE_URL", "LLM_SMALL_API_KEY", "LLM_SMALL_MODEL"),
                       "fallback": ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"),
                       "temperature": 0.0, "timeout": 30.0,
                       "duty": "意图分类（Qwen-7B 级小模型，确定性优先）"},
    "polish":        {"env": ("LLM_SMALL_BASE_URL", "LLM_SMALL_API_KEY", "LLM_SMALL_MODEL"),
                      "fallback": ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"),
                      "temperature": 0.3, "timeout": 30.0,
                      "duty": "整改任务文本润色（小模型，风格任务）"},
}


class LLMClient:
    """OpenAI 兼容 chat completions 客户端，按 role 读角色档案路由模型。

    role_actual 取值：main（主模型）/ small-model（小模型端点）/
    main-model-fallback（小模型未配置，如实回退）——上游响应应原样透出。"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float | None = None,
                 role: str = "generation"):
        if role not in ROLE_PROFILES:
            raise LLMError(f"未知 role: {role}（可选: {sorted(ROLE_PROFILES)}）")
        profile = ROLE_PROFILES[role]
        env = os.environ

        def _read(keys) -> tuple[str, str, str]:
            return (env.get(keys[0], "").rstrip("/"), env.get(keys[1], ""),
                    env.get(keys[2], ""))

        b, k, m = _read(profile["env"])
        if all((b, k, m)):
            self.role_actual = "main" if "fallback" not in profile else "small-model"
        elif "fallback" in profile:
            b, k, m = _read(profile["fallback"])
            self.role_actual = "main-model-fallback"
        else:
            self.role_actual = "main"
        # 显式传参优先于环境变量（测试/特殊调用）
        self.base_url = (base_url or b).rstrip("/")
        self.api_key = api_key or k
        self.model = model or m
        if not (self.base_url and self.api_key and self.model):
            raise LLMError(f"LLM 未配置（role={role}）：请设置 "
                           f"{' / '.join(profile['env'])}"
                           + ("，或回退 " + " / ".join(profile["fallback"])
                              if "fallback" in profile else ""))
        self.temperature = profile["temperature"]
        self.timeout = timeout or profile["timeout"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20),
           reraise=True)
    def chat(self, messages: list[dict], temperature: float | None = None,
             json_mode: bool = False) -> str:
        """返回 content 文本；三次指数退避后仍失败则抛 LLMError。

        temperature 缺省时取角色档案值（分类 0.0 / 生成 0.2 / 润色 0.3），
        调用方显式传参优先。json_mode=True 时携带 response_format=json_object
        （OpenAI 兼容扩展，DeepSeek/Kimi/Qwen 支持；不识别的自部署端点会 400——
        此时调用方应关掉）。实测动因：DeepSeek 实弹首发即返回语法破损 JSON
        致解析崩溃（开发日志09）。"""
        payload: dict = {"model": self.model, "messages": messages,
                         "temperature": self.temperature if temperature is None
                         else temperature}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = httpx.post(f"{self.base_url}/chat/completions",
                           headers={"Authorization": f"Bearer {self.api_key}"},
                           json=payload,
                           timeout=self.timeout)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"LLM 调用失败: {e}") from e


class MockLLM:
    """测试桩：返回预置文本，记录收到的消息供断言。
    canned 传 list 时按调用次序依次返回（末条之后重复末条）——用于"首发坏 JSON、
    重试修好"这类剧本；json_mode 形参仅做签名兼容，不影响行为。"""

    def __init__(self, canned: "str | list[str]"):
        self.canned = canned
        self.received: list[dict] = []
        self.calls = 0

    def chat(self, messages: list[dict], temperature: float = 0.2,
             json_mode: bool = False) -> str:
        self.received = messages
        self.calls += 1
        if isinstance(self.canned, list):
            return self.canned[min(self.calls - 1, len(self.canned) - 1)]
        return self.canned
