"""Load the sample company (users, groups, documents) and index it.

    cd backend && uv run python -m app.cli.seed [--reset]

Passwords are for local development only.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select, text

from app.db import Base, SessionLocal
from app.models import Document, DocumentVersion, Group, User
from app.models.document import DocumentStatus
from app.models.user import Role
from app.providers.embeddings import get_embedding_provider
from app.security import hash_password
from app.services.ingestion.indexer import index_document

SEED_DIR = Path(__file__).resolve().parents[3] / "seed"
DEV_PASSWORD = "senha-12345"


def seed(reset: bool = False) -> None:
    manifest = json.loads((SEED_DIR / "manifest.json").read_text(encoding="utf-8"))
    embedder = get_embedding_provider()
    with SessionLocal() as db:
        if reset:
            names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
            db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        elif db.scalar(select(User.id).limit(1)):
            raise SystemExit("O banco já tem dados. Use --reset para recriar (apaga tudo).")

        groups = {name: Group(name=name) for name in manifest["groups"]}
        db.add_all(groups.values())
        users = {
            u["email"]: User(
                name=u["name"],
                email=u["email"],
                password_hash=hash_password(DEV_PASSWORD),
                role=Role(u["role"]),
                groups=[groups[g] for g in u["groups"]],
            )
            for u in manifest["users"]
        }
        db.add_all(users.values())
        db.flush()

        author = next(u for u in users.values() if u.role == Role.admin)
        for d in manifest["documents"]:
            content = (SEED_DIR / "docs" / d["file"]).read_text(encoding="utf-8")
            doc = Document(
                title=d["title"],
                author_id=author.id,
                responsible_id=users[d["responsible"]].id,
                review_date=date.fromisoformat(d["review_date"]),
                status=DocumentStatus.published,
                groups=[groups[g] for g in d["groups"]],
                current_version=1,
            )
            doc.versions.append(
                DocumentVersion(version=1, title=d["title"], content_md=content, created_by=author.id)
            )
            db.add(doc)
            db.flush()
            n = index_document(db, doc, embedder)
            print(f"  {d['title']}: {n} chunks")
        db.commit()
    print(f"Pronto. Usuários de exemplo (senha '{DEV_PASSWORD}'):")
    for u in manifest["users"]:
        print(f"  {u['role']:<12} {u['email']}  grupos={u['groups']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="apaga todos os dados antes")
    seed(ap.parse_args().reset)
