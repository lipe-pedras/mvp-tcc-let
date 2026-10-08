import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import Group, User
from app.providers.embeddings import get_embedding_provider
from app.models.user import Role
from app.security import create_access_token, hash_password
from tests.fakes import FakeEmbedder

test_engine = create_engine(get_settings().test_database_url)
TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with test_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db():
    with TestSession() as session:
        yield session


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_embedding_provider] = FakeEmbedder
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def groups(db):
    made = {name: Group(name=name) for name in ("todos", "rh", "financeiro")}
    db.add_all(made.values())
    db.commit()
    return made


@pytest.fixture
def make_user(db):
    def _make(email: str, role: Role, *group_objs: Group, password: str = "senha-12345") -> User:
        user = User(
            name=email.split("@")[0].title(),
            email=email,
            password_hash=hash_password(password),
            role=role,
            groups=list(group_objs),
        )
        db.add(user)
        db.commit()
        return user

    return _make


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}
