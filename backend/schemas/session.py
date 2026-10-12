from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class TimestampModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("created_at", "updated_at", check_fields=False)
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class SessionSummary(TimestampModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class StoredMessage(TimestampModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class SessionDetail(SessionSummary):
    messages: list[StoredMessage]
