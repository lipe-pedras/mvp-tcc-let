"""Deterministic stand-ins for the embedding model and the reranker."""

import hashlib
import math
import re

import httpx

from app.models.chunk import EMBEDDING_DIM

_WORD = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


class FakeEmbedder:
    """Hashed bag-of-words: texts sharing words get similar vectors."""

    model = "fake-embed"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * EMBEDDING_DIM
            for tok in _tokens(text):
                vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % EMBEDDING_DIM] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


class FailingEmbedder:
    model = "fail"

    def embed(self, texts):
        raise httpx.ConnectError("ollama is down")


class FakeReranker:
    """Score = fraction of the question's words found in the passage."""

    def score(self, question: str, passages: list[str]) -> list[float]:
        q = set(_tokens(question))
        return [len(q & set(_tokens(p))) / (len(q) or 1) for p in passages]
