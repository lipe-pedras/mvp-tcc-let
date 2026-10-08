"""Turns document versions into searchable chunks."""

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.models.document import DocumentStatus
from app.providers.embeddings import EmbeddingProvider
from app.services.ingestion.chunker import chunk_markdown


def deactivate_chunks(db: Session, document_id: int) -> None:
    db.execute(update(Chunk).where(Chunk.document_id == document_id).values(active=False))


def index_document(db: Session, doc: Document, embedder: EmbeddingProvider) -> int:
    """(Re)index the current version; previous versions' chunks become inactive.

    Only published documents are searchable. Returns the number of chunks created.
    """
    deactivate_chunks(db, doc.id)
    if doc.status != DocumentStatus.published:
        return 0

    version = doc.current
    chunks = chunk_markdown(version.content_md)
    texts = [c.indexed_text(version.title) for c in chunks]
    vectors = embedder.embed(texts)
    group_ids = sorted(doc.group_ids)
    db.add_all(
        Chunk(
            document_id=doc.id,
            version=version.version,
            position=i,
            section_path=c.path_without_title(version.title),
            page=c.page,
            text=c.text,
            indexed_text=t,
            embedding=v,
            embedding_model=embedder.model,
            group_ids=group_ids,
            active=True,
        )
        for i, (c, t, v) in enumerate(zip(chunks, texts, vectors, strict=True))
    )
    db.flush()
    return len(chunks)


def sync_chunk_groups(db: Session, doc: Document) -> None:
    """Keep the access groups on active chunks equal to the document's."""
    db.execute(
        update(Chunk)
        .where(Chunk.document_id == doc.id, Chunk.active.is_(True))
        .values(group_ids=sorted(doc.group_ids))
    )
