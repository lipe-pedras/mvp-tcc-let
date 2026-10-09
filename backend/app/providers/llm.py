"""LLM provider abstraction. Switch with LLM_PROVIDER=ollama|openai; no code changes."""

import json
from collections.abc import Iterator
from typing import Protocol

import httpx

from app.config import get_settings

Message = dict[str, str]  # {"role": "system"|"user"|"assistant", "content": ...}


class LLMProvider(Protocol):
    model: str

    def stream(self, messages: list[Message]) -> Iterator[str]:
        """Yield the answer in text pieces."""
        ...


class OllamaProvider:
    def __init__(self):
        s = get_settings()
        self.base_url, self.model = s.ollama_url.rstrip("/"), s.llm_model
        self.temperature, self.num_ctx, self.timeout = s.llm_temperature, s.llm_num_ctx, s.llm_timeout

    def stream(self, messages: list[Message]) -> Iterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "think": False,  # reasoning traces would slow answers down and pollute citations
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        }
        with httpx.stream("POST", f"{self.base_url}/api/chat", json=payload, timeout=self.timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                piece = json.loads(line).get("message", {}).get("content", "")
                if piece:
                    yield piece


class OpenAICompatProvider:
    """Any endpoint implementing POST {base_url}/chat/completions (OpenAI, vLLM, LM Studio...)."""

    def __init__(self):
        s = get_settings()
        self.base_url, self.model = s.openai_base_url.rstrip("/"), s.llm_model
        self.api_key, self.temperature, self.timeout = s.openai_api_key, s.llm_temperature, s.llm_timeout

    def stream(self, messages: list[Message]) -> Iterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True, "temperature": self.temperature}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        with httpx.stream(
            "POST", f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                choices = json.loads(data).get("choices") or []
                piece = choices[0].get("delta", {}).get("content") if choices else None
                if piece:
                    yield piece


def get_llm_provider() -> LLMProvider:
    name = get_settings().llm_provider
    if name == "ollama":
        return OllamaProvider()
    if name == "openai":
        return OpenAICompatProvider()
    raise ValueError(f"LLM_PROVIDER desconhecido: {name!r} (use 'ollama' ou 'openai')")
