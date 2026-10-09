import json
from collections.abc import Iterator
from dataclasses import asdict
from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.deps import CurrentUser, DbSession
from app.models import Feedback, GapOrigin
from app.providers.embeddings import EmbeddingProvider, get_embedding_provider
from app.providers.llm import LLMProvider, get_llm_provider
from app.services.chat.pipeline import ChatResult, chat, record_gap
from app.services.retrieval.reranker import Reranker, get_reranker

router = APIRouter(prefix="/api/chat", tags=["chat"])

Embedder = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
Rerank = Annotated[Reranker, Depends(get_reranker)]
LLM = Annotated[LLMProvider, Depends(get_llm_provider)]


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class FeedbackIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(max_length=10000)
    helpful: bool
    comment: str | None = Field(default=None, max_length=500)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _public(result: ChatResult) -> dict:
    """What the client receives. Context chunks and raw model output stay server-side."""
    d = asdict(result)
    for private in ("context_chunks", "raw_answer", "top_score", "ttft_ms", "total_ms"):
        d.pop(private)
    return d


@router.post("")
def ask(body: ChatIn, db: DbSession, user: CurrentUser, embedder: Embedder, reranker: Rerank, llm: LLM):
    """Server-Sent Events: `stage` events while working, then one `result`.

    The answer is fully generated and validated before it is sent, so text without
    a valid source never reaches the user (see docs/decisions.md).
    """
    # Search is always restricted to the user's own groups, whatever their role.
    group_ids = user.group_ids

    def events() -> Iterator[str]:
        try:
            for kind, payload in chat(db, body.question, group_ids, embedder=embedder, reranker=reranker, llm=llm):
                if kind == "stage":
                    yield _sse("stage", {"name": payload})
                else:
                    yield _sse("result", _public(payload))
        except httpx.HTTPError:
            db.rollback()
            yield _sse("error", {"message": "O serviço de modelos está indisponível no momento. Tente novamente."})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
def send_feedback(body: FeedbackIn, db: DbSession, _: CurrentUser, embedder: Embedder):
    """Stores feedback without any link to the user. A negative rating also opens a gap."""
    db.add(
        Feedback(day=date.today(), question=body.question, answer=body.answer, helpful=body.helpful, comment=body.comment)
    )
    if not body.helpful:
        try:
            record_gap(db, body.question, embedder.embed([body.question])[0], GapOrigin.feedback_negativo)
        except httpx.HTTPError:
            db.rollback()
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Serviço de embeddings indisponível") from None
    db.commit()
