from __future__ import annotations
import time
from datetime import datetime
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, PrivateMessageEvent
from nonebot.matcher import Matcher
from src.services.chat.policy import ChatAddress
from src.services.chat.pipeline.models import ChatInput
from src.services.chat.pipeline.group_memory import group_memory_text
from src.utils.message import normalize_message
from .delivery import message_text, send_reply
from .reminders import handle_reminder
from src.services.chat.group.models import GroupEvent
from src.services.delivery.dispatcher import send_notice, send_to_event


async def observe(event: MessageEvent, bot: Bot, workflow):
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return
    raw = event.get_message()
    received_at = datetime.now()
    normalized = normalize_message(raw)
    quoted = getattr(event, "reply", None)
    sender = getattr(quoted, "sender", None)
    workflow.participation.observe(str(bot.self_id), GroupEvent(
        str(group_id), str(event.message_id), str(event.user_id),
        text=normalized.plain_text,
        nickname=event.sender.card or event.sender.nickname or str(event.user_id),
        reply_to_message_id=str(quoted.message_id) if quoted is not None else None,
        reply_to_user_id=str(sender.user_id) if sender is not None else None,
        mentions=tuple(str(segment.data.get("qq")) for segment in raw if segment.type == "at"),
        is_bot=str(event.user_id) == str(bot.self_id),
        direct_call=event.is_tome(),
    ), normalized)
    await workflow.group_memory.record(
        bot_id=str(bot.self_id), message_id=str(event.message_id),
        user_id=event.user_id, group_id=group_id,
        nickname=event.sender.card or event.sender.nickname or str(event.user_id),
        content=group_memory_text(normalized), received_at=received_at,
        image_urls=normalized.image_urls,
    )

def _address(event: MessageEvent) -> ChatAddress:
    return ChatAddress(
        message_type=event.message_type,
        user_id=event.user_id,
        group_id=getattr(event, "group_id", None),
    )


class QQChatTransport:
    def __init__(self, matcher: Matcher, event: MessageEvent, bot: Bot):
        self.matcher, self.event, self.bot = matcher, event, bot
        self.guard = None
        self.category = "chat"
        self.on_sent = None
        self.cancel_candidate = lambda: None

    async def reply(self, text: str):
        return await send_reply(self.matcher, self.event, self.bot, text,
                                guard=self.guard, on_sent=self.on_sent, category=self.category)

    async def reply_recorded(self, text: str, *, before_send, on_ack):
        return await send_reply(self.matcher, self.event, self.bot, text,
                                guard=self.guard, on_sent=self.on_sent, category=self.category,
                                before_send=before_send, on_ack=on_ack)

    async def notice(self, text: str):
        return await send_notice(self.matcher, self.event, Message(text),
                                 notice_key="chat.notice", guard=self.guard)

    async def extra(self, payload):
        return await send_to_event(self.matcher, self.event, payload, category="command")

    async def reminder(self, address, text):
        return await handle_reminder(self.matcher, self.event, address, text)


async def receive(matcher: Matcher, event: MessageEvent, bot: Bot, workflow):
    started_at = time.perf_counter()
    normalized = normalize_message(event.get_message())
    text = await message_text(event, bot)
    incoming = ChatInput(
        address=_address(event),
        nickname=event.sender.card or event.sender.nickname or str(event.user_id),
        text=text, normalized=normalized,
        directed=event.is_tome() or isinstance(event, PrivateMessageEvent),
        is_group_admin=getattr(event.sender, "role", "member") in {"admin", "owner"},
        started_at=started_at,
        bot_id=str(bot.self_id), message_id=str(event.message_id),
        group_memory_observed=(getattr(event, "group_id", None) is not None
                               and workflow.services.settings.record_undirected_group_messages),
    )
    await workflow.handle(incoming, QQChatTransport(matcher, event, bot))
