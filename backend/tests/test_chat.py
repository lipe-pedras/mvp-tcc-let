import json
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models import Chunk, Feedback, Gap, GapOrigin, UsageDaily
from app.models.user import Role
from app.services.chat.pipeline import REFUSAL_TEXT, chat
from tests.conftest import auth
from tests.fakes import FakeEmbedder, FakeLLM, FakeReranker


@pytest.fixture(autouse=True)
def threshold(monkeypatch):
    monkeypatch.setattr(get_settings(), "refusal_threshold", 0.4)


@pytest.fixture
def world(client, groups, make_user):
    """RH manager (responsible for the docs), a plain collaborator and a finance collaborator."""
    rh = make_user("rh@empresa.com", Role.gestor, groups["todos"], groups["rh"])
    fin = make_user("fin@empresa.com", Role.gestor, groups["todos"], groups["financeiro"])
    docs = {}
    specs = [
        ("ferias", rh, "todos", "Política de Férias", "# Política de Férias\n\n## Como solicitar\n\nO pedido de férias deve ser feito com 45 dias de antecedência no sistema ORBITA.", {}),
        ("salarios", fin, "financeiro", "Faixas salariais", "# Faixas salariais\n\nO nível Z9 tem salário de 99.000 reais por mês.", {}),
        ("senhas", rh, "todos", "Política de senhas", "# Política de senhas\n\nA troca de senha é obrigatória a cada 90 dias.", {"review_date": "2025-06-30"}),
    ]
    for key, user, group, title, text, extra in specs:
        body = {"title": title, "content_md": text, "group_ids": [groups[group].id], "responsible_id": user.id, **extra}
        r = client.post("/api/documents", json=body, headers=auth(user))
        assert r.status_code == 201, r.text
        docs[key] = r.json()
    colab = make_user("colab@empresa.com", Role.colaborador, groups["todos"])
    colab_fin = make_user("cfin@empresa.com", Role.colaborador, groups["todos"], groups["financeiro"])
    return {"docs": docs, "colab": colab, "colab_fin": colab_fin, "rh": rh}


def run(db, question, user, llm, record=True):
    events = list(chat(db, question, user.group_ids, embedder=FakeEmbedder(), reranker=FakeReranker(), llm=llm, record=record))
    stages = [p for k, p in events if k == "stage"]
    return stages, events[-1][1]


def test_answer_with_valid_citation_returns_sources(db, world):
    llm = FakeLLM("O pedido deve ser feito com 45 dias de antecedência [1].")
    stages, res = run(db, "pedido de férias com quantos dias de antecedência", world["colab"], llm)
    assert stages == ["retrieving", "generating", "validating"]
    assert res.status == "answered" and "45 dias" in res.answer
    s = res.sources[0]
    assert (s.title, s.section_path, s.version) == ("Política de Férias", "Como solicitar", 1)
    assert db.scalar(select(func.count()).select_from(Gap)) == 0
    assert db.scalar(select(UsageDaily.answered)) == 1


def test_below_threshold_refuses_without_calling_llm_and_logs_gap(db, world):
    llm = FakeLLM()
    stages, res = run(db, "como funciona o plano odontológico quântico", world["colab"], llm)
    assert llm.calls == []  # the model is never called
    assert stages == ["retrieving"]
    assert res.status == "refused" and res.answer == REFUSAL_TEXT
    assert res.refusal_reason in {"below_threshold", "no_hits"}
    gap = db.scalars(select(Gap)).one()
    assert gap.origin == GapOrigin.sem_evidencia and gap.day == date.today()
    assert db.scalar(select(UsageDaily.refused)) == 1


def test_refusal_names_the_topic_owner_of_the_closest_document(db, world):
    _, res = run(db, "férias odontológico quântico", world["colab"], FakeLLM())
    assert res.status == "refused"
    assert res.responsible and res.responsible.email == "rh@empresa.com"
    assert res.responsible.document_title == "Política de Férias"


def test_model_saying_no_evidence_becomes_refusal(db, world):
    llm = FakeLLM("SEM_EVIDENCIA")
    _, res = run(db, "pedido de férias com quantos dias de antecedência", world["colab"], llm)
    assert len(llm.calls) == 1
    assert res.status == "refused" and res.refusal_reason == "no_evidence"
    assert db.scalar(select(func.count()).select_from(Gap)) == 1


def test_answer_without_valid_citation_becomes_refusal(db, world):
    for reply in ("São 45 dias.", "São 45 dias [9]."):
        _, res = run(db, "pedido de férias com quantos dias de antecedência", world["colab"], FakeLLM(reply), record=False)
        assert res.status == "refused" and res.refusal_reason == "no_valid_citation"
        assert res.answer == REFUSAL_TEXT  # the uncited text is never shown


def test_invalid_citations_are_stripped_from_answer(db, world):
    llm = FakeLLM("São 45 dias [1] e também [5].")
    _, res = run(db, "pedido de férias com quantos dias de antecedência", world["colab"], llm)
    assert res.status == "answered" and "[5]" not in res.answer and [s.n for s in res.sources] == [1]


def test_overdue_document_adds_warning(db, world):
    llm = FakeLLM("A troca é a cada 90 dias [1].")
    _, res = run(db, "troca de senha obrigatória a cada quantos dias", world["colab"], llm)
    assert res.status == "answered"
    assert res.sources[0].review_overdue
    assert "revisão vencida" in res.warnings[0] and "30/06/2025" in res.warnings[0]


def test_up_to_date_document_has_no_warning(db, world):
    llm = FakeLLM("45 dias [1].")
    _, res = run(db, "pedido de férias com quantos dias de antecedência", world["colab"], llm)
    assert res.warnings == [] and not res.sources[0].review_overdue


def test_restricted_content_never_reaches_the_model(db, world):
    llm = FakeLLM("SEM_EVIDENCIA")
    _, res = run(db, "qual o salário do nível Z9 nas faixas salariais", world["colab"], llm)
    sent = json.dumps(llm.calls)
    assert "99.000" not in sent and "Faixas salariais >" not in sent  # neither content nor title header
    assert res.status == "refused"
    assert all(c.document_id != world["docs"]["salarios"]["id"] for c in res.context_chunks)


def test_authorised_user_gets_restricted_content(db, world):
    llm = FakeLLM("O nível Z9 tem salário de 99.000 reais [1].")
    _, res = run(db, "qual o salário do nível Z9 nas faixas salariais", world["colab_fin"], llm)
    assert res.status == "answered" and res.sources[0].title == "Faixas salariais"


def test_admin_search_is_still_limited_to_own_groups(db, world, groups, make_user):
    admin = make_user("adm@empresa.com", Role.admin, groups["todos"])
    llm = FakeLLM("SEM_EVIDENCIA")
    _, res = run(db, "qual o salário do nível Z9 nas faixas salariais", admin, llm)
    assert "99.000" not in json.dumps(llm.calls)


def test_record_false_leaves_no_trace(db, world):
    run(db, "plano odontológico quântico", world["colab"], FakeLLM(), record=False)
    assert db.scalar(select(func.count()).select_from(Gap)) == 0
    assert db.scalar(select(func.count()).select_from(UsageDaily)) == 0


def test_only_chunks_above_threshold_are_sent(db, world):
    llm = FakeLLM("45 dias [1].")
    _, res = run(db, "pedido de férias com quantos dias de antecedência", world["colab"], llm)
    prompt = llm.calls[0][1]["content"]
    assert "[1]" in prompt and "99.000" not in prompt
    assert all(c.document_id == world["docs"]["ferias"]["id"] for c in res.context_chunks)


# --- HTTP / SSE -------------------------------------------------------------------------------

def parse_sse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        name = next(l[7:] for l in block.split("\n") if l.startswith("event: "))
        data = json.loads(next(l[6:] for l in block.split("\n") if l.startswith("data: ")))
        events.append((name, data))
    return events


def test_sse_stream_emits_stages_then_result_without_internal_fields(client, world, llm):
    llm.reply = "45 dias [1]."
    r = client.post("/api/chat", json={"question": "pedido de férias com quantos dias de antecedência"}, headers=auth(world["colab"]))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert [n for n, _ in events] == ["stage", "stage", "stage", "result"]
    assert [d["name"] for n, d in events if n == "stage"] == ["retrieving", "generating", "validating"]
    result = events[-1][1]
    assert result["status"] == "answered" and result["sources"][0]["document_id"] == world["docs"]["ferias"]["id"]
    assert not {"context_chunks", "raw_answer", "top_score"} & set(result)


def test_chat_requires_authentication(client):
    assert client.post("/api/chat", json={"question": "oi"}).status_code == 401


def test_llm_outage_returns_error_event(client, world, llm):
    import httpx

    def broken(messages):
        raise httpx.ConnectError("down")
        yield  # pragma: no cover

    llm.stream = broken
    r = client.post("/api/chat", json={"question": "pedido de férias com quantos dias de antecedência"}, headers=auth(world["colab"]))
    names = [n for n, _ in parse_sse(r.text)]
    assert names[-1] == "error"


def test_negative_feedback_stores_anonymous_feedback_and_a_gap(client, db, world):
    body = {"question": "como pedir licença?", "answer": "Resposta ruim [1].", "helpful": False, "comment": "não ajudou"}
    assert client.post("/api/chat/feedback", json=body, headers=auth(world["colab"])).status_code == 204
    fb = db.scalars(select(Feedback)).one()
    assert fb.helpful is False and fb.comment == "não ajudou"
    gap = db.scalars(select(Gap)).one()
    assert gap.origin == GapOrigin.feedback_negativo and gap.question == "como pedir licença?"


def test_positive_feedback_does_not_create_a_gap(client, db, world):
    body = {"question": "q", "answer": "a", "helpful": True}
    assert client.post("/api/chat/feedback", json=body, headers=auth(world["colab"])).status_code == 204
    assert db.scalar(select(func.count()).select_from(Gap)) == 0
    assert db.scalar(select(func.count()).select_from(Feedback)) == 1


def test_anonymous_tables_have_no_user_reference():
    from app.db import Base

    for name in ("gaps", "feedback", "usage_daily"):
        cols = {c.name for c in Base.metadata.tables[name].columns}
        assert not {c for c in cols if "user" in c}, f"{name} must not reference users"
        assert not any(fk.column.table.name == "users" for c in Base.metadata.tables[name].columns for fk in c.foreign_keys)
