from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: MessageText
    session_id: UUID | None = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    trace_id: str
