import pytest

from app.models.user import Role
from tests.conftest import auth


@pytest.fixture
def people(groups, make_user):
    return {
        "admin": make_user("adm@empresa.com", Role.admin, groups["todos"]),
        "gestor_rh": make_user("rh@empresa.com", Role.gestor, groups["todos"], groups["rh"]),
        "gestor_fin": make_user("fin@empresa.com", Role.gestor, groups["todos"], groups["financeiro"]),
        "colab": make_user("colab@empresa.com", Role.colaborador, groups["todos"]),
        "colab_fin": make_user("cfin@empresa.com", Role.colaborador, groups["todos"], groups["financeiro"]),
    }


def new_doc(client, user, group_ids, **extra):
    body = {"title": "Férias", "content_md": "# Férias\n\n30 dias.", "group_ids": group_ids, **extra}
    r = client.post("/api/documents", json=body, headers=auth(user))
    assert r.status_code == 201, r.text
    return r.json()


def test_collaborator_cannot_read_other_group_document(client, groups, people):
    doc = new_doc(client, people["gestor_fin"], [groups["financeiro"].id], title="Faixas salariais")
    r = client.get(f"/api/documents/{doc['id']}", headers=auth(people["colab"]))
    assert r.status_code == 404  # 404, not 403: existence is not revealed
    assert client.get(f"/api/documents/{doc['id']}", headers=auth(people["colab_fin"])).status_code == 200


def test_list_only_returns_permitted_documents(client, groups, people):
    new_doc(client, people["gestor_fin"], [groups["financeiro"].id], title="Faixas salariais")
    public = new_doc(client, people["gestor_rh"], [groups["todos"].id], title="Home office")
    ids = [d["id"] for d in client.get("/api/documents", headers=auth(people["colab"])).json()]
    assert ids == [public["id"]]
    titles = {d["title"] for d in client.get("/api/documents", headers=auth(people["colab_fin"])).json()}
    assert titles == {"Faixas salariais", "Home office"}


def test_collaborator_does_not_see_drafts_or_archived(client, groups, people):
    doc = new_doc(client, people["gestor_rh"], [groups["todos"].id], status="draft")
    assert client.get("/api/documents", headers=auth(people["colab"])).json() == []
    assert client.get(f"/api/documents/{doc['id']}", headers=auth(people["colab"])).status_code == 404
    assert client.get(f"/api/documents/{doc['id']}", headers=auth(people["gestor_rh"])).status_code == 200


def test_manager_in_other_group_cannot_see_or_edit(client, groups, people):
    doc = new_doc(client, people["gestor_fin"], [groups["financeiro"].id])
    r = client.put(f"/api/documents/{doc['id']}", json={"title": "x"}, headers=auth(people["gestor_rh"]))
    assert r.status_code == 404
    assert client.get(f"/api/documents/{doc['id']}/versions", headers=auth(people["gestor_rh"])).status_code == 404


def test_admin_sees_everything(client, groups, people):
    doc = new_doc(client, people["gestor_fin"], [groups["financeiro"].id], status="draft")
    assert client.get(f"/api/documents/{doc['id']}", headers=auth(people["admin"])).status_code == 200


def test_collaborator_cannot_write(client, groups, people):
    body = {"title": "x", "content_md": "y", "group_ids": [groups["todos"].id]}
    assert client.post("/api/documents", json=body, headers=auth(people["colab"])).status_code == 403
    doc = new_doc(client, people["gestor_rh"], [groups["todos"].id])
    assert client.put(f"/api/documents/{doc['id']}", json={"title": "x"}, headers=auth(people["colab"])).status_code == 403
    assert client.get(f"/api/documents/{doc['id']}/versions", headers=auth(people["colab"])).status_code == 403


def test_manager_cannot_grant_groups_they_do_not_belong_to(client, groups, people):
    body = {"title": "x", "content_md": "y", "group_ids": [groups["financeiro"].id]}
    assert client.post("/api/documents", json=body, headers=auth(people["gestor_rh"])).status_code == 403
    doc = new_doc(client, people["gestor_rh"], [groups["rh"].id])
    r = client.put(f"/api/documents/{doc['id']}", json={"group_ids": [groups["financeiro"].id]}, headers=auth(people["gestor_rh"]))
    assert r.status_code == 403


def test_editing_content_creates_new_version_and_keeps_history(client, groups, people):
    gestor = people["gestor_rh"]
    doc = new_doc(client, gestor, [groups["todos"].id])
    assert doc["current_version"] == 1

    r = client.put(f"/api/documents/{doc['id']}", json={"content_md": "# Férias\n\n20 dias.", "change_note": "ajuste"}, headers=auth(gestor))
    assert r.json()["current_version"] == 2
    assert "20 dias" in r.json()["content_md"]

    versions = client.get(f"/api/documents/{doc['id']}/versions", headers=auth(gestor)).json()
    assert [v["version"] for v in versions] == [2, 1]
    old = client.get(f"/api/documents/{doc['id']}/versions/1", headers=auth(gestor)).json()
    assert "30 dias" in old["content_md"]


def test_metadata_edit_does_not_create_version(client, groups, people):
    gestor = people["gestor_rh"]
    doc = new_doc(client, gestor, [groups["todos"].id])
    r = client.put(
        f"/api/documents/{doc['id']}",
        json={"review_date": "2027-01-31", "responsible_id": people["gestor_rh"].id},
        headers=auth(gestor),
    )
    assert r.json()["current_version"] == 1
    assert r.json()["review_date"] == "2027-01-31"
    assert r.json()["responsible"]["id"] == people["gestor_rh"].id


def test_document_requires_at_least_one_group(client, people):
    body = {"title": "x", "content_md": "y", "group_ids": []}
    assert client.post("/api/documents", json=body, headers=auth(people["gestor_rh"])).status_code == 422


def test_archive_hides_from_collaborators_but_keeps_data(client, groups, people):
    gestor = people["gestor_rh"]
    doc = new_doc(client, gestor, [groups["todos"].id])
    assert client.delete(f"/api/documents/{doc['id']}", headers=auth(gestor)).status_code == 204
    assert client.get(f"/api/documents/{doc['id']}", headers=auth(people["colab"])).status_code == 404
    assert client.get(f"/api/documents/{doc['id']}", headers=auth(gestor)).json()["status"] == "archived"
