from __future__ import annotations

from collections import Counter
from src.models.schemas import BotProfile, ThoughtTrace
from src.services.memory.mako_context import default_mako_profile


def _default_profile() -> BotProfile:
    return default_mako_profile()



def _format_mako_profile(
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
