from datetime import date
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select

from app.deps import CurrentUser, DbSession, Manager
from app.models import Document, DocumentVersion, Group, User
from app.models.document import DocumentStatus
from app.providers.embeddings import EmbeddingProvider, get_embedding_provider
from app.schemas import (
    DocumentCreate,
    DocumentOut,
    DocumentSummary,
    DocumentUpdate,
    VersionDetail,
    VersionOut,
)
from app.services.ingestion.parsers import DocumentParser, get_parser, parse_upload
from app.services.ingestion.indexer import deactivate_chunks, index_document, sync_chunk_groups
from app.services.access import can_assign_groups, can_edit_document, document_visibility

router = APIRouter(prefix="/api/documents", tags=["documents"])

Embedder = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]


def _reindex_and_commit(db, doc: Document, embedder: EmbeddingProvider, *, groups_only: bool = False):
    """Index in the same transaction as the edit, so they succeed or fail together."""
    try:
        if groups_only:
            sync_chunk_groups(db, doc)
        else:
            index_document(db, doc, embedder)
        db.commit()
    except httpx.HTTPError:
        db.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Serviço de embeddings indisponível; nada foi salvo"
        ) from None


def _doc_out(doc: Document) -> DocumentOut:
    summary = DocumentSummary.model_validate(doc).model_dump()
    return DocumentOut(**summary, author=doc.author, content_md=doc.current.content_md)


def _get_visible(db, user, doc_id: int) -> Document:
    """404 (not 403) for hidden documents, so their existence is not revealed."""
    doc = db.scalar(select(Document).where(Document.id == doc_id, document_visibility(user)))
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado")
    return doc


def _groups(db, ids: list[int]) -> list[Group]:
    groups = list(db.scalars(select(Group).where(Group.id.in_(ids))))
    if len(groups) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Grupo inexistente")
    return groups


def _responsible(db, responsible_id: int | None) -> User | None:
    if responsible_id is None:
        return None
    person = db.get(User, responsible_id)
    if not person:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Responsável inexistente")
    return person


@router.get("", response_model=list[DocumentSummary])
def list_documents(db: DbSession, user: CurrentUser):
    stmt = select(Document).where(document_visibility(user)).order_by(Document.title)
    return db.scalars(stmt).all()


@router.get("/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: int, db: DbSession, user: CurrentUser):
    return _doc_out(_get_visible(db, user, doc_id))


def _create(
    db,
    user: User,
    embedder: EmbeddingProvider,
    *,
    title: str,
    content_md: str,
    group_ids: list[int],
    responsible_id: int | None,
    review_date: date | None,
    doc_status: DocumentStatus,
    source: str,
) -> DocumentOut:
    if not can_assign_groups(user, set(group_ids)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Você só pode usar grupos dos quais participa")
    doc = Document(
        title=title,
        author_id=user.id,
        responsible=_responsible(db, responsible_id),
        review_date=review_date,
        status=doc_status,
        groups=_groups(db, group_ids),
        current_version=1,
    )
    doc.versions.append(
        DocumentVersion(version=1, title=title, content_md=content_md, source=source, created_by=user.id)
    )
    db.add(doc)
    db.flush()
    _reindex_and_commit(db, doc, embedder)
    return _doc_out(doc)


@router.post("", response_model=DocumentOut, status_code=201)
def create_document(body: DocumentCreate, db: DbSession, user: Manager, embedder: Embedder):
    return _create(
        db, user, embedder,
        title=body.title, content_md=body.content_md, group_ids=body.group_ids,
        responsible_id=body.responsible_id, review_date=body.review_date,
        doc_status=body.status, source="markdown",
    )


@router.post("/import", response_model=DocumentOut, status_code=201)
def import_document(
    db: DbSession,
    user: Manager,
    embedder: Embedder,
    parser: Annotated[DocumentParser, Depends(get_parser)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=255)],
    group_ids: Annotated[list[int], Form(min_length=1)],
    responsible_id: Annotated[int | None, Form()] = None,
    review_date: Annotated[date | None, Form()] = None,
    doc_status: Annotated[DocumentStatus, Form(alias="status")] = DocumentStatus.draft,
):
    """Import PDF/DOCX/PPTX. Imports start as drafts so a manager can proofread the conversion."""
    try:
        content_md = parse_upload(parser, file.filename or "", file.file.read())
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    if not content_md.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Não foi possível extrair texto do arquivo")
    return _create(
        db, user, embedder,
        title=title, content_md=content_md, group_ids=group_ids,
        responsible_id=responsible_id, review_date=review_date,
        doc_status=doc_status, source="import",
    )


@router.put("/{doc_id}", response_model=DocumentOut)
def update_document(doc_id: int, body: DocumentUpdate, db: DbSession, user: Manager, embedder: Embedder):
    doc = _get_visible(db, user, doc_id)
    if not can_edit_document(user, doc):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Você não pode editar este documento")
    data = body.model_dump(exclude_unset=True)

    if "group_ids" in data:
        if not can_assign_groups(user, set(data["group_ids"])):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Você só pode usar grupos dos quais participa")
        doc.groups = _groups(db, data["group_ids"])
    if "responsible_id" in data:
        doc.responsible = _responsible(db, data["responsible_id"])
    if "review_date" in data:
        doc.review_date = data["review_date"]
    if data.get("status") is not None:
        doc.status = data["status"]

    # Only title/content changes create a new version; metadata edits do not.
    current = doc.current
    new_title = data.get("title") or current.title
    new_content = data.get("content_md", current.content_md)
    content_changed = new_title != current.title or new_content != current.content_md
    if content_changed:
        doc.current_version = current.version + 1
        doc.title = new_title
        doc.versions.append(
            DocumentVersion(
                version=doc.current_version,
                title=new_title,
                content_md=new_content,
                change_note=data.get("change_note"),
                created_by=user.id,
            )
        )
    db.flush()
    # Content or status changes need a full reindex; permission-only changes just resync groups.
    needs_reindex = content_changed or "status" in data
    _reindex_and_commit(db, doc, embedder, groups_only=not needs_reindex)
    return _doc_out(doc)


@router.get("/{doc_id}/versions", response_model=list[VersionOut])
def list_versions(doc_id: int, db: DbSession, user: Manager):
    doc = _get_visible(db, user, doc_id)
    return sorted(doc.versions, key=lambda v: -v.version)


@router.get("/{doc_id}/versions/{version}", response_model=VersionDetail)
def get_version(doc_id: int, version: int, db: DbSession, user: Manager):
    doc = _get_visible(db, user, doc_id)
    found = next((v for v in doc.versions if v.version == version), None)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Versão não encontrada")
    return found


@router.delete("/{doc_id}", status_code=204)
def archive_document(doc_id: int, db: DbSession, user: Manager):
    """Documents are archived, never deleted, so version history is preserved."""
    doc = _get_visible(db, user, doc_id)
    if not can_edit_document(user, doc):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Você não pode arquivar este documento")
    doc.status = DocumentStatus.archived
    deactivate_chunks(db, doc.id)
    db.commit()
