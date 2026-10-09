"""Anonymous chat-side data. None of these tables has a user id, by design (LGPD):
the manager dashboard can only ever see aggregates."""

import enum
from datetime import date

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.chunk import EMBEDDING_DIM


class GapOrigin(str, enum.Enum):
    sem_evidencia = "sem_evidencia"
    feedback_negativo = "feedback_negativo"


class Gap(Base):
    """A question the documentation could not answer."""

    __tablename__ = "gaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    day: Mapped[date] = mapped_column(Date, index=True)  # day only, no time of day
    origin: Mapped[GapOrigin] = mapped_column(Enum(GapOrigin, name="gap_origin"))


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    helpful: Mapped[bool] = mapped_column(Boolean)
    comment: Mapped[str | None] = mapped_column(String(500))


class UsageDaily(Base):
    """Per-day counters; the only usage record kept (no conversations are stored)."""

    __tablename__ = "usage_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    answered: Mapped[int] = mapped_column(Integer, default=0)
    refused: Mapped[int] = mapped_column(Integer, default=0)
