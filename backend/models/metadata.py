"""Local administrator identity and persisted document/evaluation metadata."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.session import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentRecord(Base):
    __tablename__ = "documents"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), default="local-admin")
    size_bytes: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    index_status: Mapped[str] = mapped_column(String(16), default="pending")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), default="local-admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    mode: Mapped[str] = mapped_column(String(16))
    dataset: Mapped[str] = mapped_column(String(512))
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary_json: Mapped[str] = mapped_column(Text)
