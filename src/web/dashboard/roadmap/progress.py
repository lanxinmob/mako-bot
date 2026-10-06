from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from src.models.schemas import AutonomyProgressEvent, AutonomyTask
from .catalog import ROADMAP_GROUPS


def _roadmap_groups(tasks: list[dict]) -> list[dict]:
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



def _progress(tasks: list[dict], events: list[AutonomyProgressEvent]) -> dict:
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
        "updated_at": _format_time(events[0].created_at if events else datetime.now()),
        "achieved": achieved,
    }



def _format_recent_progress(events: list[AutonomyProgressEvent]) -> list[dict]:
    return [
        {
            "id": event.event_id,
            "time": _format_time(event.created_at),
            "title": event.summary,
            "source": event.source,
            "event_type": event.event_type or event.event_kind,
            "payload": event.payload,
        }
        for event in events[:30]
    ]



def _calculate_task_progress(tasks: list[AutonomyTask]) -> int:
    if not tasks:
        return 0
    done = len([task for task in tasks if task.status == "done"])
    return round(done / len(tasks) * 100)



def _format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")
