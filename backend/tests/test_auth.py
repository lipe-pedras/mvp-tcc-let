from app.models.user import Role
from tests.conftest import auth


def test_login_and_me(client, groups, make_user):
    make_user("ana@empresa.com", Role.colaborador, groups["todos"])
    r = client.post("/api/auth/login", data={"username": "ana@empresa.com", "password": "senha-12345"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "ana@empresa.com"
    assert "password_hash" not in me.json()


def test_login_wrong_password(client, groups, make_user):
    make_user("ana@empresa.com", Role.colaborador, groups["todos"])
    r = client.post("/api/auth/login", data={"username": "ana@empresa.com", "password": "errada-123"})
    assert r.status_code == 401


def test_requires_token(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents", headers={"Authorization": "Bearer lixo"}).status_code == 401


def test_inactive_user_rejected(client, db, groups, make_user):
    user = make_user("ana@empresa.com", Role.colaborador, groups["todos"])
    user.is_active = False
    db.commit()
    assert client.get("/api/auth/me", headers=auth(user)).status_code == 401


def test_only_admin_manages_users(client, groups, make_user):
    admin = make_user("adm@empresa.com", Role.admin, groups["todos"])
    gestor = make_user("g@empresa.com", Role.gestor, groups["todos"])
    body = {"name": "Novo", "email": "novo@empresa.com", "password": "senha-12345", "group_ids": [groups["rh"].id]}
    assert client.post("/api/users", json=body, headers=auth(gestor)).status_code == 403
    r = client.post("/api/users", json=body, headers=auth(admin))
    assert r.status_code == 201
    assert r.json()["role"] == "colaborador"
    assert client.post("/api/users", json=body, headers=auth(admin)).status_code == 409


def test_admin_cannot_demote_self(client, groups, make_user):
    admin = make_user("adm@empresa.com", Role.admin, groups["todos"])
    r = client.patch(f"/api/users/{admin.id}", json={"role": "colaborador"}, headers=auth(admin))
    assert r.status_code == 400
