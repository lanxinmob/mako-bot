from __future__ import annotations

from src.services.chat.group import (
    GroupConversationService, GroupEvent,
)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_service(**kwargs):
    clock = Clock()
    options = dict(bot_user_id="42", known_bot_ids=("99",),
                   debounce_seconds=0, clock=clock)
    options.update(kwargs)
    return GroupConversationService(**options), clock


def event(message_id="1", user_id="7", text="普通聊天", **kwargs):
    return GroupEvent(group_id="g", message_id=message_id, user_id=user_id,
                      text=text, **kwargs)


def candidate_for(service, incoming=None):
    incoming = incoming or event(text="茉子，帮我分析一下")
    decision = service.select_decision(service.observe(incoming))
    candidate = service.begin_candidate(decision)
    assert candidate is not None
    return candidate
