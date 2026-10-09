"""Manager dashboard. Aggregates only: no endpoint here returns a user id, a conversation,
or any row tied to a single person."""

from datetime import date, timedelta
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import DbSession, Manager
from app.models import Document, Feedback, Gap, UsageDaily
from app.models.document import DocumentStatus
from app.schemas import DocumentSummary
from app.services.access import document_visibility
from app.services.analytics.gaps import GapRecord, cluster_gaps

router = APIRouter(prefix="/api/manager", tags=["manager"])

Days = Annotated[int, Query(ge=1, le=365, description="Período em dias, contado até hoje")]


class GapClusterOut(BaseModel):
    label: str
    count: int
    first_day: date
    last_day: date
    examples: list[str]


class GapsOut(BaseModel):
    period_days: int
    min_occurrences: int
    total_gaps: int
    hidden_gaps: int  # gaps in clusters below K: counted, never described
    clusters: list[GapClusterOut]


class DayStat(BaseModel):
    day: date
    answered: int
    refused: int
    negative_feedback: int


class StatsOut(BaseModel):
    period_days: int
    questions: int
    answered: int
    refused: int
    refusal_rate: float | None
    feedback_total: int
    feedback_negative: int
    negative_feedback_rate: float | None
    per_day: list[DayStat]


@router.get("/gaps", response_model=GapsOut)
def gaps(db: DbSession, _: Manager, days: Days = 30):
    s = get_settings()
    since = date.today() - timedelta(days=days - 1)
    rows = db.execute(select(Gap.question, Gap.embedding, Gap.day).where(Gap.day >= since)).all()
    records = [GapRecord(q, np.asarray(e), d) for q, e, d in rows]
    clusters = cluster_gaps(records, min_size=s.gap_min_occurrences, similarity=s.gap_similarity)
    shown = sum(c.count for c in clusters)
    return GapsOut(
        period_days=days,
        min_occurrences=s.gap_min_occurrences,
        total_gaps=len(records),
        hidden_gaps=len(records) - shown,
        clusters=[GapClusterOut(**c.__dict__) for c in clusters],
    )


@router.get("/stats", response_model=StatsOut)
def stats(db: DbSession, _: Manager, days: Days = 30):
    since = date.today() - timedelta(days=days - 1)
    usage = {u.day: u for u in db.scalars(select(UsageDaily).where(UsageDaily.day >= since))}
    negatives = dict(
        db.execute(
            select(Feedback.day, func.count()).where(Feedback.day >= since, Feedback.helpful.is_(False)).group_by(Feedback.day)
        ).all()
    )
    fb_total = db.scalar(select(func.count()).select_from(Feedback).where(Feedback.day >= since)) or 0
    per_day = [
        DayStat(
            day=d,
            answered=usage[d].answered if d in usage else 0,
            refused=usage[d].refused if d in usage else 0,
            negative_feedback=negatives.get(d, 0),
        )
        for d in (since + timedelta(days=i) for i in range(days))
    ]
    answered, refused = sum(p.answered for p in per_day), sum(p.refused for p in per_day)
    neg = sum(negatives.values())
    return StatsOut(
        period_days=days,
        questions=answered + refused,
        answered=answered,
        refused=refused,
        refusal_rate=refused / (answered + refused) if answered + refused else None,
        feedback_total=fb_total,
        feedback_negative=neg,
        negative_feedback_rate=neg / fb_total if fb_total else None,
        per_day=per_day,
    )


@router.get("/overdue-documents", response_model=list[DocumentSummary])
def overdue_documents(db: DbSession, user: Manager):
    stmt = (
        select(Document)
        .where(
            document_visibility(user),
            Document.review_date < date.today(),
            Document.status != DocumentStatus.archived,
        )
        .order_by(Document.review_date)
    )
    return db.scalars(stmt).all()
