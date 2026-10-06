from __future__ import annotations

from typing import Optional

from src.models.schemas import BotProfile
from src.services.persistence import StorageService

# Keep the existing constant exports during the staged dashboard refactor.
from src.web.dashboard.roadmap.catalog import ROADMAP_GROUPS, ROADMAP_TASK_TITLES
from src.web.dashboard.roadmap.defaults import (
    BLOCKED_TASKS,
    DOING_TASKS,
    DONE_TASKS,
    STATUS_LABELS,
)
from src.web.dashboard.roadmap.evidence import (
    BLOCKED_REASON_OVERRIDES,
    GROUP_CRITERIA_TEMPLATES,
    GROUP_IMPLEMENTATION_BASIS,
    TASK_EVIDENCE_OVERRIDES,
)
from src.web.dashboard.schemas import AutonomySummary, DashboardSummary


from src.web.dashboard.presenters.profile import (
    _default_profile,
    _format_mako_profile,
)
from src.web.dashboard.presenters.memory import (
    _format_notes,
    _format_long_term_memory,
    _format_relationship_memory,
)
from src.web.dashboard.presenters.people import (
    _format_people,
    _first_profile_line,
    _extract_profile_section,
    _profile_tags,
    _optional_int,
)
from src.web.dashboard.presenters.traces import (
    _format_traces,
    _format_trace_record,
    _trace_title,
    _trigger_source_label,
    _trace_target_label,
    _payload_input_summary,
    _payload_context_summary,
    _payload_retrieved_summary,
    _payload_decision_summary,
    _payload_output_summary,
    _safe_trace_payload,
    _split_summary,
    _format_trace,
)
from src.web.dashboard.roadmap.progress import (
    _roadmap_groups,
    _progress,
    _format_recent_progress,
    _calculate_task_progress,
    _format_time,
)
from src.web.dashboard.roadmap.tasks import (
    _default_goals,
    _roadmap_tasks,
    _build_goal_tree,
    _task_to_node,
    _task_id,
    _default_task_status,
    _task_summary,
    _task_detail_summary,
    _next_step_for_status,
    _next_step_for_task,
    _completion_criteria,
    _completion_basis,
    _task_evidence,
    _why_status,
    _verification_for_task,
)


class DashboardService:
    def __init__(self, storage: Optional[StorageService] = None) -> None:
        self.storage = storage or StorageService()


    def get_summary(
        self,
        *,
        bot_profile_id: Optional[str] = None,
        notes_limit: int = 100,
        profiles_limit: int = 100,
        relationship_limit: int = 100,
        thought_trace_limit: int = 100,
        autonomy_limit: int = 100,
        recent_records_limit: int = 100,
    ) -> DashboardSummary:
        bot_profile = self._get_bot_profile(bot_profile_id)
        profiles = self.storage.list_profiles()[:profiles_limit]
        goals = self.storage.list_autonomy_goals(limit=autonomy_limit)
        tasks = self.storage.list_autonomy_tasks(limit=autonomy_limit)
        events = self.storage.list_autonomy_progress_events(limit=autonomy_limit)

        return DashboardSummary(
            profile=bot_profile,
            notes=self.storage.list_all_notes(limit=notes_limit),
            profiles=profiles,
            relationship_memories=self.storage.list_all_relationship_memories(limit=relationship_limit),
            thought_traces=self.storage.list_thought_traces(limit=thought_trace_limit),
            goals=goals,
            tasks=tasks,
            events=events,
            autonomy=AutonomySummary(goals=goals, tasks=tasks, events=events),
            recent_records=self.storage.list_global_records(limit=recent_records_limit),
        )


    def get_frontend_summary(self, *, limit: int = 200) -> dict:
        summary = self.get_summary(
            notes_limit=limit,
            profiles_limit=limit,
            relationship_limit=limit,
            thought_trace_limit=limit,
            autonomy_limit=max(limit, 100),
            recent_records_limit=limit,
        )
        profile = summary.profile or self._default_profile()
        roadmap_tasks = self._roadmap_tasks(summary.goals, summary.tasks, summary.events)
        roadmap_groups = self._roadmap_groups(roadmap_tasks)
        progress = self._progress(roadmap_tasks, summary.events)
        notes = self._format_notes(summary.notes)
        long_term_memory = self._format_long_term_memory(self.storage.list_long_term_memory_points(limit=limit))
        people = self._format_people(summary.profiles, summary.relationship_memories)
        thought_traces = self._format_traces(summary.thought_traces)
        recent_progress = self._format_recent_progress(summary.events)
        mako_profile = self._format_mako_profile(profile, roadmap_tasks, summary.thought_traces)

        data = summary.model_dump(mode="json")
        data.update(
            {
                "overview": {
                    "progress_percent": progress["percent"],
                    "status_label": progress["streak"],
                    "updated_at": progress["updated_at"],
                    "counts": {
                        "notes": len(notes) + len(long_term_memory),
                        "people": len(people),
                        "relationship_memories": len(summary.relationship_memories),
                        "thought_traces": len(thought_traces),
                        "roadmap_tasks": len(roadmap_tasks),
                    },
                },
                "progress": progress,
                "mako_profile": mako_profile,
                "mako_psych_profile": mako_profile,
                "notes": notes,
                "memory_notes": notes + long_term_memory,
                "long_term_memory": long_term_memory,
                "people": people,
                "user_profiles": {"items": people, "latest": people[0] if people else None, "total": len(people)},
                "relationship_memories": [
                    self._format_relationship_memory(memory) for memory in summary.relationship_memories
                ],
                "thought_traces": thought_traces,
                "thinking_summary": thought_traces[0]["summary"] if thought_traces else "",
                "roadmap_tasks": roadmap_tasks,
                "roadmap_groups": roadmap_groups,
                "autonomy": {
                    "goals": [goal.model_dump(mode="json") for goal in summary.goals],
                    "tasks": [task.model_dump(mode="json") for task in summary.tasks],
                    "events": [event.model_dump(mode="json") for event in summary.events],
                    "tree": self._build_goal_tree(summary.goals or self._default_goals(), summary.tasks),
                    "recent_progress": recent_progress,
                },
                "goals": self._build_goal_tree(summary.goals or self._default_goals(), summary.tasks),
                "recent_progress": recent_progress,
                "raw": summary.model_dump(mode="json"),
            }
        )
        return {"ok": True, "data": data}


    def _get_bot_profile(self, profile_id: Optional[str]) -> Optional[BotProfile]:
        if profile_id:
            return self.storage.get_bot_profile(profile_id)
        profiles = self.storage.list_bot_profiles(status="active", limit=1)
        if profiles:
            return profiles[0]
        profiles = self.storage.list_bot_profiles(limit=1)
        return profiles[0] if profiles else None


    # Explicit compatibility entry points for the staged refactor.
    # Keep until callers migrate; implementations live in their domain modules.
    _default_profile = staticmethod(_default_profile)
    _format_mako_profile = staticmethod(_format_mako_profile)
    _format_notes = staticmethod(_format_notes)
    _format_long_term_memory = staticmethod(_format_long_term_memory)
    _format_relationship_memory = staticmethod(_format_relationship_memory)
    _format_people = staticmethod(_format_people)
    _first_profile_line = staticmethod(_first_profile_line)
    _extract_profile_section = staticmethod(_extract_profile_section)
    _profile_tags = staticmethod(_profile_tags)
    _optional_int = staticmethod(_optional_int)
    _format_traces = staticmethod(_format_traces)
    _format_trace_record = staticmethod(_format_trace_record)
    _trace_title = staticmethod(_trace_title)
    _trigger_source_label = staticmethod(_trigger_source_label)
    _trace_target_label = staticmethod(_trace_target_label)
    _payload_input_summary = staticmethod(_payload_input_summary)
    _payload_context_summary = staticmethod(_payload_context_summary)
    _payload_retrieved_summary = staticmethod(_payload_retrieved_summary)
    _payload_decision_summary = staticmethod(_payload_decision_summary)
    _payload_output_summary = staticmethod(_payload_output_summary)
    _safe_trace_payload = staticmethod(_safe_trace_payload)
    _split_summary = staticmethod(_split_summary)
    _format_trace = staticmethod(_format_trace)
    _roadmap_groups = staticmethod(_roadmap_groups)
    _progress = staticmethod(_progress)
    _format_recent_progress = staticmethod(_format_recent_progress)
    _calculate_task_progress = staticmethod(_calculate_task_progress)
    _format_time = staticmethod(_format_time)
    _default_goals = staticmethod(_default_goals)
    _roadmap_tasks = staticmethod(_roadmap_tasks)
    _build_goal_tree = staticmethod(_build_goal_tree)
    _task_to_node = staticmethod(_task_to_node)
    _task_id = staticmethod(_task_id)
    _default_task_status = staticmethod(_default_task_status)
    _task_summary = staticmethod(_task_summary)
    _task_detail_summary = staticmethod(_task_detail_summary)
    _next_step_for_status = staticmethod(_next_step_for_status)
    _next_step_for_task = staticmethod(_next_step_for_task)
    _completion_criteria = staticmethod(_completion_criteria)
    _completion_basis = staticmethod(_completion_basis)
    _task_evidence = staticmethod(_task_evidence)
    _why_status = staticmethod(_why_status)
    _verification_for_task = staticmethod(_verification_for_task)
