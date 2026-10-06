"""Tool admission rules, with checks kept in their original order."""
from __future__ import annotations

from typing import Callable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.governance.service import GovernanceService
    from src.services.tools.intent import IntentDecision


CONCURRENT_SAFE_TOOLS = {
    "image.describe", "language.detect", "affinity.query", "emoji.analyze",
    "weather.query", "search.web", "search.summarize_url", "map.query",
}


def is_enabled(tool_name: str, enabled_names: set[str], disabled_names: set[str]) -> bool:
    if tool_name in disabled_names:
        return False
    if enabled_names:
        return tool_name in enabled_names
    return True


def dedupe_decisions(decisions: List[IntentDecision]) -> List[IntentDecision]:
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    result: List[IntentDecision] = []
    for decision in decisions:
        key = (decision.name, tuple(sorted((decision.args or {}).items())))
        if key in seen:
            continue
        seen.add(key)
        result.append(decision)
    return result


def tool_requirements_ok(
    decision: IntentDecision,
    image_urls: List[str],
    audio_urls: List[str],
) -> tuple[bool, str]:
    if decision.name in {"image.describe", "image.process"} and not image_urls:
        return False, "requires image input"
    if decision.name == "language.stt" and not audio_urls:
        return False, "requires audio input"
    if decision.name == "search.summarize_url" and not decision.args.get("url"):
        return False, "requires a valid url"
    return True, ""


def check_admission(
    decision: IntentDecision,
    user_id: int,
    image_urls: List[str],
    audio_urls: List[str],
    *,
    message_type: str,
    group_id: Optional[int],
    is_group_admin: bool,
    governance: GovernanceService,
    is_enabled: Callable[[str], bool],
    requirements_ok: Callable[[IntentDecision, List[str], List[str]], tuple[bool, str]],
) -> tuple[str, float]:
    if not is_enabled(decision.name):
        return f"[{decision.name}] skipped: disabled by config.", 0.0

    access = governance.tool_allowed(
        decision.name,
        user_id=user_id,
        message_type=message_type,
        group_id=group_id,
        is_group_admin=is_group_admin,
    )
    if not access.allowed:
        return f"[{decision.name}] skipped: {access.reason}.", 0.0

    usable, reason = requirements_ok(decision, image_urls, audio_urls)
    if not usable:
        return f"[{decision.name}] skipped: {reason}.", 0.0

    estimated_cost = governance.estimate_tool_cost(decision.name)
    budget = governance.can_consume_cost(user_id, estimated_cost)
    if not budget.allowed:
        return f"[{decision.name}] skipped: {budget.reason}.", 0.0

    return "", estimated_cost
