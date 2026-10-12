from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.cache import RecentHistoryCache, get_recent_history_cache
from backend.models import Conversation, Message
from backend.models.session import utcnow
from backend.schemas.session import SessionDetail, SessionSummary, StoredMessage
from backend.services.agent_service import AgentService


class SessionNotFoundError(Exception):
    pass


class SessionConflictError(Exception):
    pass


class SessionService:
    def __init__(self, db: Session, cache: RecentHistoryCache | None = None):
        self.db = db
        self.cache = cache if cache is not None else get_recent_history_cache()

    def _get(self, session_id: str) -> Conversation:
        conversation = self.db.get(Conversation, session_id)
        if conversation is None:
            raise SessionNotFoundError
        return conversation

    def list(self, limit: int, offset: int) -> list[SessionSummary]:
        rows = self.db.scalars(select(Conversation).order_by(
            Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit).offset(offset)).all()
        return [SessionSummary.model_validate(row) for row in rows]

    def detail(self, session_id: str) -> SessionDetail:
        conversation = self._get(session_id)
        messages = self.db.scalars(select(Message).where(Message.session_id == session_id).order_by(Message.id)).all()
        return SessionDetail(**SessionSummary.model_validate(conversation).model_dump(),
                             messages=[StoredMessage.model_validate(row) for row in messages])

    def delete(self, session_id: str) -> None:
        self.db.delete(self._get(session_id))
        self.db.commit()
        if self.cache:
            self.cache.delete(session_id)

    def chat(self, message: str, session_id: str | None, agent: AgentService) -> tuple[str, str]:
        history, version = self.prepare_chat(session_id)
        answer = agent.chat(message, history)
        return self.save_chat(message, session_id, version, answer)

    def prepare_chat(self, session_id: str | None) -> tuple[list[dict[str, str]], int | None]:
        # Fail before spending tokens if storage or its schema is unavailable.
        self.db.execute(select(Conversation.id).limit(1))
        if session_id is None:
            self.db.rollback()
            return [], None
        if self.cache:
            version = self._get(session_id).version
            self.db.rollback()
            history = self.cache.get(session_id, version)
            if history is not None:
                return history, version
            # Cache I/O ran outside the transaction; another writer may have
            # committed since the first version check.
        version = self._get(session_id).version
        rows = self.db.scalars(select(Message).where(Message.session_id == session_id)
                               .order_by(Message.id.desc()).limit(100)).all()
        history = [{"role": row.role, "content": row.content} for row in reversed(rows)]
        # End the read transaction before Redis I/O and slow LLM/tool work.
        self.db.rollback()
        if self.cache:
            self.cache.set(session_id, version, history)
        return history, version

    def save_chat(self, message: str, session_id: str | None, version: int | None,
                  answer: str) -> tuple[str, str]:
        try:
            if session_id is None:
                conversation = Conversation(title=message[:100])
                self.db.add(conversation)
                self.db.flush()
                session_id = conversation.id
            else:
                result = self.db.execute(update(Conversation).where(
                    Conversation.id == session_id, Conversation.version == version
                ).values(version=Conversation.version + 1, updated_at=utcnow())
                  .execution_options(synchronize_session=False))
                if result.rowcount != 1:
                    self.db.rollback()
                    self.db.expire_all()
                    self._get(session_id)
                    raise SessionConflictError
            self.db.add_all([
                Message(session_id=session_id, role="user", content=message),
                Message(session_id=session_id, role="assistant", content=answer),
            ])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        if self.cache:
            self.cache.delete(session_id)
        return answer, session_id
