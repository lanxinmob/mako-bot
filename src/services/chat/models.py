"""Generation phase of the chat pipeline.

``ChatEngine`` is transport agnostic: it receives a fully enriched request and
returns a reply plus the history that should be committed after delivery.  The
NoneBot adapter owns sending, so a failed send is never recorded as successful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


from src.services.retrieval.models import SearchOutcome
from src.services.chat.policy import ReplyPlan
from src.services.persistence.history_commit.snapshot import HistorySnapshot


@dataclass(frozen=True)
class ChatRequest:
    session_id: str
    user_id: int
    nickname: str
    user_text: str
    llm_text: str
    history: List[dict]
    message_type: str = "private"
    group_id: Optional[int] = None
    directed: bool = True
    reply_plan: Optional[ReplyPlan] = None
    social_state: str = "normal"
    search_outcome: SearchOutcome = field(default_factory=SearchOutcome)
    history_snapshot: HistorySnapshot | None = None
    plugin_history: List[dict] = field(default_factory=list)


@dataclass(frozen=True)
class ChatReply:
    text: str
    history: List[dict]
    model: str
    factual_consistent: bool = True
    cited: bool = False
    fail_closed: bool = False
    cost_status: str = "unknown"
