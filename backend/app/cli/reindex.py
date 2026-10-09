"""Reindex all documents with the current embedding model.

    cd backend && uv run python -m app.cli.reindex
"""

from app.config import get_settings
from app.db import SessionLocal
from app.providers.embeddings import get_embedding_provider
from app.services.ingestion.indexer import reindex_all


def main() -> None:
    s = get_settings()
    print(f"Reindexando com o modelo '{s.embedding_model}' (dimensão {s.embedding_dim})...")
    with SessionLocal() as db:
        n = reindex_all(db, get_embedding_provider())
    print(f"Pronto: {n} chunks ativos.")


if __name__ == "__main__":
    main()
