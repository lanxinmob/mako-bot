from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from src.core.config import get_settings
from src.models.schemas import AutonomyGoal, AutonomyProgressEvent, AutonomyTask, BotProfile, ChatRecord, NoteRecord, OutboundMessageRecord, ReminderRecord, RelationshipMemory, ThoughtTrace
from src.services.persistence.backends.redis import get_redis


from src.services.persistence.backends import StorageBackend
from src.services.persistence.history import HistoryRepository
from src.services.persistence.plugin_history import PluginHistoryRepository
from src.services.persistence.outbound import OutboundRepository
from src.services.persistence.profiles import ProfilesRepository
from src.services.persistence.notes import NotesRepository
from src.services.persistence.relationships import RelationshipsRepository
from src.services.persistence.reminders import RemindersRepository
from src.services.persistence.governance import GovernanceRepository
from src.services.persistence.autonomy.traces import TracesRepository
from src.services.persistence.autonomy.goals import GoalsRepository
from src.services.persistence.autonomy.tasks import TasksRepository
from src.services.persistence.autonomy.progress import ProgressRepository
from src.services.persistence.autonomy import normalization


class StorageService:
    def __init__(self) -> None:
        self._backend = StorageBackend(get_settings(), lambda: get_redis())

    @property
    def backend(self):
        # Support callers that construct a service with an injected backend.
        if not hasattr(self, '_backend'):
            self._backend = StorageBackend(initialize=False)
        return self._backend

    @property
    def settings(self):
        return self.backend.settings

    @settings.setter
    def settings(self, value):
        self.backend.settings = value

    @property
    def redis(self):
        return self.backend.redis

    @redis.setter
    def redis(self, value):
        self.backend.redis = value

    def get_history(self, session_id: str) -> List[dict]:
        return HistoryRepository(self.backend).get_history(session_id)

    def save_history(self, session_id: str, messages: List[dict]) -> None:
        return HistoryRepository(self.backend).save_history(session_id, messages)

    def get_plugin_history(self, session_id: str, bot_id: str = "") -> List[dict]:
        return PluginHistoryRepository(self.backend).read(bot_id, session_id)

    def append_global_record(self, record: ChatRecord) -> None:
        return HistoryRepository(self.backend).append_global_record(record)

    def save_reminder(self, reminder: ReminderRecord) -> ReminderRecord:
        return RemindersRepository(self.backend).save_reminder(reminder)

    def get_reminder(self, reminder_id: str) -> Optional[ReminderRecord]:
        return RemindersRepository(self.backend).get_reminder(reminder_id)

    def list_reminders(
        self, session_id: Optional[str]=None, *, user_id: Optional[int]=None,
    ) -> List[ReminderRecord]:
        return RemindersRepository(self.backend).list_reminders(session_id, user_id=user_id)

    def delete_reminder(self, reminder_id: str) -> bool:
        return RemindersRepository(self.backend).delete_reminder(reminder_id)

    def list_global_records(self, limit: int=100) -> List[ChatRecord]:
        return HistoryRepository(self.backend).list_global_records(limit)

    def get_recent_global_records(self, hours: int=24) -> List[ChatRecord]:
        return HistoryRepository(self.backend).get_recent_global_records(hours)

    def record_outbound_message(self, record: OutboundMessageRecord) -> OutboundMessageRecord:
        return OutboundRepository(self.backend).record_outbound_message(record)

    def list_recent_outbound_messages(
        self, target_type: str, target_id: int, *, hours: Optional[int]=None, limit: Optional[int]=None,
        now: Optional[datetime]=None,
    ) -> List[OutboundMessageRecord]:
        return OutboundRepository(self.backend).list_recent_outbound_messages(
            target_type, target_id, hours=hours, limit=limit, now=now,
        )

    def list_sent_news(self) -> set[str]:
        return OutboundRepository(self.backend).list_sent_news()

    def record_sent_news(self, fingerprints: List[str], *, sent_at: Optional[datetime]=None) -> None:
        return OutboundRepository(self.backend).record_sent_news(fingerprints, sent_at=sent_at)

    def get_profile(self, user_id: int) -> Optional[dict]:
        return ProfilesRepository(self.backend).get_profile(user_id)

    def set_profile(self, user_id: int, nickname: str, profile_text: str) -> None:
        return ProfilesRepository(self.backend).set_profile(user_id, nickname, profile_text)

    def list_profiles(self) -> List[dict]:
        return ProfilesRepository(self.backend).list_profiles()

    @staticmethod
    def _parse_profile_payload(raw: str, *, key: str='') -> Optional[dict]:
        return ProfilesRepository._parse_profile_payload(raw, key=key)

    def save_bot_profile(self, profile: BotProfile) -> BotProfile:
        return ProfilesRepository(self.backend).save_bot_profile(profile)

    def add_bot_profile(
        self, name: str, *, summary: str='', persona: str='', capabilities: Optional[List[str]]=None,
        limitations: Optional[List[str]]=None, status: str='active',
    ) -> BotProfile:
        return ProfilesRepository(self.backend).add_bot_profile(
            name, summary=summary, persona=persona, capabilities=capabilities, limitations=limitations,
            status=status,
        )

    def get_bot_profile(self, profile_id: str) -> Optional[BotProfile]:
        return ProfilesRepository(self.backend).get_bot_profile(profile_id)

    def list_bot_profiles(self, *, status: Optional[str]=None, limit: int=50) -> List[BotProfile]:
        return ProfilesRepository(self.backend).list_bot_profiles(status=status, limit=limit)

    def get_affinity(self, user_id: int) -> int:
        return ProfilesRepository(self.backend).get_affinity(user_id)

    def adjust_affinity(self, user_id: int, delta: int) -> int:
        return ProfilesRepository(self.backend).adjust_affinity(user_id, delta)

    def add_note(
        self, user_id: int, title: str, content: str, category: str='default',
        visibility: str='private',
    ) -> NoteRecord:
        return NotesRepository(self.backend).add_note(user_id, title, content, category, visibility)

    def list_notes(self, user_id: int) -> List[NoteRecord]:
        return NotesRepository(self.backend).list_notes(user_id)

    def list_all_notes(self, limit: int=200) -> List[NoteRecord]:
        return NotesRepository(self.backend).list_all_notes(limit)

    def list_long_term_memory_points(self, limit: int=200) -> List[dict]:
        return NotesRepository(self.backend).list_long_term_memory_points(limit)

    def search_notes(self, user_id: int, keyword: str) -> List[NoteRecord]:
        return NotesRepository(self.backend).search_notes(user_id, keyword)

    def delete_note(self, user_id: int, note_id_or_keyword: str) -> bool:
        return NotesRepository(self.backend).delete_note(user_id, note_id_or_keyword)

    def update_note(self, user_id: int, note_id_or_keyword: str, new_content: str) -> Optional[NoteRecord]:
        return NotesRepository(self.backend).update_note(user_id, note_id_or_keyword, new_content)

    def add_relationship_memory(
        self, user_id: int, memory_type: str, content: str, *, source: str='chat',
        confidence: float=0.8, due_at: Optional[datetime]=None,
    ) -> RelationshipMemory:
        return RelationshipsRepository(self.backend).add_relationship_memory(
            user_id, memory_type, content, source=source, confidence=confidence, due_at=due_at,
        )

    def list_relationship_memories(
        self, user_id: int, *, memory_type: Optional[str]=None, status: str='active', limit: int=20,
    ) -> List[RelationshipMemory]:
        return RelationshipsRepository(self.backend).list_relationship_memories(
            user_id, memory_type=memory_type, status=status, limit=limit,
        )

    def get_relationship_memory(self, user_id: int, memory_id: str) -> Optional[RelationshipMemory]:
        return RelationshipsRepository(self.backend).get_relationship_memory(user_id, memory_id)

    def update_relationship_memory(
        self, user_id: int, memory_id: str, content: str,
    ) -> Optional[RelationshipMemory]:
        return RelationshipsRepository(self.backend).update_relationship_memory(user_id, memory_id, content)

    def delete_relationship_memory(self, user_id: int, memory_id: str) -> bool:
        return RelationshipsRepository(self.backend).delete_relationship_memory(user_id, memory_id)

    def mark_relationship_done(self, user_id: int, memory_id: str) -> bool:
        return RelationshipsRepository(self.backend).mark_relationship_done(user_id, memory_id)

    def list_all_relationship_memories(
        self, *, memory_type: Optional[str]=None, status: Optional[str]=None, limit: int=200,
    ) -> List[RelationshipMemory]:
        return RelationshipsRepository(self.backend).list_all_relationship_memories(
            memory_type=memory_type, status=status, limit=limit,
        )

    def save_thought_trace(self, trace: ThoughtTrace) -> ThoughtTrace:
        return TracesRepository(self.backend).save_thought_trace(trace)

    def add_thought_trace(
        self, summary: str, *, trace_kind: str='chat', source: str='', trace_type: str='',
        input_summary: str='', context_summary: str='', retrieved_summary: str='',
        decision_summary: str='', output_summary: str='', safety_notes: str='',
        payload: Optional[dict]=None, user_id: Optional[int]=None, group_id: Optional[int]=None,
        session_id: Optional[str]=None, related_goal_id: Optional[str]=None,
        related_task_id: Optional[str]=None,
    ) -> ThoughtTrace:
        return TracesRepository(self.backend).add_thought_trace(
            summary, trace_kind=trace_kind, source=source, trace_type=trace_type,
            input_summary=input_summary, context_summary=context_summary,
            retrieved_summary=retrieved_summary, decision_summary=decision_summary,
            output_summary=output_summary, safety_notes=safety_notes, payload=payload, user_id=user_id,
            group_id=group_id, session_id=session_id, related_goal_id=related_goal_id,
            related_task_id=related_task_id,
        )

    def append_thought_trace(self, payload: dict) -> ThoughtTrace:
        return TracesRepository(self.backend).append_thought_trace(payload)

    @staticmethod
    def _derive_trace_fields(source: str, trace_type: str, summary: str, payload: dict) -> dict[str, str]:
        return TracesRepository._derive_trace_fields(source, trace_type, summary, payload)

    def get_thought_trace(self, trace_id: str) -> Optional[ThoughtTrace]:
        return TracesRepository(self.backend).get_thought_trace(trace_id)

    def list_thought_traces(
        self, *, trace_kind: Optional[str]=None, user_id: Optional[int]=None, limit: int=100,
    ) -> List[ThoughtTrace]:
        return TracesRepository(self.backend).list_thought_traces(trace_kind=trace_kind, user_id=user_id, limit=limit)

    def save_autonomy_goal(self, goal: AutonomyGoal) -> AutonomyGoal:
        return GoalsRepository(self.backend).save_autonomy_goal(goal)

    def add_autonomy_goal(
        self, title: str, *, summary: str='', status: str='active', priority: int=0, owner: str='bot',
        due_at: Optional[datetime]=None,
    ) -> AutonomyGoal:
        return GoalsRepository(self.backend).add_autonomy_goal(
            title, summary=summary, status=status, priority=priority, owner=owner, due_at=due_at,
        )

    def get_autonomy_goal(self, goal_id: str) -> Optional[AutonomyGoal]:
        return GoalsRepository(self.backend).get_autonomy_goal(goal_id)

    def list_autonomy_goals(self, *, status: Optional[str]=None, limit: int=100) -> List[AutonomyGoal]:
        return GoalsRepository(self.backend).list_autonomy_goals(status=status, limit=limit)

    def save_autonomy_task(self, task: AutonomyTask) -> AutonomyTask:
        return TasksRepository(self.backend).save_autonomy_task(task)

    def add_autonomy_task(
        self, title: str, *, goal_id: Optional[str]=None, summary: str='', status: str='todo',
        priority: int=0, due_at: Optional[datetime]=None,
    ) -> AutonomyTask:
        return TasksRepository(self.backend).add_autonomy_task(
            title, goal_id=goal_id, summary=summary, status=status, priority=priority, due_at=due_at,
        )

    def get_autonomy_task(self, task_id: str) -> Optional[AutonomyTask]:
        return TasksRepository(self.backend).get_autonomy_task(task_id)

    def list_autonomy_tasks(
        self, *, goal_id: Optional[str]=None, status: Optional[str]=None, limit: int=100,
    ) -> List[AutonomyTask]:
        return TasksRepository(self.backend).list_autonomy_tasks(goal_id=goal_id, status=status, limit=limit)

    def save_autonomy_progress_event(self, event: AutonomyProgressEvent) -> AutonomyProgressEvent:
        return ProgressRepository(self.backend).save_autonomy_progress_event(event)

    def get_autonomy_progress_event(self, event_id: str) -> Optional[AutonomyProgressEvent]:
        return ProgressRepository(self.backend).get_autonomy_progress_event(event_id)

    def add_autonomy_progress_event(
        self, summary: str, *, event_kind: str='note', source: str='', event_type: str='',
        payload: Optional[dict]=None, goal_id: Optional[str]=None, task_id: Optional[str]=None,
    ) -> AutonomyProgressEvent:
        return ProgressRepository(self.backend).add_autonomy_progress_event(
            summary, event_kind=event_kind, source=source, event_type=event_type, payload=payload,
            goal_id=goal_id, task_id=task_id,
        )

    def append_progress_event(self, payload: dict) -> AutonomyProgressEvent:
        return ProgressRepository(self.backend).append_progress_event(payload)

    def list_autonomy_progress_events(
        self, *, goal_id: Optional[str]=None, task_id: Optional[str]=None, limit: int=100,
    ) -> List[AutonomyProgressEvent]:
        return ProgressRepository(self.backend).list_autonomy_progress_events(
            goal_id=goal_id, task_id=task_id, limit=limit,
        )

    _parse_datetime = staticmethod(normalization.parse_datetime)

    _optional_int = staticmethod(normalization.optional_int)

    _normalize_progress_event_kind = staticmethod(normalization.normalize_progress_event_kind)

    _normalize_trace_kind = staticmethod(normalization.normalize_trace_kind)

    def list_due_followups(self, now: Optional[datetime]=None, limit: int=20) -> List[RelationshipMemory]:
        return RelationshipsRepository(self.backend).list_due_followups(now, limit)

    def is_user_blacklisted(self, user_id: int) -> bool:
        return GovernanceRepository(self.backend).is_user_blacklisted(user_id)

    def is_group_blacklisted(self, group_id: int) -> bool:
        return GovernanceRepository(self.backend).is_group_blacklisted(group_id)

    def add_user_blacklist(self, user_id: int, reason: str='') -> None:
        return GovernanceRepository(self.backend).add_user_blacklist(user_id, reason)

    def remove_user_blacklist(self, user_id: int) -> None:
        return GovernanceRepository(self.backend).remove_user_blacklist(user_id)

    def add_group_blacklist(self, group_id: int, reason: str='') -> None:
        return GovernanceRepository(self.backend).add_group_blacklist(group_id, reason)

    def remove_group_blacklist(self, group_id: int) -> None:
        return GovernanceRepository(self.backend).remove_group_blacklist(group_id)

    def consume_cost(self, user_id: int, amount: float, *, at: Optional[datetime]=None) -> None:
        return GovernanceRepository(self.backend).consume_cost(user_id, amount, at=at)

    def get_daily_cost(self, user_id: Optional[int]=None, *, at: Optional[datetime]=None) -> float:
        return GovernanceRepository(self.backend).get_daily_cost(user_id, at=at)
