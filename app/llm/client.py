# -*- coding: utf-8 -*-
"""
LLM 客户端：OpenAI 兼容接口（DeepSeek/GLM/Qwen/Moonshot/Ollama 通用）
BYOK：用户填 base_url + api_key + model，本文件不内置任何 Key。

设计原则：LLM 只负责"表达"（搭配说明、简化做法、自然语言解释）。
过敏判断、硬约束过滤、预算/热量/用量计算一律由规则代码负责，绝不交给 LLM。
所有调用都可能失败，调用方必须准备好模板兜底。
"""
import httpx

# 交互式请求的默认超时：宁可退回模板，也不要让用户干等 90 秒
DEFAULT_TIMEOUT = 30.0


class LLMError(RuntimeError):
    """LLM 调用失败。message 里不会包含 API Key。"""


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.timeout = float(timeout or DEFAULT_TIMEOUT)

    def is_ollama(self) -> bool:
        """是否为本地 Ollama（无需 api_key）。"""
        return "ollama" in self.base_url.lower() or ":11434" in self.base_url

    @property
    def available(self) -> bool:
        if not (self.base_url and self.model):
            return False
        # 本地 Ollama 不需要 api_key
        if self.is_ollama():
            return True
        return bool(self.api_key)

    def list_models(self) -> list:
        """列出可用模型。仅本地 Ollama 支持（/api/tags），其它返回空列表。"""
        if not self.base_url or not self.is_ollama():
            return []
        try:
            root = self.base_url.split("/v1")[0] if "/v1" in self.base_url else self.base_url
            resp = httpx.get(f"{root}/api/tags", timeout=10)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return [m.get("name") or m.get("model") for m in models if m]
        except Exception:
            return []

    def chat(self, messages: list, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        """非流式对话，返回文本内容。失败抛 LLMError（不含 Key）。"""
        if not self.available:
            raise LLMError("LLM 未配置：请先填写 base_url / api_key / model")
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.TimeoutException:
            raise LLMError(f"LLM 请求超时（{self.timeout:.0f} 秒）")
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            hint = "（检查 API Key / 模型名）" if code in (401, 403, 404) else ""
            raise LLMError(f"LLM 接口返回 {code}{hint}")
        except httpx.HTTPError as e:
            # 只保留异常类型与目标主机，不带出 header/Key
            raise LLMError(f"LLM 请求失败：{type(e).__name__}")

        try:
            data = resp.json()
        except ValueError:
            raise LLMError("LLM 返回的不是合法 JSON")
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("LLM 返回格式异常（缺少 choices[0].message.content）")
