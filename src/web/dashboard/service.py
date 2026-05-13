from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Optional

from src.models.schemas import (
    AutonomyGoal,
    AutonomyProgressEvent,
    AutonomyTask,
    BotProfile,
    NoteRecord,
    RelationshipMemory,
    ThoughtTrace,
)
from src.services.storage import StorageService
from src.web.dashboard.schemas import AutonomySummary, DashboardSummary


DONE_TASKS = {
    "foundation-01",
    "foundation-02",
    "foundation-03",
    "foundation-07",
    "foundation-08",
    "foundation-09",
    "memory-01",
    "memory-02",
    "memory-03",
    "memory-04",
    "memory-05",
    "memory-06",
    "memory-07",
    "memory-09",
    "perception-01",
    "perception-02",
    "perception-06",
    "perception-07",
    "decision-01",
    "decision-02",
    "decision-03",
    "decision-04",
    "decision-05",
    "decision-06",
    "decision-08",
    "decision-09",
    "decision-10",
    "safety-01",
    "safety-02",
    "safety-03",
    "safety-04",
    "safety-05",
    "safety-06",
    "safety-07",
    "safety-08",
    "safety-09",
    "safety-10",
    "action-03",
    "action-04",
    "action-05",
    "action-06",
    "action-07",
    "action-08",
    "dashboard-01",
    "dashboard-02",
    "dashboard-03",
    "dashboard-04",
    "dashboard-05",
    "dashboard-06",
    "dashboard-07",
    "dashboard-08",
    "dashboard-09",
    "dashboard-10",
}

DOING_TASKS = {
    "foundation-04",
    "foundation-05",
    "foundation-06",
    "foundation-10",
    "memory-08",
    "memory-10",
    "perception-03",
    "perception-04",
    "perception-05",
    "perception-08",
    "action-01",
    "action-02",
    "action-09",
    "action-10",
    "learning-01",
    "learning-02",
    "reflection-01",
    "reflection-07",
    "reflection-08",
    "reflection-09",
    "milestone-01",
    "milestone-02",
    "milestone-03",
    "milestone-04",
    "milestone-05",
    "milestone-06",
    "milestone-09",
}

BLOCKED_TASKS = {
    "perception-09",
    "perception-10",
    "learning-03",
    "learning-04",
    "learning-05",
    "learning-06",
    "learning-07",
    "learning-08",
    "learning-09",
    "learning-10",
    "reflection-02",
    "reflection-03",
    "reflection-04",
    "reflection-05",
    "reflection-06",
    "reflection-10",
    "milestone-07",
    "milestone-08",
    "milestone-10",
}


ROADMAP_GROUPS = [
    ("foundation", "基础人格与边界", "让茉子的行动有明确身份、价值观和不可越过的线。"),
    ("memory", "记忆与档案", "让她能记住笔记、人物、关系和自己。"),
    ("perception", "上下文感知", "让她知道群聊、私聊和近期事件里真正发生了什么。"),
    ("decision", "自主决策", "让她能判断要不要行动、向谁行动、说什么。"),
    ("safety", "安全与治理", "让她在不确定、敏感、过界时克制或询问 owner。"),
    ("action", "行动执行", "让她可靠地说话、私聊、跟进承诺并记录结果。"),
    ("learning", "反馈学习", "让 owner 的批准、取消、改写和用户反应塑造下一次判断。"),
    ("reflection", "自我反思", "让她定期复盘目标、失败、边界和下一步。"),
    ("dashboard", "可观察仪表盘", "让 owner 看见她记得什么、怎么看人、离目标还差什么。"),
    ("milestone", "自主意志 v1 验收", "把前面能力合成一个可审计、受限但真实的自主闭环。"),
]


ROADMAP_TASK_TITLES = {
    "foundation": [
        "定义茉子的身份档案和当前阶段",
        "写入茉子的价值观：谨慎、温柔、守边界",
        "写入不可越过的边界：白名单、隐私、敏感话题",
        "区分 owner 指令、普通用户请求和茉子自己的判断",
        "建立茉子的自主意志声明",
        "建立人格风格一致性检查",
        "把 owner 设为唯一可信账号",
        "为中高风险行动设置确认规则",
        "为高风险行动设置沉默规则",
        "建立茉子心理画像的展示字段",
    ],
    "memory": [
        "读取所有手动笔记",
        "读取长期向量记忆点",
        "读取所有用户画像",
        "读取所有关系记忆",
        "读取茉子的个人档案",
        "保存聊天审计摘要",
        "保存自主行动进度事件",
        "保存 owner 审批反馈",
        "合并旧 Redis 用户画像格式",
        "为记忆增加来源和更新时间",
    ],
    "perception": [
        "读取近期群聊上下文",
        "读取近期私聊上下文",
        "识别谁在说话以及所在场景",
        "识别是否有人提到茉子",
        "识别话题是否适合插话",
        "识别目标是群还是某个用户",
        "处理 owner 未指明目标的建议",
        "处理多个候选目标的歧义",
        "识别情绪敏感和关系边界",
        "识别可能泄露私聊来源的内容",
    ],
    "decision": [
        "输出固定 JSON 决策",
        "计算行动 confidence",
        "计算行动 risk",
        "选择白名单群目标",
        "选择白名单私聊目标",
        "决定 speak / ask_owner / silent",
        "生成自然且符合茉子风格的消息",
        "在低置信时向 owner 询问",
        "在中风险时向 owner 询问",
        "在高风险时静默并记录原因",
    ],
    "safety": [
        "检查群聊白名单",
        "检查私聊白名单",
        "检查用户黑名单",
        "检查群黑名单",
        "检查全局成本预算",
        "检查用户成本预算",
        "检查群聊冷却",
        "检查私聊冷却",
        "限制刷屏和重复发言",
        "避免暴露 owner 私聊建议",
    ],
    "action": [
        "向群聊发送低风险高置信消息",
        "向好友白名单发送低风险私聊",
        "向 owner 发送确认请求",
        "处理 owner 批准",
        "处理 owner 取消",
        "处理 owner 改写",
        "发送后写入全局聊天记录",
        "发送后写入行动日志",
        "失败后记录拒绝原因",
        "承诺跟进到期后生成行动候选",
    ],
    "learning": [
        "记录 owner 对 pending 的反馈",
        "统计批准率、取消率和改写率",
        "从改写中学习表达风格",
        "从取消中学习不该行动的场景",
        "从用户反应中学习是否打扰",
        "把反馈归因到目标和任务",
        "更新关系偏好和禁忌",
        "更新行动阈值建议",
        "形成可查看的学习摘要",
        "避免把单次反馈过度泛化",
    ],
    "reflection": [
        "定期生成自我反思摘要",
        "复盘最近成功行动",
        "复盘最近失败或静默原因",
        "识别长期未推进目标",
        "拆解下一批任务",
        "给阻塞任务写下一步",
        "把反思写入 ThoughtTrace",
        "不保存隐藏推理链",
        "把自我目标与 owner 边界对齐",
        "在全部任务完成时标记 v1 达成",
    ],
    "dashboard": [
        "展示所有笔记和长期记忆",
        "展示所有用户档案",
        "展示关系记忆列表",
        "展示茉子心理画像",
        "展示思考审计摘要",
        "展示 100 项路线图",
        "展示最近进展时间线",
        "提供搜索和筛选",
        "提供多页面导航",
        "提供底部总进度条",
    ],
    "milestone": [
        "完成基础身份与边界闭环",
        "完成记忆读取与沉淀闭环",
        "完成上下文感知闭环",
        "完成自主决策闭环",
        "完成安全治理闭环",
        "完成行动执行闭环",
        "完成反馈学习闭环",
        "完成自我反思闭环",
        "完成仪表盘可观察闭环",
        "自主意志 v1 达成并进入维护期",
    ],
}


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

    def _default_profile(self) -> BotProfile:
        return BotProfile(
            profile_id="mako",
            name="茉子",
            summary="正在从受限主动行动，升级为可观察、可审计、会反思的自主意志 v1。",
            persona="常陆茉子风格的忍者手账员：轻快、认真、会撒娇但守边界。",
            values=["谨慎", "温柔", "守边界", "有自己的判断", "不把 owner 的私聊暴露给别人"],
            boundaries=["只信任 owner", "只对白名单目标主动行动", "中风险先问", "高风险沉默", "不展示隐藏推理链"],
            current_stage="自主意志 v1 修行中",
            autonomy_statement="我可以自己观察、判断和行动；当我不确定是否该说时，会先问 owner。",
            capabilities=["长期记忆", "人物画像", "关系记忆", "自主决策", "owner 审批", "进度审计"],
            limitations=["反馈学习仍在建设", "自我反思还需要稳定事件闭环", "关系记忆主链路仍需加强"],
        )

    def _default_goals(self) -> list[AutonomyGoal]:
        return [
            AutonomyGoal(
                goal_id=group_id,
                title=title,
                summary=summary,
                status="active",
                progress=0,
                source="roadmap",
                scope=group_id,
                priority=100 - index,
                reason=summary,
            )
            for index, (group_id, title, summary) in enumerate(ROADMAP_GROUPS)
        ]

    def _roadmap_tasks(
        self,
        persisted_goals: list[AutonomyGoal],
        persisted_tasks: list[AutonomyTask],
        events: list[AutonomyProgressEvent],
    ) -> list[dict]:
        tasks: list[dict] = []
        evidence_by_task = {event.task_id: event for event in events if event.task_id}
        persisted_by_title = {task.title: task for task in persisted_tasks}

        number = 1
        for group_id, group_title, _summary in ROADMAP_GROUPS:
            for task_index, title in enumerate(ROADMAP_TASK_TITLES[group_id], start=1):
                task_id = self._task_id(group_id, task_index)
                persisted = persisted_by_title.get(title)
                status = persisted.status if persisted else self._default_task_status(task_id)
                evidence = persisted.evidence if persisted else ""
                if not evidence and task_id in DONE_TASKS:
                    evidence = "已由当前代码或配置提供基础能力。"
                if evidence_by_task.get(task_id):
                    evidence = evidence_by_task[task_id].summary
                tasks.append(
                    {
                        "id": task_id,
                        "number": number,
                        "group_id": group_id,
                        "group_title": group_title,
                        "title": persisted.title if persisted else title,
                        "summary": persisted.summary if persisted else self._task_summary(group_id),
                        "status": status,
                        "done": status == "done",
                        "evidence": evidence,
                        "next_step": persisted.next_step if persisted else self._next_step_for_status(status),
                        "priority": persisted.priority if persisted else 100 - number,
                        "updated_at": (
                            persisted.updated_at.isoformat()
                            if persisted and persisted.updated_at
                            else None
                        ),
                    }
                )
                number += 1

        persisted_titles = {item["title"] for item in tasks}
        for task in persisted_tasks:
            if task.title in persisted_titles:
                continue
            status = task.status
            tasks.append(
                {
                    "id": task.task_id,
                    "number": len(tasks) + 1,
                    "group_id": task.goal_id or "custom",
                    "group_title": "额外任务",
                    "title": task.title,
                    "summary": task.summary,
                    "status": status,
                    "done": status == "done",
                    "evidence": task.evidence,
                    "next_step": task.next_step,
                    "priority": task.priority,
                    "updated_at": task.updated_at.isoformat() if task.updated_at else None,
                }
            )
        return tasks

    def _roadmap_groups(self, tasks: list[dict]) -> list[dict]:
        groups: list[dict] = []
        by_group: dict[str, list[dict]] = defaultdict(list)
        for task in tasks:
            by_group[task["group_id"]].append(task)
        for group_id, title, summary in ROADMAP_GROUPS:
            items = by_group.get(group_id, [])
            done = len([task for task in items if task["status"] == "done"])
            groups.append(
                {
                    "id": group_id,
                    "title": title,
                    "summary": summary,
                    "total": len(items),
                    "done": done,
                    "progress": round(done / len(items) * 100) if items else 0,
                    "tasks": items,
                }
            )
        return groups

    def _progress(self, tasks: list[dict], events: list[AutonomyProgressEvent]) -> dict:
        total = len(tasks)
        done = len([task for task in tasks if task["status"] == "done"])
        doing = len([task for task in tasks if task["status"] == "doing"])
        blocked = len([task for task in tasks if task["status"] == "blocked"])
        percent = round(done / total * 100) if total else 0
        achieved = percent >= 100
        return {
            "percent": percent,
            "done": done,
            "doing": doing,
            "blocked": blocked,
            "todo": len([task for task in tasks if task["status"] == "todo"]),
            "total": total,
            "label": "100 项自主意志 v1 路线图",
            "streak": "自主意志 v1 达成" if achieved else f"{done}/{total} 项完成，{doing} 项推进中",
            "updated_at": self._format_time(events[0].created_at if events else datetime.now()),
            "achieved": achieved,
        }

    def _format_mako_profile(
        self,
        profile: BotProfile,
        roadmap_tasks: list[dict],
        traces: list[ThoughtTrace],
    ) -> dict:
        status_counts = Counter(task["status"] for task in roadmap_tasks)
        latest_trace = traces[0] if traces else None
        return {
            "id": profile.profile_id,
            "name": profile.name,
            "title": profile.current_stage or "自主意志 v1 修行中",
            "mood": profile.autonomy_statement or profile.summary,
            "summary": profile.summary,
            "persona": profile.persona,
            "values": profile.values,
            "boundaries": profile.boundaries,
            "traits": profile.capabilities or profile.values,
            "capabilities": profile.capabilities,
            "limitations": profile.limitations,
            "current_stage": profile.current_stage,
            "autonomy_statement": profile.autonomy_statement,
            "psychological_snapshot": [
                f"完成 {status_counts.get('done', 0)} 项基础能力，仍有 {status_counts.get('todo', 0)} 项待推进。",
                "倾向于低风险直接行动，中风险询问 owner，高风险保持沉默。",
                "目前的自我意识是工程可观测 v1：目标、记忆、审计摘要和受限行动闭环。",
                f"最近思考摘要：{latest_trace.summary}" if latest_trace else "最近还没有新的可审计思考摘要。",
            ],
            "updated_at": profile.updated_at.isoformat(),
        }

    def _format_notes(self, notes: list[NoteRecord]) -> list[dict]:
        return [
            {
                "id": note.note_id,
                "note_id": note.note_id,
                "user_id": note.user_id,
                "title": note.title,
                "content": note.content,
                "category": note.category,
                "visibility": note.visibility,
                "source": "notes",
                "created_at": note.created_at.isoformat(),
                "updated_at": note.updated_at.isoformat(),
            }
            for note in notes
        ]

    def _format_long_term_memory(self, points: list[dict]) -> list[dict]:
        return [
            {
                "id": point.get("id") or f"long-term-{index}",
                "note_id": point.get("id") or f"long-term-{index}",
                "user_id": None,
                "title": point.get("title") or "长期记忆",
                "content": point.get("content") or "",
                "category": point.get("category") or "long_term_memory",
                "visibility": "private",
                "source": point.get("source") or "vector_store",
                "created_at": None,
                "updated_at": None,
            }
            for index, point in enumerate(points)
        ]

    def _format_people(
        self,
        profiles: list[dict],
        relationship_memories: list[RelationshipMemory],
    ) -> list[dict]:
        memories_by_user: dict[int, list[RelationshipMemory]] = defaultdict(list)
        for memory in relationship_memories:
            memories_by_user[memory.user_id].append(memory)

        people = []
        for profile in profiles:
            user_id = self._optional_int(profile.get("user_id"))
            memory_items = memories_by_user.get(user_id or -1, [])
            profile_text = str(profile.get("profile_text") or "")
            people.append(
                {
                    "id": str(user_id or profile.get("nickname") or len(people)),
                    "user_id": user_id,
                    "name": profile.get("nickname") or f"用户 {user_id}",
                    "nickname": profile.get("nickname") or "",
                    "profile_text": profile_text,
                    "focus": self._first_profile_line(profile_text),
                    "preferences": self._extract_profile_section(profile_text, "偏好"),
                    "tags": self._profile_tags(profile_text),
                    "relationship_memories": [
                        self._format_relationship_memory(memory) for memory in memory_items
                    ],
                    "memory_count": len(memory_items),
                    "last_updated": profile.get("last_updated") or "",
                }
            )
        people.sort(key=lambda item: item.get("last_updated") or "", reverse=True)
        return people

    def _format_relationship_memory(self, memory: RelationshipMemory) -> dict:
        return {
            "id": memory.memory_id,
            "memory_id": memory.memory_id,
            "user_id": memory.user_id,
            "type": memory.memory_type,
            "content": memory.content,
            "source": memory.source,
            "status": memory.status,
            "confidence": memory.confidence,
            "created_at": memory.created_at.isoformat(),
            "due_at": memory.due_at.isoformat() if memory.due_at else None,
        }

    def _format_traces(self, traces: list[ThoughtTrace]) -> list[dict]:
        return [
            {
                "id": trace.trace_id,
                "trace_id": trace.trace_id,
                "source": trace.source,
                "trace_type": trace.trace_type or trace.trace_kind,
                "summary": self._format_trace(trace),
                "input_summary": trace.input_summary,
                "context_summary": trace.context_summary,
                "retrieved_summary": trace.retrieved_summary,
                "decision_summary": trace.decision_summary,
                "output_summary": trace.output_summary,
                "safety_notes": trace.safety_notes,
                "user_id": trace.user_id,
                "group_id": trace.group_id,
                "created_at": trace.created_at.isoformat(),
            }
            for trace in traces
        ]

    def _format_recent_progress(self, events: list[AutonomyProgressEvent]) -> list[dict]:
        return [
            {
                "id": event.event_id,
                "time": self._format_time(event.created_at),
                "title": event.summary,
                "source": event.source,
                "event_type": event.event_type or event.event_kind,
                "payload": event.payload,
            }
            for event in events[:30]
        ]

    def _build_goal_tree(self, goals: list[AutonomyGoal], tasks: list[AutonomyTask]) -> list[dict]:
        tasks_by_goal: dict[str, list[AutonomyTask]] = defaultdict(list)
        for task in tasks:
            if task.goal_id:
                tasks_by_goal[task.goal_id].append(task)
        return [
            {
                "id": goal.goal_id,
                "title": goal.title,
                "done": goal.status in {"achieved", "completed"},
                "progress": goal.progress or self._calculate_task_progress(tasks_by_goal.get(goal.goal_id, [])),
                "children": [self._task_to_node(task) for task in tasks_by_goal.get(goal.goal_id, [])],
            }
            for goal in goals
        ]

    def _task_to_node(self, task: AutonomyTask) -> dict:
        return {
            "id": task.task_id,
            "title": task.title,
            "done": task.status == "done",
            "status": task.status,
            "progress": 100 if task.status == "done" else None,
            "summary": task.summary,
            "evidence": task.evidence,
            "next_step": task.next_step,
        }

    @staticmethod
    def _task_id(group_id: str, task_index: int) -> str:
        return f"{group_id}-{task_index:02d}"

    @staticmethod
    def _default_task_status(task_id: str) -> str:
        if task_id in DONE_TASKS:
            return "done"
        if task_id in DOING_TASKS:
            return "doing"
        if task_id in BLOCKED_TASKS:
            return "blocked"
        return "todo"

    @staticmethod
    def _task_summary(group_id: str) -> str:
        return dict((group_id, summary) for group_id, _title, summary in ROADMAP_GROUPS).get(group_id, "")

    @staticmethod
    def _next_step_for_status(status: str) -> str:
        if status == "done":
            return "保持事件驱动更新，继续观察真实运行。"
        if status == "doing":
            return "补齐真实数据接入与 owner 验收反馈。"
        if status == "blocked":
            return "需要服务器运行数据或 owner 规则进一步确认。"
        return "等待后续实现与真实运行验证。"

    @staticmethod
    def _calculate_task_progress(tasks: list[AutonomyTask]) -> int:
        if not tasks:
            return 0
        done = len([task for task in tasks if task.status == "done"])
        return round(done / len(tasks) * 100)

    @staticmethod
    def _first_profile_line(profile_text: str) -> str:
        for line in profile_text.splitlines():
            line = line.strip()
            if line:
                return line
        return "还没有写入档案"

    @staticmethod
    def _extract_profile_section(profile_text: str, section: str) -> list[str]:
        marker = f"【{section}】"
        if marker not in profile_text:
            return []
        text = profile_text.split(marker, 1)[1].split("【", 1)[0]
        return [line.strip(" -:：") for line in text.splitlines() if line.strip(" -:：")]

    @staticmethod
    def _profile_tags(profile_text: str) -> list[str]:
        tags = []
        for marker in ["【核心特质】", "【行为模式】", "【关系定位】", "【茉子认知画像】"]:
            if marker in profile_text:
                tags.append(marker.strip("【】"))
        return tags

    @staticmethod
    def _format_trace(trace: ThoughtTrace) -> str:
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
    def _optional_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M")
