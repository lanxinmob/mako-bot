"""QQ boundary: self-only access, plain text and version-checked scheduling."""
import time
from collections import OrderedDict
from nonebot.adapters.onebot.v11 import PrivateMessageEvent, Message, MessageSegment
from src.services.delivery.dispatcher import dispatch, acknowledged_result
from src.services.memory.ledger import LedgerService
from src.services.memory.ledger.commands import Command, execute, parse
from src.services.memory.ledger.source import from_event
from .runtime import storage, governance

_explanations = OrderedDict()


async def handle(matcher, event, bot, command):
    if not isinstance(event, PrivateMessageEvent):
        await dispatch('group', event.group_id,
                       lambda: matcher.send(Message(MessageSegment.text('请在本人私聊里查看或修改记忆。'))), category='command')
        await matcher.finish()
        return
    def allowed():
        return governance.can_chat(event.user_id).allowed
    if not allowed():
        await matcher.finish()
        return
    if command and command.operation == 'quoted_forget':
        reply = getattr(event, 'reply', None)
        key = (str(bot.self_id), event.user_id, str(reply.message_id)) if reply else None
        item = _explanations.get(key)
        command = Command('forget', item[0]) if item and time.monotonic() - item[1] <= 300 else None
    try:
        if command is None:
            text, view, explanation = '请提供记忆 ID；说明引用须来自本人、当前机器人且在五分钟内。', None, None
        else:
            text, view, explanation = await execute(LedgerService(storage), event.user_id, command, from_event(event, bot), admit=allowed)
    except ValueError:
        text, view, explanation = '缺少可信来源或命令格式不完整，请重新发送。', None, None
    except Exception:
        text, view, explanation = '记忆控制暂时不可用，修改结果待确认；请稍后查询，不会猜测为成功。', None, None
    async def send():
        if not allowed():
            return False
        sender = lambda: matcher.send(Message(MessageSegment.text(text)))
        result = await view.send(sender) if view else await sender()
        if acknowledged_result(result) and explanation and isinstance(result, dict):
            key = (str(bot.self_id), event.user_id, str(result['message_id']))
            _explanations[key] = (explanation, time.monotonic())
            while len(_explanations) > 1024:
                _explanations.popitem(last=False)
        return acknowledged_result(result)
    sent = await dispatch('private', event.user_id, send, category='command', guard=allowed)
    if not sent and view is not None and not view.current():
        await dispatch('private', event.user_id,
                       lambda: matcher.send(Message(MessageSegment.text('记忆已更新，请重新查看。'))),
                       category='command', guard=allowed, notice_key='memory.updated')
    await matcher.finish()


async def natural_invoked(event):
    text = event.get_message().extract_plain_text().strip()
    return not text.startswith(('/', '.')) and parse(text) is not None
