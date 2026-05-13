from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.models.schemas import (
    AutonomyGoal,
    AutonomyProgressEvent,
    AutonomyTask,
    BotProfile,
    ChatRecord,
    NoteRecord,
    RelationshipMemory,
    ThoughtTrace,
)


class AutonomySummary(BaseModel):
    goals: list[AutonomyGoal] = Field(default_factory=list)
    tasks: list[AutonomyTask] = Field(default_factory=list)
    events: list[AutonomyProgressEvent] = Field(default_factory=list)


class DashboardSummary(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.now)
    profile: Optional[BotProfile] = None
    notes: list[NoteRecord] = Field(default_factory=list)
    profiles: list[dict] = Field(default_factory=list)
    relationship_memories: list[RelationshipMemory] = Field(default_factory=list)
    thought_traces: list[ThoughtTrace] = Field(default_factory=list)
    goals: list[AutonomyGoal] = Field(default_factory=list)
    tasks: list[AutonomyTask] = Field(default_factory=list)
    events: list[AutonomyProgressEvent] = Field(default_factory=list)
    autonomy: AutonomySummary = Field(default_factory=AutonomySummary)
    recent_records: list[ChatRecord] = Field(default_factory=list)
