"""Pure metric functions (no database or model access), so they are easy to test."""

from collections.abc import Sequence
from dataclasses import dataclass

Evidence = dict[str, str]  # {"documento": title, "secao": section substring (optional)}


@dataclass(frozen=True)
class RetrievedChunk:
    doc_title: str
    section_path: str
    chunk_group_ids: frozenset[int]
    doc_group_ids: frozenset[int]


def matches(chunk: RetrievedChunk, ev: Evidence) -> bool:
    if chunk.doc_title.strip().lower() != ev["documento"].strip().lower():
        return False
    secao = ev.get("secao", "").strip().lower()
    return not secao or secao in chunk.section_path.lower()


def recall_at_k(ranked: Sequence[RetrievedChunk], evidences: Sequence[Evidence], k: int) -> float | None:
    """Fraction of expected evidences found among the top-k chunks (None if no evidence expected)."""
    if not evidences:
        return None
    found = sum(any(matches(c, ev) for c in ranked[:k]) for ev in evidences)
    return found / len(evidences)


def reciprocal_rank(ranked: Sequence[RetrievedChunk], evidences: Sequence[Evidence]) -> float | None:
    """1 / rank of the first chunk matching any expected evidence (0 if none)."""
    if not evidences:
        return None
    for rank, chunk in enumerate(ranked, start=1):
        if any(matches(chunk, ev) for ev in evidences):
            return 1.0 / rank
    return 0.0


def leaked_chunks(ranked: Sequence[RetrievedChunk], profile_group_ids: set[int]) -> int:
    """Chunks the profile may not read. Checked against both the chunk's copied groups
    and the document's current groups; either lacking overlap counts as a leak."""
    return sum(
        1
        for c in ranked
        if not (c.chunk_group_ids & profile_group_ids) or not (c.doc_group_ids & profile_group_ids)
    )


def mean(values: Sequence[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None
