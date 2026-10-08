"""Access control rules. Every read path (API and, later, retrieval) goes through here."""

from sqlalchemy import exists, select
from sqlalchemy.sql import ColumnElement

from app.models import Document, User, document_groups
from app.models.document import DocumentStatus
from app.models.user import Role


def document_visibility(user: User) -> ColumnElement[bool]:
    """SQL condition: documents `user` may read.

    Admin sees everything. Others need a group in common with the document;
    collaborators additionally only see published documents.
    """
    if user.role == Role.admin:
        return Document.id.is_not(None)
    shares_group = exists(
        select(1).where(
            document_groups.c.document_id == Document.id,
            document_groups.c.group_id.in_(user.group_ids or {-1}),
        )
    )
    if user.role == Role.gestor:
        return shares_group
    return shares_group & (Document.status == DocumentStatus.published)


def can_edit_document(user: User, doc: Document) -> bool:
    if user.role == Role.admin:
        return True
    return user.role == Role.gestor and bool(user.group_ids & doc.group_ids)


def can_assign_groups(user: User, group_ids: set[int]) -> bool:
    """Managers may only grant access to groups they belong to themselves."""
    return user.role == Role.admin or group_ids <= user.group_ids
