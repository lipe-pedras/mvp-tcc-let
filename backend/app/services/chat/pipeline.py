"""Query pipeline: retrieve -> (refuse | generate) -> validate citations -> sources/warnings."""

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Chunk, Document, Gap, GapOrigin, UsageDaily
from app.providers.embeddings import EmbeddingProvider
from app.providers.llm import LLMProvider
from app.services.chat.citations import is_no_evidence, validate_citations
from app.services.chat.prompts import SYSTEM_PROMPT, build_user_prompt
from app.services.retrieval.reranker import Reranker
from app.services.retrieval.search import Hit, retrieve

REFUSAL_TEXT = "Não encontrei essa informação na documentação."

# Stage names streamed to the frontend while the (buffered) answer is produced.
STAGES = ("retrieving", "generating", "validating")


@dataclass
class Source:
    n: int
    document_id: int
    title: str
    section_path: str
    version: int
    chunk_id: int
    page: int | None
    review_overdue: bool


@dataclass
class Responsible:
    name: str
    email: str
    document_title: str


@dataclass
class ChatResult:
    status: str  # "answered" | "refused"
    answer: str
    sources: list[Source] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    responsible: Responsible | None = None
    refusal_reason: str | None = None  # below_threshold | no_hits | no_evidence | no_valid_citation
    top_score: float = 0.0
    ttft_ms: float | None = None
    total_ms: float = 0.0
    # Not exposed by the API: what was sent to the model (used by the evaluation harness).
    context_chunks: list[Chunk] = field(default_factory=list)
    raw_answer: str = ""


Event = tuple[str, object]  # ("stage", name) ... ("result", ChatResult)


def _record_usage(db: Session, answered: bool) -> None:
    col = UsageDaily.answered if answered else UsageDaily.refused
    stmt = insert(UsageDaily).values(day=date.today(), answered=int(answered), refused=int(not answered))
    db.execute(stmt.on_conflict_do_update(index_elements=["day"], set_={col.key: col + 1}))


def record_gap(db: Session, question: str, embedding: list[float], origin: GapOrigin) -> None:
    """Anonymous: question text, embedding, day and origin. No user, no time of day."""
    db.add(Gap(question=question[:1000], embedding=embedding, day=date.today(), origin=origin))


def _refuse(
    db: Session, question: str, qvec: list[float], reason: str, hits: list[Hit], docs: dict[int, Document], record: bool
) -> ChatResult:
    responsible = None
    if hits:
        doc = docs[hits[0].chunk.document_id]
        if doc.responsible:
            responsible = Responsible(doc.responsible.name, doc.responsible.email, doc.title)
    if record:
        record_gap(db, question, qvec, GapOrigin.sem_evidencia)
        _record_usage(db, answered=False)
        db.commit()
    return ChatResult(
        status="refused",
        answer=REFUSAL_TEXT,
        responsible=responsible,
        refusal_reason=reason,
        top_score=hits[0].rerank_score if hits else 0.0,
    )


def _overdue_warning(doc: Document) -> str:
    who = f" Fale com {doc.responsible.name} ({doc.responsible.email})." if doc.responsible else ""
    return (
        f"O documento “{doc.title}” está com a revisão vencida desde "
        f"{doc.review_date:%d/%m/%Y}; a informação pode estar desatualizada.{who}"
    )


def chat(
    db: Session,
    question: str,
    group_ids: set[int],
    *,
    embedder: EmbeddingProvider,
    reranker: Reranker,
    llm: LLMProvider,
    record: bool = True,
) -> Iterator[Event]:
    """Run the pipeline, yielding ("stage", name) events and finally ("result", ChatResult).

    `record=False` skips gap/usage logging (used by the evaluation harness so that
    test questions do not pollute the manager's dashboard).
    """
    s = get_settings()
    t0 = time.perf_counter()
    yield "stage", "retrieving"
    qvec = embedder.embed([question])[0]
    hits = retrieve(
        db, question, group_ids, embedder, reranker,
        candidates=s.retrieval_candidates, rerank_top_n=s.rerank_top_n, query_vec=qvec,
    )
    doc_ids = {h.chunk.document_id for h in hits}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(doc_ids)))} if doc_ids else {}

    top_score = hits[0].rerank_score if hits else 0.0
    if top_score < s.refusal_threshold:
        # The LLM is never called below the threshold.
        result = _refuse(db, question, qvec, "below_threshold" if hits else "no_hits", hits, docs, record)
        result.total_ms = (time.perf_counter() - t0) * 1000
        yield "result", result
        return

    context = [h for h in hits if h.rerank_score >= s.refusal_threshold][: s.top_k]
    passages = [
        (i, f"{docs[h.chunk.document_id].title} > {h.chunk.section_path}".rstrip(" >"), h.chunk.text)
        for i, h in enumerate(context, start=1)
    ]

    yield "stage", "generating"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, passages)},
    ]
    pieces: list[str] = []
    ttft = None
    for piece in llm.stream(messages):
        if ttft is None:
            ttft = (time.perf_counter() - t0) * 1000
        pieces.append(piece)
    raw = "".join(pieces).strip()

    yield "stage", "validating"
    cleaned, cited = validate_citations(raw, len(context))
    reason = "no_evidence" if is_no_evidence(raw) else ("no_valid_citation" if not cited else None)
    if reason:
        result = _refuse(db, question, qvec, reason, hits, docs, record)
        result.ttft_ms, result.raw_answer, result.context_chunks = ttft, raw, [h.chunk for h in context]
        result.total_ms = (time.perf_counter() - t0) * 1000
        yield "result", result
        return

    sources, warnings, seen_docs = [], [], set()
    for n in cited:
        chunk = context[n - 1].chunk
        doc = docs[chunk.document_id]
        overdue = bool(doc.review_date and doc.review_date < date.today())
        sources.append(
            Source(n, doc.id, doc.title, chunk.section_path, chunk.version, chunk.id, chunk.page, overdue)
        )
        if overdue and doc.id not in seen_docs:
            warnings.append(_overdue_warning(doc))
        seen_docs.add(doc.id)

    if record:
        _record_usage(db, answered=True)
        db.commit()
    yield "result", ChatResult(
        status="answered",
        answer=cleaned,
        sources=sources,
        warnings=warnings,
        top_score=top_score,
        ttft_ms=ttft,
        total_ms=(time.perf_counter() - t0) * 1000,
        context_chunks=[h.chunk for h in context],
        raw_answer=raw,
    )
