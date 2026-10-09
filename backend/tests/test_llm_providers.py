import json
from contextlib import contextmanager

import pytest

from app.config import get_settings
from app.providers.llm import OllamaProvider, OpenAICompatProvider, get_llm_provider


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


def patch_stream(monkeypatch, lines, captured):
    @contextmanager
    def fake_stream(method, url, **kwargs):
        captured.update(url=url, **kwargs)
        yield FakeResponse(lines)

    monkeypatch.setattr("app.providers.llm.httpx.stream", fake_stream)


def test_ollama_streams_pieces_and_disables_thinking(monkeypatch):
    lines = [json.dumps({"message": {"content": c}, "done": False}) for c in ("Olá", " mundo")] + [
        json.dumps({"message": {"content": ""}, "done": True})
    ]
    captured = {}
    patch_stream(monkeypatch, lines, captured)
    out = list(OllamaProvider().stream([{"role": "user", "content": "oi"}]))
    assert out == ["Olá", " mundo"]
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["think"] is False and captured["json"]["stream"] is True


def test_openai_compatible_parses_sse_chunks(monkeypatch):
    chunk = lambda t: "data: " + json.dumps({"choices": [{"delta": {"content": t}}]})  # noqa: E731
    lines = [chunk("A"), "", chunk("B"), "data: " + json.dumps({"choices": []}), "data: [DONE]", chunk("ignored")]
    captured = {}
    patch_stream(monkeypatch, lines, captured)
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-test")
    out = list(OpenAICompatProvider().stream([{"role": "user", "content": "oi"}]))
    assert out == ["A", "B"]
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_provider_is_chosen_by_configuration(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "openai")
    assert isinstance(get_llm_provider(), OpenAICompatProvider)
    monkeypatch.setattr(s, "llm_provider", "ollama")
    assert isinstance(get_llm_provider(), OllamaProvider)
    monkeypatch.setattr(s, "llm_provider", "nope")
    with pytest.raises(ValueError):
        get_llm_provider()
