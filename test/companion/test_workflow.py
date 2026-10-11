import asyncio
import json
import pytest

from src.services.companion.commands import parse
from src.services.companion.projection import project,format_plan
from src.services.companion.scanning import CompanionScanner
from src.services.persistence.companion.repository import key
from src.services.persistence.companion.lifecycle import update
from .conftest import execute,source,Bot,immediate,BASE


@pytest.mark.asyncio
async def test_complete_workflow_has_two_separate_confirmed_sends(context,create):
    pid = await create()
    repo = context.service.repo
    plan = repo.get(101,pid)
    assert plan['consent'] == 'none' and list(plan['steps']) == ['reminder']
    notes = context.storage.list_notes(101)
    assert len(notes)==1 and notes[0].category=='companion' and notes[0].visibility=='private'
    assert context.storage.list_relationship_memories(101)==[]
    scanner = CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:Bot(context),schedule=immediate)
    context.client.ms = BASE+3600000
    assert (await scanner.run())[0][1]=='sent'
    plan = repo.get(101,pid)
    assert plan['steps']['reminder']['source_complete'] and plan['status']=='active'
    old_source = repo.frozen(101,pid+':reminder')
    assert (await execute(context,f'同意回顾 {pid} 2026-10-09 16:00',2))['status']=='active'
    assert repo.frozen(101,pid+':reminder') == old_source
    context.client.ms = BASE+4*3600000
    await scanner.run(); await scanner.run()
    assert len(context.sends)==2 and '回顾邀请' in str(context.sends[-1]['message'])
    result = await execute(context,f'提交回顾 {pid} 完成=1 | 感受=紧张 | 下次=提前整理错题',3)
    assert result['status']=='completed'
    text = format_plan(project(repo,repo.get(101,pid)))
    assert '完成 1/2' in text and '本人感受：紧张' in text and '提前整理错题' in text
    assert (await execute(context,f'提交回顾 {pid} 完成=2 | 感受=不同内容 | 下次=不同建议',3))['duplicate']
    await scanner.run()
    assert len(context.sends)==2 and '紧张' in repo.get(101,pid)['review']['feeling']


@pytest.mark.asyncio
async def test_no_consent_no_invitation_and_silent_deadline(context,create):
    pid = await create()
    scanner = CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:Bot(context),schedule=immediate)
    context.client.ms = BASE+3600000
    await scanner.run()
    context.client.ms = BASE+3*3600000+604800000
    await scanner.run()
    assert context.service.repo.get(101,pid)['status']=='closed' and len(context.sends)==1


@pytest.mark.asyncio
async def test_concurrent_capacity_and_separate_users(context,create):
    first,second = await asyncio.gather(create(1),create(2))
    assert first == second
    assert len(context.service.repo.list(101))==1
    other = await create(3,user=102)
    assert other != first
    assert (await execute(context,f'忘掉计划 {first}',4,user=102))['status']=='not_found'


@pytest.mark.asyncio
async def test_edit_resets_consent_and_only_new_reminder_source(context,create):
    pid = await create()
    await execute(context,f'同意回顾 {pid} 2026-10-09 16:00',2)
    before = context.service.repo.get(101,pid)
    await execute(context,f'修改计划 {pid} 任务=复习新章节',3)
    after = context.service.repo.get(101,pid)
    assert after['content_revision']==2 and after['consent']=='revoked'
    assert after['steps']['reminder']['revision']!=before['steps']['reminder']['revision']
    assert context.service.repo.frozen(101,pid+':review') is None
    assert len(context.storage.list_notes(101))==1


@pytest.mark.asyncio
@pytest.mark.parametrize('terminal',['cancelled','completed','closed','forgotten'])
async def test_terminal_command_matrix_never_reactivates(context,create,terminal):
    pid = await create()
    if terminal=='cancelled':
        await execute(context,f'取消计划 {pid}',2)
    elif terminal=='forgotten':
        await execute(context,f'忘掉计划 {pid}',2)
    elif terminal=='completed':
        context.client.ms = BASE+3*3600000
        await execute(context,f'提交回顾 {pid} 完成=无 | 感受=一般 | 下次=调整',2)
    else:
        context.client.ms = BASE+3*3600000+604800000
        update(context.service.repo,101,pid)
    for n,text in enumerate([f'同意回顾 {pid} 2026-10-10 16:00',f'撤销回顾 {pid}',
                              f'修改计划 {pid} 任务=新任务',f'提交回顾 {pid} 完成=无 | 感受=a | 下次=b']):
        assert (await execute(context,text,10+n))['status'] in {'ended','forgotten','invalid_time'}
        assert context.service.repo.get(101,pid)['status']==terminal


@pytest.mark.asyncio
async def test_deadline_and_future_time_checked_by_redis(context,create):
    pid = await create()
    context.client.ms = BASE+3*3600000+604800000-1
    assert (await execute(context,f'提交回顾 {pid} 完成=无 | 感受=a | 下次=b',2))['status']=='completed'
    assert context.service.repo.get(101,pid)['review']['completed']==[]
    pid2 = await create(3,user=102)  # Original literal is now stale.
    assert not pid2 or context.service.repo.get(102,pid2) is None


@pytest.mark.asyncio
async def test_submit_exact_deadline_closes_without_false_completion(context,create):
    pid = await create()
    context.client.ms=BASE+3*3600000+604800000
    assert (await execute(context,f'提交回顾 {pid} 完成=1 | 感受=a | 下次=b',2))['status']=='closed'
    assert context.service.repo.get(101,pid)['review'] is None
