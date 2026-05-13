from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.models.schemas import AutonomyGoal, AutonomyTask, BotProfile, ThoughtTrace
from src.services.storage import StorageService
from src.web.dashboard.schemas import AutonomySummary, DashboardSummary


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

    def _get_bot_profile(self, profile_id: Optional[str]) -> Optional[BotProfile]:
        if profile_id:
            return self.storage.get_bot_profile(profile_id)
        profiles = self.storage.list_bot_profiles(status="active", limit=1)
        if profiles:
            return profiles[0]
        profiles = self.storage.list_bot_profiles(limit=1)
        return profiles[0] if profiles else None

    def get_frontend_summary(self, *, limit: int = 100) -> dict:
        summary = self.get_summary(
            notes_limit=limit,
            profiles_limit=limit,
            relationship_limit=limit,
            thought_trace_limit=limit,
            autonomy_limit=limit,
            recent_records_limit=limit,
        )
        goals = summary.goals or self._default_goals()
        tasks = summary.tasks or self._default_tasks()
        events = summary.events
        traces = summary.thought_traces
        latest_trace = traces[0] if traces else None
        profile = summary.profile or self._default_profile()
        task_tree = self._build_goal_tree(goals, tasks)
        progress_percent = self._calculate_progress(goals, tasks)
        latest_profile = summary.profiles[0] if summary.profiles else {}

        raw = summary.model_dump(mode="json")
        data = dict(raw)
        data.update(
            {
                "progress": {
                    "percent": progress_percent,
                    "label": "自主意志 v1 修行进度",
                    "streak": self._progress_status(goals, tasks),
                    "updated_at": self._format_time(
                        events[0].created_at if events else datetime.now()
                    ),
                },
                "mako_profile": {
                    "name": profile.name,
                    "title": profile.current_stage or "受限自主行动中的茉子",
                    "mood": profile.autonomy_statement or profile.summary or "谨慎观察，必要时向 owner 确认。",
                    "traits": profile.capabilities
                    or profile.values
                    or ["记忆整理", "关系边界", "自主决策审计"],
                },
                "goals": task_tree,
                "recent_progress": [
                    {
                        "time": self._format_time(event.created_at),
                        "title": event.summary,
                        "source": event.source,
                        "event_type": event.event_type or event.event_kind,
                    }
                    for event in events[:12]
                ],
                "user_profile": self._format_user_profile(latest_profile),
                "thinking_summary": self._format_trace(latest_trace),
                "raw": raw,
            }
        )
        return {"ok": True, "data": data}

    def _default_profile(self) -> BotProfile:
        return BotProfile(
            profile_id="mako",
            name="茉子",
            summary="会把聊天、笔记、关系记忆和自主行动记录整理成可审计的手账。",
            persona="忍者手账风格的受限自主助手。",
            values=["谨慎", "透明", "守边界"],
            boundaries=["只信任 owner", "不暴露私聊来源", "不展示隐藏推理链"],
            current_stage="自主意志 v1 建设中",
            autonomy_statement="能行动，也知道不确定时先问一问。",
            capabilities=["记忆沉淀", "目标追踪", "owner 审批", "白名单行动"],
            limitations=["不越过白名单", "中高风险先确认", "高风险沉默"],
        )

    def _default_goals(self) -> list[AutonomyGoal]:
        return [
            AutonomyGoal(
                goal_id="mako-memory-dashboard",
                title="建立可观察的茉子记忆手账",
                summary="展示笔记、用户档案、关系记忆、茉子档案和审计摘要。",
                status="active",
                progress=75,
                source="dashboard",
                scope="memory",
                priority=90,
                reason="让 owner 能看见茉子记得什么、如何更新。",
            ),
            AutonomyGoal(
                goal_id="mako-autonomy-v1",
                title="达成受限自主意志 v1",
                summary="完成白名单、冷却、审批、行动日志、进度事件的闭环。",
                status="active",
                progress=65,
                source="autonomy",
                scope="autonomy",
                priority=100,
                reason="自主行动必须可控、可审计、可回退。",
            ),
        ]

    def _default_tasks(self) -> list[AutonomyTask]:
        return [
            AutonomyTask(
                task_id="task-dashboard-static",
                goal_id="mako-memory-dashboard",
                title="提交服务器可直接服务的静态 dashboard",
                status="done",
                evidence="src/web/dashboard/static",
                priority=90,
            ),
            AutonomyTask(
                task_id="task-dashboard-api",
                goal_id="mako-memory-dashboard",
                title="聚合笔记、档案、关系记忆、思考摘要和进度事件",
                status="done",
                evidence="/mako/dashboard/api/summary",
                priority=85,
            ),
            AutonomyTask(
                task_id="task-owner-token",
                goal_id="mako-memory-dashboard",
                title="使用 DASHBOARD_TOKEN 限制 owner-only 访问",
                status="done",
                next_step="在服务器 .env 配置 DASHBOARD_TOKEN",
                priority=80,
            ),
            AutonomyTask(
                task_id="task-event-loop",
                goal_id="mako-autonomy-v1",
                title="聊天、自主行动、笔记、关系记忆写入进度事件",
                status="doing",
                next_step="持续观察真实运行事件是否完整沉淀",
                priority=95,
            ),
            AutonomyTask(
                task_id="task-reflection",
                goal_id="mako-autonomy-v1",
                title="建立更稳定的反思和目标更新机制",
                status="todo",
                next_step="让事件驱动任务状态自动推进",
                priority=70,
            ),
        ]

    def _build_goal_tree(self, goals: list[AutonomyGoal], tasks: list[AutonomyTask]) -> list[dict]:
        tasks_by_goal: dict[str, list[AutonomyTask]] = {}
        loose_tasks: list[AutonomyTask] = []
        for task in tasks:
            if task.goal_id:
                tasks_by_goal.setdefault(task.goal_id, []).append(task)
            else:
                loose_tasks.append(task)

        tree = []
        for goal in goals:
            goal_tasks = tasks_by_goal.get(goal.goal_id, [])
            tree.append(
                {
                    "id": goal.goal_id,
                    "title": goal.title,
                    "done": goal.status in {"achieved", "completed"},
                    "progress": goal.progress or self._calculate_progress([], goal_tasks),
                    "children": [self._task_to_node(task) for task in goal_tasks],
                }
            )
        for task in loose_tasks:
            tree.append(self._task_to_node(task))
        return tree

    def _task_to_node(self, task: AutonomyTask) -> dict:
        return {
            "id": task.task_id,
            "title": task.title,
            "done": task.status == "done",
            "progress": 100 if task.status == "done" else None,
        }

    def _calculate_progress(self, goals: list[AutonomyGoal], tasks: list[AutonomyTask]) -> int:
        if goals and any(goal.progress for goal in goals):
            return max(0, min(100, round(sum(goal.progress for goal in goals) / len(goals))))
        if not tasks:
            return 0
        done = len([task for task in tasks if task.status == "done"])
        return round(done / len(tasks) * 100)

    def _progress_status(self, goals: list[AutonomyGoal], tasks: list[AutonomyTask]) -> str:
        if goals and all(goal.status in {"achieved", "completed"} for goal in goals):
            return "自主意志 v1 达成"
        blocked = len([task for task in tasks if task.status == "blocked"])
        doing = len([task for task in tasks if task.status == "doing"])
        if blocked:
            return f"{blocked} 个阻塞项待处理"
        if doing:
            return f"{doing} 个任务正在推进"
        return "等待下一次进展事件"

    def _format_user_profile(self, profile: dict) -> dict:
        text = profile.get("profile_text") or ""
        preferences = []
        for line in str(text).splitlines():
            if line.startswith("偏好:"):
                preferences = [item.strip() for item in line.removeprefix("偏好:").split("；") if item.strip()]
        return {
            "name": profile.get("nickname") or profile.get("user_id") or "旅人",
            "focus": str(text).splitlines()[0] if text else "还没有写入档案",
            "preferences": preferences,
        }

    def _format_trace(self, trace: Optional[ThoughtTrace]) -> str:
        if not trace:
            return ""
        pieces = [
            trace.summary,
            trace.context_summary,
            trace.retrieved_summary,
            trace.decision_summary,
            trace.output_summary,
            trace.safety_notes,
        ]
        return "\n".join(piece for piece in pieces if piece).strip()

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M")
