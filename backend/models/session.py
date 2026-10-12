from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def utcnow() -> datetime:
    # MySQL DATETIME stores naive values; all application timestamps are UTC.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Conversation(Base):
    __tablename__ = "sessions"
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime().with_variant(DATETIME(fsp=6), "mysql"), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime().with_variant(DATETIME(fsp=6), "mysql"), default=utcnow, index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[str | None] = mapped_column(String(36), default="local-admin", nullable=True)
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session_id_id", "session_id", "id"),
                      {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"})

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"))
    created_at: Mapped[datetime] = mapped_column(DateTime().with_variant(DATETIME(fsp=6), "mysql"), default=utcnow)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
