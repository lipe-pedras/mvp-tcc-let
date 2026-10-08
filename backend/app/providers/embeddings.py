"""Embedding provider abstraction. Swap the implementation to change the backend."""

from typing import Protocol

import httpx

from app.config import get_settings


class EmbeddingProvider(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbeddings:
    def __init__(self, base_url: str | None = None, model: str | None = None):
        s = get_settings()
        self.base_url = (base_url or s.ollama_url).rstrip("/")
        self.model = model or s.embedding_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for i in range(0, len(texts), 16):  # small batches keep memory bounded
            r = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts[i : i + 16], "keep_alive": "5m"},
                timeout=300,
            )
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
        return out


def get_embedding_provider() -> EmbeddingProvider:
    return OllamaEmbeddings()
