from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

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


RelationshipType = Literal["event", "preference", "taboo", "promise"]
RelationshipStatus = Literal["active", "done"]


class RelationshipMemory(BaseModel):
    memory_id: str
    user_id: int
    memory_type: RelationshipType
    content: str
    source: str = "chat"
    status: RelationshipStatus = "active"
    confidence: float = 0.8
    created_at: datetime = Field(default_factory=datetime.now)
    due_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


ProfileStatus = Literal["active", "archived"]
ThoughtTraceKind = Literal["chat", "tool", "autonomy", "system"]
GoalStatus = Literal["active", "paused", "achieved", "abandoned", "completed", "cancelled"]
TaskStatus = Literal["todo", "doing", "blocked", "done", "skipped", "cancelled"]
ProgressEventKind = Literal[
    "created",
    "updated",
    "blocked",
    "completed",
    "cancelled",
    "note",
    "decision",
    "sent",
    "ask_owner",
    "rejected",
    "approved",
    "rewritten",
    "silent",
]


class BotProfile(BaseModel):
    profile_id: str
    name: str
    summary: str = ""
    persona: str = ""
    values: list[str] = Field(default_factory=list)
    boundaries: list[str] = Field(default_factory=list)
    current_stage: str = ""
    autonomy_statement: str = ""
    capabilities: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: ProfileStatus = "active"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ThoughtTrace(BaseModel):
    trace_id: str
    trace_kind: ThoughtTraceKind = "chat"
    source: str = ""
    trace_type: str = ""
    summary: str
    input_summary: str = ""
    context_summary: str = ""
    retrieved_summary: str = ""
    decision_summary: str = ""
    output_summary: str = ""
    safety_notes: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    session_id: Optional[str] = None
    related_goal_id: Optional[str] = None
    related_task_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class AutonomyGoal(BaseModel):
    goal_id: str
    title: str
    summary: str = ""
    status: GoalStatus = "active"
    progress: int = 0
    source: str = ""
    scope: str = ""
    priority: int = 0
    reason: str = ""
    owner: str = "bot"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AutonomyTask(BaseModel):
    task_id: str
    goal_id: Optional[str] = None
    title: str
    summary: str = ""
    status: TaskStatus = "todo"
    evidence: str = ""
    next_step: str = ""
    target: str = ""
    priority: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AutonomyProgressEvent(BaseModel):
    event_id: str
    event_kind: ProgressEventKind = "note"
    source: str = ""
    event_type: str = ""
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    goal_id: Optional[str] = None
    task_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
