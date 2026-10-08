"""Transport-free inputs and explicit chat service dependencies."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol, Callable
from src.services.chat.policy import ChatAddress
from src.utils.message import NormalizedMessage


@dataclass(frozen=True)
class ChatInput:
    address: ChatAddress
    nickname: str
    text: str
    normalized: NormalizedMessage
    directed: bool
    is_group_admin: bool
    started_at: float
    bot_id: str = ""
    message_id: str = ""
    group_context: str = ""
    is_current: Callable[[], bool] | None = None
    read_group_context: Callable[[], str] | None = None
    refresh_before_generation: Callable[[], bool] | None = None
    work_kind: str = "chat"
    group_memory_observed: bool = False


class ChatTransport(Protocol):
    async def reply(self, text: str) -> bool: ...
    async def reply_recorded(self, text: str, *, before_send, on_ack) -> bool: ...
    async def notice(self, text: str) -> bool: ...
    async def extra(self, payload: Any) -> bool: ...
    async def reminder(self, address: ChatAddress, text: str) -> bool: ...


@dataclass
class ChatServices:
    settings: Any
    storage: Any
    audit: Any
    context_builder: Any
    relationship: Any
    governance: Any
    chat_rhythm: Any
    chat_engine: Any
    make_tools: Callable[[], Any]
    history_delivery: Any = None

    def __post_init__(self):
        if self.history_delivery is None:
            from src.services.chat.history_delivery.runtime import ChatHistoryRuntime
            self.history_delivery = ChatHistoryRuntime(self.storage, self.settings)


@dataclass(frozen=True)
class Admission:
    will_reply: bool
    rhythm: Any
