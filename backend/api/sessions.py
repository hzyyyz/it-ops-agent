from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.schemas.session import SessionDetail, SessionSummary
from backend.services.session_service import SessionService


router = APIRouter(prefix="/api/sessions", tags=["sessions"])
Database = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[SessionSummary])
def list_sessions(db: Database, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                  offset: Annotated[int, Query(ge=0)] = 0):
    return SessionService(db).list(limit, offset)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: UUID, db: Database):
    return SessionService(db).detail(str(session_id))


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: UUID, db: Database):
    SessionService(db).delete(str(session_id))
    return Response(status_code=204)
