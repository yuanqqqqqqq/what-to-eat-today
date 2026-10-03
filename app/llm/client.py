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

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

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
