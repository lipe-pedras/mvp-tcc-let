import pytest

from eval.metrics import RetrievedChunk, leaked_chunks, mean, recall_at_k, reciprocal_rank


def chunk(title, section="", chunk_groups=(1,), doc_groups=(1,)):
    return RetrievedChunk(title, section, frozenset(chunk_groups), frozenset(doc_groups))


RANKED = [
    chunk("Reembolso", "Reembolso > Limites"),
    chunk("Férias", "Férias > Como solicitar"),
    chunk("Viagens", "Viagens > Prestação de contas"),
]


def test_recall_counts_expected_evidences_in_top_k():
    evs = [{"documento": "Férias", "secao": "como solicitar"}, {"documento": "Viagens", "secao": "Prestação"}]
    assert recall_at_k(RANKED, evs, 1) == 0.0
    assert recall_at_k(RANKED, evs, 2) == 0.5
    assert recall_at_k(RANKED, evs, 3) == 1.0


def test_section_is_optional_and_wrong_section_does_not_match():
    assert recall_at_k(RANKED, [{"documento": "Férias"}], 2) == 1.0
    assert recall_at_k(RANKED, [{"documento": "Férias", "secao": "Abono"}], 3) == 0.0


def test_reciprocal_rank():
    assert reciprocal_rank(RANKED, [{"documento": "Férias"}]) == 0.5
    assert reciprocal_rank(RANKED, [{"documento": "Nada"}]) == 0.0


def test_no_evidence_expected_gives_none():
    assert recall_at_k(RANKED, [], 5) is None and reciprocal_rank(RANKED, []) is None


def test_leak_detected_from_chunk_or_document_groups():
    ok = chunk("A", chunk_groups=(1,), doc_groups=(1,))
    chunk_leak = chunk("B", chunk_groups=(2,), doc_groups=(1,))
    stale_chunk_groups = chunk("C", chunk_groups=(1,), doc_groups=(2,))  # doc was restricted later
    assert leaked_chunks([ok], {1}) == 0
    assert leaked_chunks([ok, chunk_leak, stale_chunk_groups], {1}) == 2


def test_mean_ignores_none():
    assert mean([1.0, None, 0.0]) == pytest.approx(0.5)
    assert mean([None]) is None
