"""An optional exported demonstration records actual states, inputs and fake sends."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import PrivateMessageEvent
from src.services.chat.models import ChatRequest
from src.services.chat.messages import MessageBuilder
from src.services.memory.ledger import LedgerService
from src.services.memory.ledger.runtime import for_storage
from src.services.memory.mako_context import MakoRuntimeContext
from test.memory.ledger.test_records import ledger, isolated_redis, source
from test.memory.ledger.test_runtime import adapter


@pytest.mark.asyncio
async def test_export_complete_companion_memory_control_demo(ledger):
    steps = []
    def checkpoint(label, result):
        steps.append(dict(label=label, result=result, control=ledger.repo.state(101),
                          records=[m.model_dump(mode='json') for m in ledger.list(101)],
                          mirrors=[json.loads(v) for v in ledger.repo.notes(101).values()]))
    first = await ledger.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1))
    original = first['memory_id']
    checkpoint('保存并解释真实来源', {'explanation': ledger.explain(101, original)})
    other = await ledger.mutate(101, 'auto', None, '我喜欢红茶', source(2))
    ledger.storage.set_profile(101, '合成人物', '过期画像乌龙茶')
    changed = await ledger.mutate(101, 'correct', original, '现在不喜欢乌龙茶了', source(3))
    checkpoint('偏好变化，原ID已替换', changed)
    builder = MessageBuilder(ledger.storage, lambda _: ['过期向量乌龙茶'], MakoRuntimeContext(ledger.storage))
    def model_input():
        return builder.build(ChatRequest('private_101', 101, '合成人物', '今天你好', '今天你好',
                             [{'role': 'user', 'content': '过期历史乌龙茶'}]))
    corrected_input = model_input()
    assert all(marker not in str(corrected_input) for marker in ('过期画像', '过期向量', '过期历史'))
    assert '不喜欢：乌龙茶' in str(corrected_input)
    queued_view = for_storage(ledger.storage, [101])
    result = await ledger.mutate(101, 'forget', original, '', source(4))
    checkpoint('遗忘整条替换链及镜像', result)
    await ledger.mutate(101, 'forget', other['memory_id'], '', source(5))
    restarted = LedgerService(ledger.storage)
    replay = await restarted.mutate(101, 'auto', None, '我喜欢乌龙茶', source(1))
    blocked = await restarted.mutate(101, 'auto', None, '我喜欢乌龙茶', source(6))
    checkpoint('服务重建，旧来源重放与普通重述仍不恢复', dict(replay=replay, ordinary=blocked))
    assert all(m.status == 'forgotten' and not m.content for m in restarted.list(101))
    forgotten_input = model_input()
    assert '乌龙茶' not in str(forgotten_input)
    matcher = SimpleNamespace(send=AsyncMock(return_value={'message_id': 50}))
    sent = await adapter().send_reply(matcher, PrivateMessageEvent.model_construct(user_id=101),
                    SimpleNamespace(self_id='999'), '旧说明乌龙茶', memory_view=queued_view)
    assert sent is False
    matcher.send.assert_not_awaited()
    restored = await restarted.mutate(101, 'relearn', original, '我喜欢乌龙茶', source(7))
    checkpoint('明确重新授权，仅恢复乌龙茶的新ID', restored)
    active = [m for m in ledger.list(101) if m.status == 'active']
    assert len(active) == 1 and active[0].memory_id != original and active[0].content == '喜欢：乌龙茶'
    assert ledger.repo.blocked(101, ledger.topic(next(m for m in ledger.list(101) if m.memory_id == other['memory_id'])))
    output = dict(steps=steps, model_inputs=dict(after_correct=corrected_input, after_forget=forgotten_input,
                                               after_relearn=model_input()),
                  simulated_delivery=dict(old_body_started=matcher.send.await_count, acknowledged=sent),
                  retained_historic_profile=ledger.storage.get_profile(101))
    destination = os.environ.get('MAKO_LEDGER_DEMO_OUT')
    if destination:
        Path(destination).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
