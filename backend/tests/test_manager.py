import json
from datetime import date, timedelta

import numpy as np
import pytest

from app.config import get_settings
from app.models import Feedback, Gap, GapOrigin, UsageDaily
from app.models.user import Role
from app.services.analytics.gaps import GapRecord, cluster_gaps
from tests.conftest import auth
from tests.fakes import FakeEmbedder

TODAY = date.today()


def unit(*xs):
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def rec(q, vec, day=TODAY):
    return GapRecord(q, vec, day)


# --- clustering (pure) ------------------------------------------------------------------------

def test_cluster_below_k_is_never_returned():
    a = unit(1, 0, 0)
    records = [rec("licença?", a), rec("licença paternidade?", unit(1, 0.05, 0))]
    assert cluster_gaps(records, min_size=3, similarity=0.9) == []


def test_cluster_with_exactly_k_is_returned():
    records = [rec(f"licença {i}?", unit(1, 0.02 * i, 0)) for i in range(3)]
    clusters = cluster_gaps(records, min_size=3, similarity=0.9)
    assert len(clusters) == 1 and clusters[0].count == 3
    assert len(cluster_gaps(records[:2], min_size=3, similarity=0.9)) == 0


def test_k_is_configurable_and_k1_shows_everything():
    records = [rec("a?", unit(1, 0, 0)), rec("b?", unit(0, 1, 0))]
    assert len(cluster_gaps(records, min_size=1, similarity=0.9)) == 2
    assert cluster_gaps(records, min_size=2, similarity=0.9) == []


def test_dissimilar_questions_do_not_merge():
    records = [rec("x", unit(1, 0, 0)), rec("y", unit(0, 1, 0)), rec("z", unit(0, 0, 1))]
    assert cluster_gaps(records, min_size=2, similarity=0.5) == []


def test_cluster_reports_period_and_distinct_examples():
    d0 = TODAY - timedelta(days=5)
    records = [rec("Licença?", unit(1, 0, 0), d0), rec("Licença?", unit(1, 0, 0), TODAY), rec("licença paternidade?", unit(1, 0.01, 0), TODAY)]
    (c,) = cluster_gaps(records, min_size=3, similarity=0.9)
    assert (c.first_day, c.last_day) == (d0, TODAY)
    wordings = [c.label, *c.examples]
    assert sorted(wordings) == ["Licença?", "licença paternidade?"]  # duplicates collapsed, label not repeated


# --- API --------------------------------------------------------------------------------------

@pytest.fixture
def people(groups, make_user):
    return {
        "gestor": make_user("g@empresa.com", Role.gestor, groups["todos"], groups["rh"]),
        "gestor_fin": make_user("f@empresa.com", Role.gestor, groups["todos"], groups["financeiro"]),
        "colab": make_user("c@empresa.com", Role.colaborador, groups["todos"]),
    }


def add_gaps(db, questions, origin=GapOrigin.sem_evidencia, day=TODAY):
    emb = FakeEmbedder().embed(questions)
    db.add_all(Gap(question=q, embedding=e, day=day, origin=origin) for q, e in zip(questions, emb))
    db.commit()


def test_dashboard_is_manager_only(client, people):
    for path in ("/api/manager/gaps", "/api/manager/stats", "/api/manager/overdue-documents", "/api/people"):
        assert client.get(path, headers=auth(people["colab"])).status_code == 403
        assert client.get(path).status_code == 401
        assert client.get(path, headers=auth(people["gestor"])).status_code == 200


def test_gap_panel_hides_clusters_below_k_but_counts_them(client, db, people, monkeypatch):
    monkeypatch.setattr(get_settings(), "gap_similarity", 0.6)
    monkeypatch.setattr(get_settings(), "gap_min_occurrences", 3)
    add_gaps(db, ["como pedir licença paternidade", "licença paternidade como pedir", "pedir licença paternidade como"])
    add_gaps(db, ["qual a senha do wifi visitantes", "senha wifi visitantes qual"])  # only 2
    add_gaps(db, ["onde fica o estacionamento de bicicletas"])  # only 1
    r = client.get("/api/manager/gaps", headers=auth(people["gestor"])).json()
    assert r["min_occurrences"] == 3 and r["total_gaps"] == 6 and r["hidden_gaps"] == 3
    assert len(r["clusters"]) == 1 and r["clusters"][0]["count"] == 3
    text = json.dumps(r)
    assert "wifi" not in text and "bicicletas" not in text  # small clusters are not even described


def test_gap_panel_respects_period(client, db, people, monkeypatch):
    monkeypatch.setattr(get_settings(), "gap_similarity", 0.6)
    add_gaps(db, ["pedir licença paternidade", "licença paternidade pedir", "paternidade pedir licença"], day=TODAY - timedelta(days=40))
    assert client.get("/api/manager/gaps?days=30", headers=auth(people["gestor"])).json()["total_gaps"] == 0
    assert len(client.get("/api/manager/gaps?days=60", headers=auth(people["gestor"])).json()["clusters"]) == 1


def test_manager_responses_never_contain_user_ids_or_conversations(client, db, people, monkeypatch):
    monkeypatch.setattr(get_settings(), "gap_similarity", 0.6)
    add_gaps(db, ["pedir licença paternidade", "licença paternidade pedir", "paternidade pedir licença"])
    db.add(Feedback(day=TODAY, question="q", answer="resposta secreta", helpful=False, comment="comentário identificável"))
    db.commit()
    for path in ("/api/manager/gaps", "/api/manager/stats"):
        body = client.get(path, headers=auth(people["gestor"])).text
        assert "user" not in body.lower() and "resposta secreta" not in body and "identificável" not in body
        assert '"id"' not in body and "email" not in body


def test_stats_aggregate_usage_and_feedback(client, db, people):
    db.add(UsageDaily(day=TODAY, answered=7, refused=3))
    db.add(UsageDaily(day=TODAY - timedelta(days=1), answered=1, refused=0))
    db.add_all([Feedback(day=TODAY, question="q", answer="a", helpful=h) for h in (True, False, False, True)])
    db.commit()
    r = client.get("/api/manager/stats?days=7", headers=auth(people["gestor"])).json()
    assert (r["questions"], r["answered"], r["refused"]) == (11, 8, 3)
    assert r["refusal_rate"] == pytest.approx(3 / 11)
    assert (r["feedback_total"], r["feedback_negative"]) == (4, 2)
    assert len(r["per_day"]) == 7 and r["per_day"][-1] == {"day": TODAY.isoformat(), "answered": 7, "refused": 3, "negative_feedback": 2}


def test_overdue_documents_only_those_the_manager_can_see(client, groups, people):
    def make(user, group, title, review):
        body = {"title": title, "content_md": "x", "group_ids": [groups[group].id], "review_date": review}
        assert client.post("/api/documents", json=body, headers=auth(user)).status_code == 201

    make(people["gestor"], "rh", "Vencido RH", (TODAY - timedelta(days=3)).isoformat())
    make(people["gestor"], "rh", "Em dia", (TODAY + timedelta(days=30)).isoformat())
    make(people["gestor_fin"], "financeiro", "Vencido Financeiro", (TODAY - timedelta(days=10)).isoformat())
    titles = [d["title"] for d in client.get("/api/manager/overdue-documents", headers=auth(people["gestor"])).json()]
    assert titles == ["Vencido RH"]


# --- passages ---------------------------------------------------------------------------------

def test_passage_of_old_version_is_still_readable_but_permission_checked(client, groups, people):
    g = people["gestor"]
    body = {"title": "Férias", "content_md": "# Férias\n\n## Prazo\n\n45 dias.", "group_ids": [groups["rh"].id]}
    doc = client.post("/api/documents", json=body, headers=auth(g)).json()
    from tests.conftest import TestSession
    from sqlalchemy import select
    from app.models import Chunk

    with TestSession() as s:
        old = s.scalars(select(Chunk).where(Chunk.document_id == doc["id"])).first()
        old_id = old.id
    client.put(f"/api/documents/{doc['id']}", json={"content_md": "# Férias\n\n## Prazo\n\n30 dias."}, headers=auth(g))
    r = client.get(f"/api/documents/{doc['id']}/passages/{old_id}", headers=auth(g))
    assert r.status_code == 200
    p = r.json()
    assert "45 dias" in p["text"] and p["version"] == 1 and p["is_current_version"] is False
    # A user without access to the document cannot read the passage (404, not 403).
    assert client.get(f"/api/documents/{doc['id']}/passages/{old_id}", headers=auth(people["colab"])).status_code == 404
    assert client.get(f"/api/documents/{doc['id']}/passages/999999", headers=auth(g)).status_code == 404
