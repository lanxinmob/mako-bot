from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional
from src.models.schemas import RelationshipMemory
from .memory import _format_relationship_memory


def _format_people(
    profiles: list[dict],
    relationship_memories: list[RelationshipMemory],
) -> list[dict]:
    memories_by_user: dict[int, list[RelationshipMemory]] = defaultdict(list)
    for memory in relationship_memories:
        memories_by_user[memory.user_id].append(memory)

    people = []
    for profile in profiles:
        user_id = _optional_int(profile.get("user_id"))
        memory_items = memories_by_user.get(user_id or -1, [])
        profile_text = str(profile.get("profile_text") or "")
        people.append(
            {
                "id": str(user_id or profile.get("nickname") or len(people)),
                "user_id": user_id,
                "name": profile.get("nickname") or f"用户 {user_id}",
                "nickname": profile.get("nickname") or "",
                "profile_text": profile_text,
                "focus": _first_profile_line(profile_text),
                "preferences": _extract_profile_section(profile_text, "偏好"),
                "tags": _profile_tags(profile_text),
                "relationship_memories": [
                    _format_relationship_memory(memory) for memory in memory_items
                ],
                "memory_count": len(memory_items),
                "last_updated": profile.get("last_updated") or "",
            }
        )
    people.sort(key=lambda item: item.get("last_updated") or "", reverse=True)
    return people



def _first_profile_line(profile_text: str) -> str:
    for line in profile_text.splitlines():
        line = line.strip()
        if line:
            return line
    return "还没有写入档案"



def _extract_profile_section(profile_text: str, section: str) -> list[str]:
    marker = f"【{section}】"
    if marker not in profile_text:
        return []
    text = profile_text.split(marker, 1)[1].split("【", 1)[0]
    return [line.strip(" -:：") for line in text.splitlines() if line.strip(" -:：")]



def _profile_tags(profile_text: str) -> list[str]:
    tags = []
    for marker in ["【核心特质】", "【行为模式】", "【关系定位】", "【茉子认知画像】"]:
        if marker in profile_text:
            tags.append(marker.strip("【】"))
    return tags



def _optional_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
