import importlib
from types import SimpleNamespace

import nonebot
import pytest
from nonebot import on_message
from nonebot.adapters.onebot.v11 import Adapter,Bot,MessageEvent,Message,MessageSegment
from src.services.delivery.dispatcher import OutboundDispatcher
from src.core.config import Settings
from test.features.discoveries.test_plugin import plugin
from test.features.discoveries.test_access import event


@pytest.fixture
def runtime(plugin,context,monkeypatch):
    loaded=nonebot.get_plugin('companion') or nonebot.load_plugin('src.plugins.companion')
    assert loaded
    module=loaded.module
    state=SimpleNamespace(sends=[],fallback=[],observed=[],allowed=True,context=context,module=module)
    state.settings=Settings(_env_file=None,PLUGIN_ENABLE_LIST='chat,companion')
    monkeypatch.setattr(module,'get_settings',lambda:state.settings)
    monkeypatch.setattr(module,'service',context.service)
    monkeypatch.setattr(module,'governance',SimpleNamespace(can_chat=lambda *_:SimpleNamespace(allowed=state.allowed)))
    handler=importlib.import_module('src.plugins.companion.handler')
    monkeypatch.setattr(handler,'dispatch',OutboundDispatcher(spacing=0).dispatch)
    async def api(bot,name,**kwargs):
        assert name in {'send_msg','send_private_msg','send_group_msg'}
        state.sends.append(kwargs)
        return {'message_id':len(state.sends)+1000}
    monkeypatch.setattr(Bot,'call_api',api)
    fallback=on_message(priority=40,block=False)
    observer=on_message(priority=1,block=False)
    @observer.handle()
    async def personal_record(event:MessageEvent):
        state.observed.append(event.message_id)
    @fallback.handle()
    async def record(event:MessageEvent):
        state.fallback.append(event.message_id)
    monkeypatch.setattr(importlib.import_module('nonebot.message'),'matchers',
                        {0:[module.commands],1:[observer],40:[fallback]})
    state.bot=Bot(Adapter(nonebot.get_driver()),'42')
    yield state
    fallback.destroy()
    observer.destroy()


def personal(text,message=1,user=101):
    return event(text,private=True).model_copy(update={'user_id':user,'message_id':message})


@pytest.mark.asyncio
async def test_actual_nonebot_create_query_consent_and_duplicate_without_models(runtime):
    text='创建考试计划 合成数学 | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=复习章节；练习真题'
    await runtime.bot.handle_event(personal(text))
    plan=runtime.context.service.repo.list(101)[0]
    assert plan['bot_id']=='42' and '未授权' in str(runtime.sends[0]['message'])
    await runtime.bot.handle_event(personal(text))
    assert len(runtime.sends)==1
    await runtime.bot.handle_event(personal('/我的考试计划',2))
    assert plan['plan_id'] in str(runtime.sends[-1]['message'])
    await runtime.bot.handle_event(personal(f"同意回顾 {plan['plan_id']} 2026-10-09 16:00",3))
    assert runtime.context.service.repo.get(101,plan['plan_id'])['consent']=='granted'
    assert not runtime.fallback
    assert not runtime.observed  # Consumption precedes passive record/permission reads.
    assert all(segment.type=='text' for send in runtime.sends for segment in send['message'])


@pytest.mark.asyncio
async def test_disabled_plugin_blocks_live_commands_and_scanner_qualification(runtime):
    runtime.settings.plugin_enable_list='chat'
    assert not runtime.module.scanner.allowed(101)
    await runtime.bot.handle_event(personal('创建考试计划 A | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=a'))
    assert runtime.context.service.repo.list(101)==[] and runtime.sends==[] and runtime.fallback==[]


@pytest.mark.asyncio
async def test_group_unknown_id_invalid_and_media_never_reach_personal_reads(runtime,monkeypatch):
    def forbidden(*args):
        raise AssertionError('personal storage accessed from group')
    monkeypatch.setattr(runtime.context.service.repo,'list',forbidden)
    monkeypatch.setattr(runtime.context.service.repo,'get',forbidden)
    await runtime.bot.handle_event(event('查看计划 123456abcdef'))
    assert '本人私聊' in str(runtime.sends[-1]['message']) and not runtime.fallback
    # Media/invalid/third-party parameters consume the command before services.
    await runtime.bot.handle_event(personal(MessageSegment.image('https://synthetic.invalid/a')+Message('我的考试计划'),2))
    assert '纯文本' in str(runtime.sends[-1]['message'])
    await runtime.bot.handle_event(personal('同意回顾 123456abcdef 明晚',3))
    assert 'YYYY-MM-DD' in str(runtime.sends[-1]['message'])
    assert not runtime.fallback


@pytest.mark.asyncio
async def test_unknown_other_owner_and_access_denied_have_no_body(runtime):
    await runtime.bot.handle_event(personal('创建考试计划 私密计划 | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=私密任务'))
    pid=runtime.context.service.repo.list(101)[0]['plan_id']
    await runtime.bot.handle_event(personal(f'查看计划 {pid}',2,user=102))
    assert '没有可操作的本人计划' in str(runtime.sends[-1]['message'])
    assert '私密' not in str(runtime.sends[-1]['message'])
    before=len(runtime.sends)
    runtime.allowed=False
    await runtime.bot.handle_event(personal(f'忘掉计划 {pid}',3))
    assert len(runtime.sends)==before and runtime.context.service.repo.get(101,pid)['status']=='active'
    assert not runtime.fallback
