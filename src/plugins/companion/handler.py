"""Identity comes from OneBot; groups never trigger personal storage access."""
import asyncio
from nonebot.adapters.onebot.v11 import PrivateMessageEvent, Message, MessageSegment

from src.services.delivery.dispatcher import dispatch, acknowledged_result
from src.services.companion.commands import parse
from src.services.companion.projection import reply
from src.services.memory.ledger.source import from_event


async def handle(matcher,event,bot,service,governance,*,enabled=lambda:True):
    if not isinstance(event,PrivateMessageEvent):
        await dispatch('group',event.group_id,lambda: matcher.send(
            Message(MessageSegment.text('请在本人私聊里创建、查看或修改考试计划。'))),category='command')
        await matcher.finish()
        return
    allowed = lambda: enabled() and governance.can_chat(event.user_id).allowed
    if not allowed():
        await matcher.finish()
        return
    view = None
    try:
        if getattr(event,'reply',None) or any(segment.type != 'text' for segment in event.get_message()):
            raise ValueError('请本人直接发送一条纯文本命令，不接受引用或媒体授权。')
        command = parse(event.get_plaintext())
        if command is None:
            raise ValueError('请发送完整考试计划命令。')
        result = await service.execute(event.user_id,command,from_event(event,bot),admit=allowed)
        if result.get('duplicate'):
            return  # The blocking matcher consumes duplicate events silently.
        text,view = await asyncio.to_thread(reply,service,event.user_id,command,result,str(bot.self_id))
    except ValueError as exc:
        text = str(exc)
    except Exception:
        text = '计划操作或状态待确认，请稍后用“我的考试计划”核对；不会猜测成功或自动重发。'
    async def send():
        if not allowed():
            return False
        sender = lambda: matcher.send(Message(MessageSegment.text(text)))
        result = await view.send(sender,admit=allowed) if view else await sender()
        return acknowledged_result(result)
    sent = await dispatch('private',event.user_id,send,category='command',guard=allowed)
    if not sent and view and not view.current():
        await dispatch('private',event.user_id,lambda: matcher.send(
            Message(MessageSegment.text('计划已更新，请重新查看。'))),category='command',
            guard=allowed,notice_key='companion.updated')
    await matcher.finish()
