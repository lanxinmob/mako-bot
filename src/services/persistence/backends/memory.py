from __future__ import annotations

from dataclasses import dataclass, field
from collections import OrderedDict
from typing import Dict, List


@dataclass
class MemoryStorage:
    histories: Dict[str, List[dict]] = field(default_factory=dict)
    plugin_histories: OrderedDict[str, List[dict]] = field(default_factory=OrderedDict)
    all_memory: List[str] = field(default_factory=list)
    outbound_messages: Dict[str, List[dict]] = field(default_factory=dict)
    sent_news: Dict[str, float] = field(default_factory=dict)
    profiles: Dict[str, str] = field(default_factory=dict)
    notes: Dict[int, Dict[str, dict]] = field(default_factory=dict)
    bot_profiles: Dict[str, dict] = field(default_factory=dict)
    thought_traces: Dict[str, dict] = field(default_factory=dict)
    autonomy_goals: Dict[str, dict] = field(default_factory=dict)
    autonomy_tasks: Dict[str, dict] = field(default_factory=dict)
    autonomy_progress_events: Dict[str, dict] = field(default_factory=dict)
    affinity: Dict[int, int] = field(default_factory=dict)
    affinity_daily: Dict[str, int] = field(default_factory=dict)
    relationship_memories: Dict[int, Dict[str, dict]] = field(default_factory=dict)
    relationship_followups: Dict[str, tuple[int, float]] = field(default_factory=dict)
    blacklisted_users: Dict[int, str] = field(default_factory=dict)
    blacklisted_groups: Dict[int, str] = field(default_factory=dict)
    daily_costs: Dict[str, float] = field(default_factory=dict)
    reminders: Dict[str, dict] = field(default_factory=dict)


memory_store = MemoryStorage()
