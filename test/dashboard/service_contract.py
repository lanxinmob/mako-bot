"""Dashboard summary contracts with synthetic storage and no application startup."""

import json
from pathlib import Path
import sys
import types
from unittest.mock import Mock


root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))


def deny_external(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = Path(str(args[0])).name
        assert name != ".env" and not name.startswith(".env."), "env read denied"
    assert event not in {"socket.connect", "socket.getaddrinfo"}, "network denied"


sys.addaudithook(deny_external)
storage_stub = types.ModuleType("src.services.persistence")
storage_stub.StorageService = Mock(side_effect=AssertionError("real storage forbidden"))
sys.modules[storage_stub.__name__] = storage_stub

from src.models import schemas as models
from src.web.dashboard.service import DashboardService, ROADMAP_TASK_TITLES


storage_methods = (
    "list_bot_profiles", "list_profiles", "list_autonomy_goals", "list_autonomy_tasks",
    "list_autonomy_progress_events", "list_all_notes", "list_all_relationship_memories",
    "list_thought_traces", "list_global_records", "list_long_term_memory_points",
)


def summary(rows, limit):
    storage = Mock(spec=storage_methods)
    for name in storage_methods:
        getattr(storage, name).side_effect = (
            lambda items=rows.get(name, []), **kwargs: items[:kwargs.get("limit", len(items))]
        )
    result = DashboardService(storage).get_frontend_summary(limit=limit)
    for name in ("list_all_notes", "list_all_relationship_memories", "list_thought_traces",
                 "list_global_records", "list_long_term_memory_points"):
        getattr(storage, name).assert_called_once_with(limit=limit)
    for name in ("list_autonomy_goals", "list_autonomy_tasks", "list_autonomy_progress_events"):
        getattr(storage, name).assert_called_once_with(limit=max(limit, 100))
    assert result["ok"] is True
    json.dumps(result)
    data = result["data"]
    assert data["overview"]["progress_percent"] == data["progress"]["percent"]
    assert data["mako_profile"] == data["mako_psych_profile"]
    assert data["overview"]["counts"]["roadmap_tasks"] == len(data["roadmap_tasks"])
    assert data["overview"]["counts"]["notes"] == len(data["memory_notes"])
    return data


titles = ROADMAP_TASK_TITLES["foundation"]
tasks = [models.AutonomyTask(
    task_id=f"stored-{index}", goal_id="foundation", title=titles[index],
    status=status, summary="Fixture summary", evidence="Stored evidence",
) for index, status in enumerate(("todo", "doing", "blocked", "done", "skipped", "cancelled"))]
tasks.append(models.AutonomyTask(task_id="custom-1", title="Custom task", status="done"))
events = [models.AutonomyProgressEvent(
    event_id=f"event-{index}", task_id="foundation-01", summary=text,
) for index, text in enumerate(("First event", "Latest event"))]
populated = {
    "list_bot_profiles": [models.BotProfile(profile_id="fixture", name="Fixture")],
    "list_autonomy_goals": [models.AutonomyGoal(goal_id="foundation", title="Goal")],
    "list_autonomy_tasks": tasks,
    "list_autonomy_progress_events": events,
    "list_all_notes": [models.NoteRecord(note_id="n1", user_id=1, title="Note", content="Fixture")],
    "list_profiles": [{"user_id": "1", "profile_text": "Fixture profile"}],
    "list_all_relationship_memories": [models.RelationshipMemory(
        memory_id="r1", user_id=1, memory_type="preference", content="Fixture preference")],
    "list_global_records": [models.ChatRecord(role="user", content="Fixture")],
    "list_long_term_memory_points": [{"id": "l1", "content": "Fixture memory"}],
}
complete = {"list_autonomy_tasks": [models.AutonomyTask(
    task_id=f"{group}-{index:02d}", goal_id=group, title=title, status="done",
) for group, names in ROADMAP_TASK_TITLES.items() for index, title in enumerate(names, 1)]}
legacy = {"list_thought_traces": [models.ThoughtTrace(
    trace_id="legacy-" + source, source=source, summary="Legacy fixture",
    payload={"action": "silent", "target_type": "group", "target_id": 7,
             "token": "synthetic-token", "messages": ["Synthetic message"],
             "memories": [{"content_preview": "Fixture"}, "Old item"]},
) for source in ("autonomy", "chat", "notes", "relationship", "unknown")]}

for limit in (1, 200):
    empty = summary({}, limit)
    assert empty["roadmap_tasks"] and empty["roadmap_groups"]
    assert empty["notes"] == empty["people"] == empty["thought_traces"] == []
    assert {key: empty["progress"][key] for key in ("done", "doing", "blocked", "todo")} == {
        "done": 53, "doing": 27, "blocked": 19, "todo": 1,
    }
    data = summary(populated, limit)
    assert data["roadmap_tasks"][0]["evidence"] == "Latest event"
    assert data["roadmap_tasks"][-1]["id"] == "custom-1"
    assert len(data["notes"]) == len(data["people"]) == 1
    assert [(item["id"], item["content"]) for item in data["long_term_memory"]] == [
        ("l1", "Fixture memory"),
    ]
    assert [item["id"] for item in data["memory_notes"]] == ["n1", "l1"]
    assert data["overview"]["counts"]["notes"] == 2
    statuses = {item["title"]: item["status"] for item in data["roadmap_tasks"]}
    for task in tasks:
        assert statuses[task.title] == task.status
    data = summary(complete, limit)
    assert data["progress"]["percent"] == 100 and data["progress"]["achieved"] is True
    data = summary(legacy, limit)
    assert len(data["thought_traces"]) == min(limit, len(legacy["list_thought_traces"]))
    for trace in data["thought_traces"]:
        assert trace["payload"]["token"] == "[redacted]"
        assert trace["payload"]["messages"] == "[redacted]"

assert "src.core.config" not in sys.modules
assert "nonebot" not in sys.modules
print("PASS summary: empty/populated/complete/legacy, limits, serialization, safe trace view")
