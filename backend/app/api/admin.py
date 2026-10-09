from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import Admin, CurrentUser, DbSession, Manager
from app.models import Group, User
from app.models.user import Role
from app.schemas import GroupIn, GroupOut, UserBrief, UserCreate, UserOut, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/api", tags=["admin"])


def _load_groups(db, ids: list[int]) -> list[Group]:
    groups = list(db.scalars(select(Group).where(Group.id.in_(ids)))) if ids else []
    if len(groups) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Grupo inexistente")
    return groups


@router.get("/groups", response_model=list[GroupOut])
def list_groups(db: DbSession, user: CurrentUser):
    """Admins see every group; everyone else only the groups they belong to."""
    if user.role == Role.admin:
        return db.scalars(select(Group).order_by(Group.name)).all()
    return sorted(user.groups, key=lambda g: g.name)


@router.get("/people", response_model=list[UserBrief])
def list_people(db: DbSession, _: Manager):
    """Names only, so managers can pick a document's topic owner."""
    return db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()


@router.post("/groups", response_model=GroupOut, status_code=201)
def create_group(body: GroupIn, db: DbSession, _: Admin):
    group = Group(name=body.name)
    db.add(group)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Grupo já existe") from None
    return group


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _: Admin):
    return db.scalars(select(User).order_by(User.name)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: DbSession, _: Admin):
    user = User(
        name=body.name,
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        role=body.role,
        groups=_load_groups(db, body.group_ids),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado") from None
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: DbSession, admin: Admin):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    data = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (data.get("role", Role.admin) != Role.admin or data.get("is_active") is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Você não pode remover seu próprio acesso de admin")
    if "password" in data:
        user.password_hash = hash_password(data.pop("password"))
    if "group_ids" in data:
        user.groups = _load_groups(db, data.pop("group_ids"))
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    return user
