"""Hybrid retrieval: dense (pgvector) + lexical (PostgreSQL FTS), fused with RRF.

Permission filtering happens inside both SQL queries (WHERE group_ids && :groups),
before any ranking, so a chunk the user may not read can never become a candidate.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.orm import Session

from app.models import Chunk
from app.providers.embeddings import EmbeddingProvider
from app.services.retrieval.reranker import Reranker

RRF_K = 60


@dataclass
class Hit:
    chunk: Chunk
    rrf_score: float
    rerank_score: float | None = None


def _allowed(group_ids: Iterable[int]):
    return (Chunk.active.is_(True)) & Chunk.group_ids.overlap(list(group_ids))


def dense_search(db: Session, query_vec: list[float], group_ids: set[int], n: int) -> list[int]:
    if not group_ids:
        return []
    stmt = (
        select(Chunk.id)
        .where(_allowed(group_ids))
        .order_by(Chunk.embedding.cosine_distance(query_vec))
        .limit(n)
    )
    return list(db.scalars(stmt))


_WORD = re.compile(r"[\wÀ-ÿ]+(?:[-./][\wÀ-ÿ]+)*", re.UNICODE)


def lexical_query(question: str) -> str | None:
    """OR-query over the question's words (quoted, so codes like 'HR-204' survive).

    Natural-language questions rarely contain *all* words of the answer chunk,
    so an AND query would miss most of them. Stop words are dropped by the
    `portuguese` configuration.
    """
    words = {w.replace("'", "") for w in _WORD.findall(question)}
    words = {w for w in words if len(w) > 1}
    return " | ".join(f"'{w}'" for w in sorted(words)) or None


def lexical_search(db: Session, question: str, group_ids: set[int], n: int) -> list[int]:
    q = lexical_query(question)
    if not group_ids or q is None:
        return []
    tsq = func.to_tsquery(cast(literal("portuguese"), REGCONFIG), q)
    stmt = (
        select(Chunk.id)
        .where(_allowed(group_ids), Chunk.tsv.op("@@")(tsq))
        .order_by(func.ts_rank_cd(Chunk.tsv, tsq).desc())
        .limit(n)
    )
    return list(db.scalars(stmt))


def rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion. Returns (chunk_id, score) best first."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def retrieve(
    db: Session,
    question: str,
    group_ids: set[int],
    embedder: EmbeddingProvider,
    reranker: Reranker,
    *,
    candidates: int,
    rerank_top_n: int,
) -> list[Hit]:
    """Return hits ordered by reranker score (best first)."""
    query_vec = embedder.embed([question])[0]
    fused = rrf_fuse(
        [
            dense_search(db, query_vec, group_ids, candidates),
            lexical_search(db, question, group_ids, candidates),
        ]
    )[:rerank_top_n]
    if not fused:
        return []
    by_id = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_([i for i, _ in fused])))}
    hits = [Hit(chunk=by_id[i], rrf_score=s) for i, s in fused]
    scores = reranker.score(question, [h.chunk.indexed_text for h in hits])
    for hit, score in zip(hits, scores, strict=True):
        hit.rerank_score = score
    return sorted(hits, key=lambda h: h.rerank_score, reverse=True)
