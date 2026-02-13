from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]


class ChatRecord(BaseModel):
    role: Role
    content: str
    nickname: Optional[str] = None
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    time: datetime = Field(default_factory=datetime.now)


class NoteRecord(BaseModel):
    note_id: str
    user_id: int
    title: str
    content: str
    category: str = "default"
    visibility: Literal["private", "shared"] = "private"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class AffinityState(BaseModel):
    user_id: int
    score: int
    updated_at: datetime = Field(default_factory=datetime.now)


class ReminderRecord(BaseModel):
    reminder_id: str
    user_id: int
    group_id: int
    content: str
    remind_time: datetime
