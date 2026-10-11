import asyncio
import json
import pytest
from types import SimpleNamespace

from src.services.companion.commands import parse
from src.services.companion.workflow import CompanionService
from src.services.companion.projection import reply
from src.services.memory.ledger.runtime import for_storage
from src.services.memory.ledger.service import LedgerService
from src.services.persistence.companion.repository import key,CompanionUnavailable
from src.services.persistence.ledger.repository import LedgerUnavailable,control_key
from .conftest import execute,source,BASE


@pytest.mark.asyncio
async def test_new_create_id_collision_never_overwrites_forgotten_record(context,create,monkeypatch):
    pid=await create()
    await execute(context,f'忘掉计划 {pid}',2)
    before=context.service.repo.get(101,pid)
    monkeypatch.setattr('src.services.companion.workflow.uuid.uuid4',lambda:SimpleNamespace(hex=pid+'0'*20))
    assert await create(3)==pid
    assert context.service.repo.get(101,pid)==before


@pytest.mark.asyncio
async def test_startup_recovers_reserved_create_even_before_any_plan_exists(context):
    from src.services.companion.scanning import CompanionScanner
    from .conftest import Bot,immediate
    command=parse('创建考试计划 合成数学 | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=复习章节')
    client=context.client
    class Lost:
        def __getattr__(self,name): return getattr(client,name)
        def eval(self,script,nkeys,*args):
            result=client.eval(script,nkeys,*args)
            if args[nkeys]=='reserve': raise ConnectionError('synthetic lost reservation')
            return result
    context.storage.redis=Lost()
    with pytest.raises(CompanionUnavailable):
        await context.service.execute(101,command,source(1))
    context.storage.redis=client
    import src.services.persistence.ledger.repository as module
    module._uncertain.clear()
    scanner=CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:Bot(context),schedule=immediate)
    await scanner.run()
    assert len(context.service.repo.list(101))==1 and context.sends==[]


@pytest.mark.asyncio
async def test_invalid_edit_is_metadata_only_and_does_not_cancel_old_source(context,create):
    pid=await create()
    before=context.service.repo.get(101,pid)
    source_before=context.service.repo.frozen(101,pid+':reminder')
    result=await execute(context,f'修改计划 {pid} 提醒=2026-10-09 12:01',2)
    assert result['status']=='invalid_time'
    assert context.service.repo.get(101,pid)==before
    assert context.service.repo.frozen(101,pid+':reminder')==source_before


@pytest.mark.asyncio
@pytest.mark.parametrize('loss',['reserve','apply','before_server','restart'])
async def test_unknown_control_closes_c2_and_new_query_recovers_original_intent(context,create,loss):
    pid=await create()
    client=context.client
    class Lost:
        def __getattr__(self,name):
            return getattr(client,name)
        def eval(self,script,nkeys,*args):
            if loss=='before_server':
                raise ConnectionError('synthetic outcome unknown')
            result=client.eval(script,nkeys,*args)
            if args[nkeys]==('apply' if loss=='apply' else 'reserve'):
                raise ConnectionError('synthetic lost response')
            return result
    context.storage.redis=Lost()
    with pytest.raises(CompanionUnavailable):
        await execute(context,f'忘掉计划 {pid}',2)
    assert not for_storage(context.storage,[101]).available
    context.storage.redis=client
    if loss=='restart':
        import src.services.persistence.ledger.repository as module
        module._uncertain.clear()  # Isolated fixture; model loss of process-local state.
    await CompanionService(context.storage).execute(101,parse('我的考试计划'),source(3))
    assert context.service.repo.get(101,pid)['status']=='forgotten'
    assert for_storage(context.storage,[101]).available
    assert context.storage.list_notes(101)==[]
    assert (await execute(context,f'同意回顾 {pid} 2026-10-09 16:00',2))['status']=='forgotten'


@pytest.mark.asyncio
async def test_forget_clears_cached_and_frozen_plaintext_and_old_event_after_100(context,create):
    pid=await create()
    await execute(context,f'同意回顾 {pid} 2026-10-09 16:00',2)
    unrelated=context.storage.add_note(101,'别的私人笔记','保留内容')
    ledger=LedgerService(context.storage)
    relation=await ledger.mutate(101,'auto',None,'我喜欢合成茶',source(70))
    old=for_storage(context.storage,[101])
    command=parse('我的考试计划')
    text,view=reply(context.service,101,command,dict(status='query'),'999')
    assert '合成数学' in text
    await execute(context,f'忘掉计划 {pid}',3)
    assert not view.current() and not old.current()
    assert [n.note_id for n in context.storage.list_notes(101) if n.category!='relationship']==[unrelated.note_id]
    assert ledger.list(101)[0].content=='喜欢：合成茶'
    state=context.service.repo.state(101)
    assert state['controlled'] and int(state['cutoff_ns'])>0
    for kind in ('plans','steps','operations'):
        assert '合成数学' not in str(context.client.hgetall(key(kind,101)))
        assert '复习章节' not in str(context.client.hgetall(key(kind,101)))
    forgotten=context.service.repo.get(101,pid)
    assert forgotten['exam_ms'] is None and forgotten['remind_ms'] is None and forgotten['review_ms'] is None
    assert forgotten['exam_iso']=='' and forgotten['remind_iso']==''
    for n in range(105):
        await execute(context,f'取消计划 {pid}',100+n)
    result=await create(1)
    assert not result or result==pid
    assert len(context.service.repo.list(101))==1
    assert context.service.repo.get(101,pid)['status']=='forgotten'


@pytest.mark.asyncio
async def test_wrong_type_preserves_business_and_same_original_recovers(context,create):
    pid=await create()
    before=context.service.repo.get(101,pid)
    context.client.delete('mako:companion:v1:due')
    context.client.set('mako:companion:v1:due','wrong')
    with pytest.raises(CompanionUnavailable):
        await execute(context,f'忘掉计划 {pid}',2)
    stored=json.loads(context.client.hget(key('plans',101),pid))
    assert stored==before
    context.client.delete('mako:companion:v1:due')
    await context.service.reconcile(101)
    assert context.service.repo.get(101,pid)['status']=='forgotten'


@pytest.mark.asyncio
async def test_c2_query_can_reconcile_c3_pending_original_without_new_authorization(context,create):
    pid=await create()
    client=context.client
    class Lost:
        def __getattr__(self,name): return getattr(client,name)
        def eval(self,script,nkeys,*args):
            result=client.eval(script,nkeys,*args)
            if args[nkeys]=='reserve': raise ConnectionError('synthetic lost reservation')
            return result
    context.storage.redis=Lost()
    with pytest.raises(CompanionUnavailable): await execute(context,f'忘掉计划 {pid}',2)
    context.storage.redis=client
    await LedgerService(context.storage).reconcile(101)
    assert context.service.repo.get(101,pid)['status']=='forgotten'


@pytest.mark.asyncio
async def test_unavailable_redis_has_no_memory_fallback(context):
    context.storage.redis=None
    with pytest.raises(LedgerUnavailable):
        await context.service.execute(101,parse('我的考试计划'),source(1))
