from __future__ import annotations

from collections import defaultdict
from src.models.schemas import AutonomyGoal, AutonomyTask, AutonomyProgressEvent
from .catalog import ROADMAP_GROUPS, ROADMAP_TASK_TITLES
from .defaults import BLOCKED_TASKS, DOING_TASKS, DONE_TASKS, STATUS_LABELS
from .evidence import (BLOCKED_REASON_OVERRIDES, GROUP_CRITERIA_TEMPLATES,
                       GROUP_IMPLEMENTATION_BASIS, TASK_EVIDENCE_OVERRIDES)
from .progress import _calculate_task_progress


def _default_goals() -> list[AutonomyGoal]:
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
            task_id = _task_id(group_id, task_index)
            persisted = persisted_by_title.get(title)
            status = persisted.status if persisted else _default_task_status(task_id)
            evidence = persisted.evidence if persisted else ""
            if not evidence:
                evidence = _task_evidence(task_id, group_id, status)
            if evidence_by_task.get(task_id):
                evidence = evidence_by_task[task_id].summary
            summary = persisted.summary if persisted else _task_detail_summary(group_id, title, status)
            next_step = persisted.next_step if persisted else _next_step_for_task(task_id, group_id, title, status)
            criteria = _completion_criteria(group_id, title)
            why_status = _why_status(task_id, group_id, status, evidence)
            tasks.append(
                {
                    "id": task_id,
                    "number": number,
                    "group_id": group_id,
                    "group_title": group_title,
                    "title": persisted.title if persisted else title,
                    "summary": summary,
                    "status": status,
                    "status_label": STATUS_LABELS.get(status, status),
                    "done": status == "done",
                    "evidence": evidence,
                    "completion_criteria": criteria,
                    "completion_basis": _completion_basis(task_id, group_id, status, evidence),
                    "verification": _verification_for_task(task_id, group_id, status),
                    "why_status": why_status,
                    "next_step": next_step,
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
        criteria = _completion_criteria(task.goal_id or "custom", task.title)
        evidence = task.evidence or _task_evidence(task.task_id, task.goal_id or "custom", status)
        tasks.append(
            {
                "id": task.task_id,
                "number": len(tasks) + 1,
                "group_id": task.goal_id or "custom",
                "group_title": "额外任务",
                "title": task.title,
                "summary": task.summary,
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "done": status == "done",
                "evidence": evidence,
                "completion_criteria": criteria,
                "completion_basis": _completion_basis(task.task_id, task.goal_id or "custom", status, evidence),
                "verification": _verification_for_task(task.task_id, task.goal_id or "custom", status),
                "why_status": _why_status(task.task_id, task.goal_id or "custom", status, evidence),
                "next_step": task.next_step,
                "priority": task.priority,
                "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            }
        )
    return tasks



def _build_goal_tree(goals: list[AutonomyGoal], tasks: list[AutonomyTask]) -> list[dict]:
    tasks_by_goal: dict[str, list[AutonomyTask]] = defaultdict(list)
    for task in tasks:
        if task.goal_id:
            tasks_by_goal[task.goal_id].append(task)
    return [
        {
            "id": goal.goal_id,
            "title": goal.title,
            "done": goal.status in {"achieved", "completed"},
            "progress": goal.progress or _calculate_task_progress(tasks_by_goal.get(goal.goal_id, [])),
            "children": [_task_to_node(task) for task in tasks_by_goal.get(goal.goal_id, [])],
        }
        for goal in goals
    ]



def _task_to_node(task: AutonomyTask) -> dict:
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



def _task_id(group_id: str, task_index: int) -> str:
    return f"{group_id}-{task_index:02d}"



def _default_task_status(task_id: str) -> str:
    if task_id in DONE_TASKS:
        return "done"
    if task_id in DOING_TASKS:
        return "doing"
    if task_id in BLOCKED_TASKS:
        return "blocked"
    return "todo"



def _task_summary(group_id: str) -> str:
    return dict((group_id, summary) for group_id, _title, summary in ROADMAP_GROUPS).get(group_id, "")



def _task_detail_summary(group_id: str, title: str, status: str) -> str:
    group_summary = _task_summary(group_id)
    status_label = STATUS_LABELS.get(status, status)
    return f"{group_summary} 当前任务是“{title}”，状态为{status_label}；展开可查看完成判定、依据、验证方式和下一步。"



def _next_step_for_status(status: str) -> str:
    if status == "done":
        return "保持事件驱动更新，继续观察真实运行。"
    if status == "doing":
        return "补齐真实数据接入与 owner 验收反馈。"
    if status == "blocked":
        return "需要服务器运行数据或 owner 规则进一步确认。"
    return "等待后续实现与真实运行验证。"



def _next_step_for_task(task_id: str, group_id: str, title: str, status: str) -> str:
    if status == "done":
        return "保持当前实现，并继续让真实聊天、审批和发送事件覆盖默认完成依据。"
    if status == "doing":
        return f"补齐“{title}”的真实运行样例、owner 验收反馈和自动进度事件。"
    if status == "blocked":
        return BLOCKED_REASON_OVERRIDES.get(
            task_id,
            f"先收集服务器真实数据或 owner 规则，明确“{title}”的验收口径后再推进。",
        )
    return f"实现“{title}”对应的数据写入、读取、展示和至少一次可复核验证。"



def _completion_criteria(group_id: str, title: str) -> list[str]:
    templates = GROUP_CRITERIA_TEMPLATES.get(
        group_id,
        [
            "存在对应的数据结构、实现路径或配置项。",
            "能在仪表盘或事件流水中看到该任务的状态和依据。",
            "缺少真实验证时不能判定为完成。",
        ],
    )
    return [template.format(title=title) for template in templates]



def _completion_basis(task_id: str, group_id: str, status: str, evidence: str) -> list[str]:
    basis = []
    if evidence:
        basis.append(evidence)
    group_basis = GROUP_IMPLEMENTATION_BASIS.get(group_id)
    if group_basis:
        basis.append(group_basis)
    if status == "done":
        basis.append("该任务在当前 100 项路线图基线中被标记为 done，并有代码路径或配置作为支撑。")
    elif status == "doing":
        basis.append("已有部分实现或数据入口，但还缺真实运行样例、统计闭环或 owner 验收。")
    elif status == "blocked":
        basis.append("当前缺少足够规则、样本或自动化闭环，不能只靠设想判定完成。")
    else:
        basis.append("尚未看到对应实现或真实事件，保持待办。")
    return list(dict.fromkeys(item for item in basis if item))



def _task_evidence(task_id: str, group_id: str, status: str) -> str:
    if task_id in TASK_EVIDENCE_OVERRIDES:
        return TASK_EVIDENCE_OVERRIDES[task_id]
    if status == "done":
        return GROUP_IMPLEMENTATION_BASIS.get(group_id, "已有当前代码或配置提供基础能力。")
    if status == "doing":
        return f"{GROUP_IMPLEMENTATION_BASIS.get(group_id, '已有部分入口。')} 仍需要更多真实事件或策略回写来完成验收。"
    if status == "blocked":
        return BLOCKED_REASON_OVERRIDES.get(task_id, "缺少真实运行样例、owner 规则或自动化闭环，暂不能验收。")
    return "尚未发现可证明完成的代码路径或事件记录。"



def _why_status(task_id: str, group_id: str, status: str, evidence: str) -> str:
    status_label = STATUS_LABELS.get(status, status)
    if status == "done":
        return f"判定为{status_label}，因为当前实现已经覆盖主要入口，并能通过仪表盘或事件流水被 owner 查看。"
    if status == "doing":
        return f"判定为{status_label}，因为已有基础入口，但还需要真实运行数据、owner 反馈或自动回写来完成闭环。"
    if status == "blocked":
        return f"判定为{status_label}，因为{BLOCKED_REASON_OVERRIDES.get(task_id, evidence or '缺少关键验收条件')}。"
    return f"判定为{status_label}，因为目前还没有足够实现证据；需要先完成对应代码、数据和验证。"



def _verification_for_task(task_id: str, group_id: str, status: str) -> str:
    if group_id == "dashboard":
        return "打开 /mako/dashboard?token=...，确认该模块有内容、可搜索/筛选，移动端不重叠；API 不能泄露密钥或隐藏推理链。"
    if group_id == "memory":
        return "在 Redis 有数据和 Redis 不可用两种场景下调用 dashboard summary，确认旧 key 与新模型记录都能展示。"
    if group_id == "decision":
        return "构造 owner 建议和近期上下文，确认决策 JSON 字段完整，非法/歧义输出被本地规则降级或转问 owner。"
    if group_id == "safety":
        return "用未白名单、冷却中、中风险、高风险和预算不足样例验证不会直接发送，并写入拒绝/静默事件。"
    if group_id == "action":
        return "用批准、取消、改写和发送失败四类 pending 流程验证消息发送、冷却、日志和全局记录。"
    if group_id == "perception":
        return "喂入群聊/私聊/多个 QQ/未指明目标样例，检查目标类型和 ask_owner 分支是否正确。"
    if group_id == "learning":
        return "积累 owner 批准、取消、改写样例后，检查统计、归因和下一次决策提示是否可见。"
    if group_id == "reflection":
        return "触发定期或手动复盘，确认生成 ThoughtTrace、更新目标/任务状态，并明确不保存隐藏推理链。"
    if group_id == "milestone":
        return "所有能力组达到完成判定后，检查总进度为 100%，并写入“自主意志 v1 达成”进度事件。"
    return "运行 py_compile/API smoke test，并用至少一条真实事件验证该任务能被仪表盘展示。"
