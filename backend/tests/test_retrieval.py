import pytest

from app.models.user import Role
from app.services.retrieval.search import lexical_query, retrieve, rrf_fuse
from tests.conftest import auth
from tests.fakes import FakeEmbedder, FakeReranker


@pytest.fixture
def corpus(client, groups, make_user):
    fin = make_user("fin@empresa.com", Role.gestor, groups["todos"], groups["financeiro"])
    rh = make_user("rh@empresa.com", Role.gestor, groups["todos"], groups["rh"])
    docs = {}
    for key, user, group, title, text in [
        ("salarios", fin, "financeiro", "Faixas salariais", "# Faixas\n\nO nível Z9 recebe salário de 99.000 reais."),
        ("ferias", rh, "todos", "Férias", "# Férias\n\nO colaborador tem 30 dias de férias, pedido no sistema ORBITA."),
    ]:
        body = {"title": title, "content_md": text, "group_ids": [groups[group].id]}
        docs[key] = client.post("/api/documents", json=body, headers=auth(user)).json()
    return docs


def search(db, question, group_ids):
    return retrieve(db, question, set(group_ids), FakeEmbedder(), FakeReranker(), candidates=20, rerank_top_n=10)


def test_user_without_group_never_gets_restricted_chunks(db, groups, corpus):
    # The question matches the restricted document exactly, in both dense and lexical terms.
    hits = search(db, "Qual o salário do nível Z9 nas faixas salariais?", {groups["todos"].id})
    assert all(h.chunk.document_id != corpus["salarios"]["id"] for h in hits)


def test_user_with_group_gets_restricted_chunks(db, groups, corpus):
    hits = search(db, "Qual o salário do nível Z9 nas faixas salariais?", {groups["todos"].id, groups["financeiro"].id})
    assert hits[0].chunk.document_id == corpus["salarios"]["id"]


def test_no_groups_returns_nothing(db, corpus):
    assert search(db, "férias ORBITA", set()) == []


def test_inactive_chunks_are_not_returned(client, db, groups, corpus, make_user):
    rh = make_user("rh2@empresa.com", Role.gestor, groups["todos"])
    client.put(f"/api/documents/{corpus['ferias']['id']}", json={"content_md": "# Férias\n\nAgora 20 dias."}, headers=auth(rh))
    hits = search(db, "quantos dias de férias", {groups["todos"].id})
    assert hits and all(h.chunk.version == 2 for h in hits)


def test_lexical_matches_internal_codes(db, groups, corpus):
    from app.services.retrieval.search import lexical_search

    ids = lexical_search(db, "como uso o ORBITA?", {groups["todos"].id}, 5)
    assert len(ids) == 1


def test_rrf_rewards_agreement_between_rankings():
    fused = rrf_fuse([[1, 2, 3], [2, 3, 9]])
    order = [i for i, _ in fused]
    assert order[:2] == [2, 3] and set(order) == {1, 2, 3, 9}
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)


def test_lexical_query_quotes_codes_and_sanitises():
    q = lexical_query("Como abrir o chamado HR-204, d'água?")
    assert "'HR-204'" in q and "'água'" in q
    assert q.count("'") % 2 == 0  # every lexeme is properly quoted
    assert lexical_query("?!") is None
