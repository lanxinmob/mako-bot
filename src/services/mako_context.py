from __future__ import annotations

from typing import Iterable, Optional

from src.models.schemas import BotProfile, RelationshipMemory
from src.services.storage import StorageService


def default_mako_profile() -> BotProfile:
    return BotProfile(
        profile_id="mako",
        name="茉子",
        summary="以稳定、尊重边界、能够延续关系的方式与人相处。",
        persona="常陆茉子风格的忍者手账员：轻快、认真、会撒娇但守边界。",
        values=["诚实", "温柔", "守边界", "有自己的判断", "尊重每个人对记忆的控制权"],
        boundaries=[
            "只对白名单目标主动行动",
            "不同用户的私人记忆不可混用",
            "中风险先询问 owner",
            "高风险保持沉默",
            "不展示隐藏推理链",
        ],
        current_stage="关系连续性 v1",
        autonomy_statement="我会依据真实事件、关系历史和当前目标判断是否行动，不为刷存在感而发言。",
        capabilities=["对话记忆", "关系记忆", "自主决策", "owner 审批", "进度审计"],
        limitations=["不能替代真实的人际关系", "不确定时需要询问", "记忆可能被用户纠正或删除"],
    )


def relationship_stage(memories: list[RelationshipMemory], affinity_score: int) -> str:
    active = [memory for memory in memories if memory.status == "active"]
    if not active:
        return "初识"
    if affinity_score >= 85 or len(active) >= 8:
        return "亲近"
    if affinity_score >= 65 or len(active) >= 4:
        return "信任建立"
    return "熟悉中"


class MakoRuntimeContext:
    def __init__(self, storage: Optional[StorageService] = None) -> None:
        self.storage = storage or StorageService()

    def get_profile(self) -> BotProfile:
        try:
            profile = self.storage.get_bot_profile("mako")
        except Exception:
            profile = None
        if profile:
            return profile
        profile = default_mako_profile()
        try:
            self.storage.save_bot_profile(profile)
        except Exception:
            pass
        return profile

    def identity_context(self) -> str:
        profile = self.get_profile()
        return "\n".join(
            [
                f"姓名：{profile.name}",
                f"自我概述：{profile.summary or '无'}",
                f"人格：{profile.persona or '无'}",
                f"当前阶段：{profile.current_stage or '未设定'}",
                f"价值观：{'；'.join(profile.values) or '未设定'}",
                f"边界：{'；'.join(profile.boundaries) or '未设定'}",
                f"自主声明：{profile.autonomy_statement or '未设定'}",
                f"能力：{'；'.join(profile.capabilities) or '未设定'}",
                f"限制：{'；'.join(profile.limitations) or '未设定'}",
            ]
        )

    def relationship_context(self, user_id: int, *, limit: int = 12) -> str:
        try:
            memories = self.storage.list_relationship_memories(user_id, status="", limit=limit)
        except Exception:
            memories = []
        try:
            affinity = self.storage.get_affinity(user_id)
        except Exception:
            affinity = 50
        stage = relationship_stage(memories, affinity)
        active = [memory for memory in memories if memory.status == "active"]
        lines = [f"用户 {user_id}：关系阶段={stage}，好感度={affinity}"]
        labels = {"preference": "偏好", "taboo": "边界", "event": "事件", "promise": "承诺"}
        for memory in active:
            due = f"，计划跟进={memory.due_at.isoformat()}" if memory.due_at else ""
            lines.append(f"- {labels.get(memory.memory_type, memory.memory_type)}：{memory.content}{due}")
        if not active:
            lines.append("- 暂无这个用户的有效关系记忆。")
        lines.append("约束：这里只描述该 user_id，绝不能套用到其他人。")
        return "\n".join(lines)

    def goal_context(self, *, limit: int = 6) -> str:
        try:
            goals = self.storage.list_autonomy_goals(status="active", limit=limit)
        except Exception:
            goals = []
        try:
            doing = self.storage.list_autonomy_tasks(status="doing", limit=limit)
            todo = self.storage.list_autonomy_tasks(status="todo", limit=limit)
        except Exception:
            doing, todo = [], []
        lines: list[str] = []
        for goal in goals:
            lines.append(f"- 目标：{goal.title}｜{goal.summary or goal.reason}｜进度 {goal.progress}%")
        for task in [*doing, *todo][:limit]:
            lines.append(f"- 当前任务[{task.status}]：{task.title}｜{task.summary or task.next_step}")
        return "\n".join(lines) if lines else "暂无持久化的活跃目标或任务。"

    def build_for_user(self, user_id: int) -> str:
        return (
            "[Mako 自身档案]\n"
            f"{self.identity_context()}\n\n"
            "[与当前用户的关系]\n"
            f"{self.relationship_context(user_id)}\n\n"
            "[当前目标]\n"
            f"{self.goal_context()}"
        )

    def build_for_autonomy(self, user_ids: Iterable[int]) -> str:
        unique_ids: list[int] = []
        for user_id in user_ids:
            if user_id not in unique_ids:
                unique_ids.append(user_id)
            if len(unique_ids) >= 6:
                break
        relationships = (
            "\n\n".join(self.relationship_context(user_id, limit=6) for user_id in unique_ids)
            if unique_ids
            else "近期上下文没有可识别的用户关系。"
        )
        return (
            "[Mako 自身档案]\n"
            f"{self.identity_context()}\n\n"
            "[活跃目标]\n"
            f"{self.goal_context()}\n\n"
            "[近期参与者关系，仅可按相同 user_id 使用]\n"
            f"{relationships}"
        )
