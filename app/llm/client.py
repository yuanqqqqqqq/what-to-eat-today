# -*- coding: utf-8 -*-
"""
LLM 客户端：OpenAI 兼容接口（DeepSeek/GLM/Qwen/Moonshot/Ollama 通用）
BYOK：用户填 base_url + api_key + model，本文件不内置任何 Key。
"""
import httpx


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""

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
        """非流式对话，返回文本内容。"""
        if not self.available:
            raise RuntimeError("LLM 未配置：请先填写 base_url / api_key / model")
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
        resp = httpx.post(url, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise RuntimeError(f"LLM 返回格式异常: {str(data)[:200]}")
