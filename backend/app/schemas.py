from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.document import DocumentStatus
from app.models.user import Role


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class GroupOut(ORM):
    id: int
    name: str


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class UserOut(ORM):
    id: int
    name: str
    email: EmailStr
    role: Role
    is_active: bool
    groups: list[GroupOut]


class UserBrief(ORM):
    id: int
    name: str


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8)
    role: Role = Role.colaborador
    group_ids: list[int] = []


class UserUpdate(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: Role | None = None
    is_active: bool | None = None
    group_ids: list[int] | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content_md: str
    responsible_id: int | None = None
    review_date: date | None = None
    group_ids: list[int] = Field(min_length=1)
    status: DocumentStatus = DocumentStatus.published


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content_md: str | None = None
    responsible_id: int | None = None
    review_date: date | None = None
    group_ids: list[int] | None = Field(default=None, min_length=1)
    status: DocumentStatus | None = None
    change_note: str | None = Field(default=None, max_length=255)


class DocumentSummary(ORM):
    id: int
    title: str
    status: DocumentStatus
    current_version: int
    review_date: date | None
    responsible: UserBrief | None
    groups: list[GroupOut]
    updated_at: datetime


class DocumentOut(DocumentSummary):
    author: UserBrief
    content_md: str


class VersionOut(ORM):
    version: int
    title: str
    change_note: str | None
    source: str
    created_by: int
    created_at: datetime


class VersionDetail(VersionOut):
    content_md: str
