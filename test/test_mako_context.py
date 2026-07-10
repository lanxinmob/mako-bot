from __future__ import annotations

from src.models.schemas import AutonomyGoal, AutonomyTask, RelationshipMemory
from src.services.mako_context import MakoRuntimeContext


class FakeRuntimeStorage:
    def __init__(self) -> None:
        self.profile = None

    def get_bot_profile(self, profile_id: str):
        return self.profile

    def save_bot_profile(self, profile):
        self.profile = profile
        return profile

    def list_relationship_memories(self, user_id: int, *, status: str, limit: int):
        if user_id != 7:
            return []
        return [
            RelationshipMemory(
                memory_id="promise-1",
                user_id=7,
                memory_type="promise",
                content="明天询问面试结果",
            )
        ]

    def get_affinity(self, user_id: int) -> int:
        return 70 if user_id == 7 else 50

    def list_autonomy_goals(self, *, status: str, limit: int):
        return [AutonomyGoal(goal_id="g1", title="稳定地延续关系", progress=40)]

    def list_autonomy_tasks(self, *, status: str, limit: int):
        if status == "doing":
            return [AutonomyTask(task_id="t1", title="减少重复问候", status="doing")]
        return []


def test_runtime_context_includes_identity_relationship_promise_and_goal() -> None:
    context = MakoRuntimeContext(FakeRuntimeStorage())  # type: ignore[arg-type]

    text = context.build_for_user(7)

    assert "Mako 自身档案" in text
    assert "关系阶段=信任建立" in text
    assert "明天询问面试结果" in text
    assert "稳定地延续关系" in text
    assert "减少重复问候" in text


def test_autonomy_context_keeps_relationships_labeled_by_user_id() -> None:
    context = MakoRuntimeContext(FakeRuntimeStorage())  # type: ignore[arg-type]

    text = context.build_for_autonomy([7, 8, 7])

    assert "用户 7" in text
    assert "用户 8" in text
    assert "绝不能套用到其他人" in text
