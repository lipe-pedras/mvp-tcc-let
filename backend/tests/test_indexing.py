import pytest
from sqlalchemy import select

from app.models import Chunk
from app.models.user import Role
from app.providers.embeddings import get_embedding_provider
from app.main import app
from tests.conftest import auth
from tests.fakes import FailingEmbedder

BODY = "# Férias\n\nTodo colaborador tem 30 dias.\n\n## Como solicitar\n\nAbra o chamado ORBITA-77."


@pytest.fixture
def gestor(groups, make_user):
    return make_user("rh@empresa.com", Role.gestor, groups["todos"], groups["rh"])


def make(client, gestor, groups, **extra):
    body = {"title": "Política de Férias", "content_md": BODY, "group_ids": [groups["rh"].id], **extra}
    r = client.post("/api/documents", json=body, headers=auth(gestor))
    assert r.status_code == 201, r.text
    return r.json()


def active(db, doc_id):
    return list(db.scalars(select(Chunk).where(Chunk.document_id == doc_id, Chunk.active.is_(True)).order_by(Chunk.position)))


def test_create_indexes_chunks_with_document_groups(client, db, gestor, groups):
    doc = make(client, gestor, groups)
    chunks = active(db, doc["id"])
    assert len(chunks) == 2
    assert all(c.group_ids == [groups["rh"].id] for c in chunks)
    assert chunks[1].section_path == "Férias > Como solicitar"
    assert chunks[1].indexed_text.startswith("Política de Férias > Férias > Como solicitar")
    assert len(chunks[0].embedding) == 1024


def test_edit_deactivates_previous_version_chunks(client, db, gestor, groups):
    doc = make(client, gestor, groups)
    client.put(f"/api/documents/{doc['id']}", json={"content_md": "# Férias\n\nAgora são 20 dias."}, headers=auth(gestor))
    all_chunks = list(db.scalars(select(Chunk).where(Chunk.document_id == doc["id"])))
    assert {c.version for c in all_chunks if c.active} == {2}
    assert {c.version for c in all_chunks if not c.active} == {1}
    assert any("20 dias" in c.text for c in active(db, doc["id"]))


def test_metadata_edit_keeps_chunks(client, db, gestor, groups):
    doc = make(client, gestor, groups)
    ids = [c.id for c in active(db, doc["id"])]
    client.put(f"/api/documents/{doc['id']}", json={"review_date": "2027-01-01"}, headers=auth(gestor))
    assert [c.id for c in active(db, doc["id"])] == ids


def test_group_change_updates_chunk_permissions(client, db, gestor, groups):
    doc = make(client, gestor, groups)
    r = client.put(f"/api/documents/{doc['id']}", json={"group_ids": [groups["todos"].id]}, headers=auth(gestor))
    assert r.status_code == 200
    assert all(c.group_ids == [groups["todos"].id] for c in active(db, doc["id"]))


def test_draft_is_not_indexed_and_publishing_indexes_it(client, db, gestor, groups):
    doc = make(client, gestor, groups, status="draft")
    assert active(db, doc["id"]) == []
    client.put(f"/api/documents/{doc['id']}", json={"status": "published"}, headers=auth(gestor))
    assert len(active(db, doc["id"])) == 2


def test_archive_deactivates_chunks(client, db, gestor, groups):
    doc = make(client, gestor, groups)
    client.delete(f"/api/documents/{doc['id']}", headers=auth(gestor))
    assert active(db, doc["id"]) == []


def test_embedding_failure_saves_nothing(client, db, gestor, groups):
    app.dependency_overrides[get_embedding_provider] = FailingEmbedder
    body = {"title": "X", "content_md": BODY, "group_ids": [groups["rh"].id]}
    r = client.post("/api/documents", json=body, headers=auth(gestor))
    assert r.status_code == 503
    assert client.get("/api/documents", headers=auth(gestor)).json() == []


def test_reindex_all_replaces_chunks_with_current_embedder(client, db, gestor, groups):
    from app.services.ingestion.indexer import reindex_all
    from tests.fakes import FakeEmbedder

    class OtherModel(FakeEmbedder):
        model = "other-embed"

    doc = make(client, gestor, groups)
    make(client, gestor, groups, status="draft")  # drafts stay out of the index
    assert {c.embedding_model for c in active(db, doc["id"])} == {"fake-embed"}
    assert reindex_all(db, OtherModel()) == 2
    assert {c.embedding_model for c in active(db, doc["id"])} == {"other-embed"}
    assert db.scalars(select(Chunk).where(Chunk.embedding_model == "fake-embed", Chunk.active.is_(True))).first() is None
