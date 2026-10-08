"""Cross-encoder reranker. Its score (0..1) defines the refusal threshold."""

from typing import Protocol

from app.config import get_settings


class Reranker(Protocol):
    def score(self, question: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    """bge-reranker-v2-m3 on CPU (the GPU is left to the LLM). Loaded lazily."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or get_settings().reranker_model
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, device="cpu", max_length=512)
        return self._model

    def score(self, question: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        # Single-logit cross-encoders are passed through a sigmoid by default.
        scores = self._load().predict([(question, p) for p in passages], batch_size=8)
        return [float(s) for s in scores]


_instance: CrossEncoderReranker | None = None


def get_reranker() -> Reranker:
    global _instance
    if _instance is None:
        _instance = CrossEncoderReranker()
    return _instance
