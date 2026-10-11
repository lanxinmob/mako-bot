import asyncio
import json
import pytest

from src.services.companion.delivery import CompanionDelivery
from src.services.companion.scanning import CompanionScanner
from src.services.delivery.effects.worker import EffectWorker
from src.services.delivery.state import DeliveryStore
from src.services.memory.ledger.service import LedgerService
from .conftest import BASE,Bot,execute,immediate,source


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['cancel','forget','memory','permission'])
async def test_queued_control_has_zero_old_body_starts(context,create,change):
    pid = await create()
    context.client.ms=BASE+3600000
    async def queue(target,user,callback,**kwargs):
        if change in {'cancel','forget'}:
            await execute(context,f'{"取消" if change=="cancel" else "忘掉"}计划 {pid}',2)
        elif change=='memory':
            ledger=LedgerService(context.storage)
            await ledger.mutate(101,'auto',None,'我喜欢合成茶',source(2))
        else:
            context.allowed=False
        return await callback()
    delivery=CompanionDelivery(context.storage,schedule=queue,allowed=lambda _:context.allowed)
    assert not await delivery.deliver(Bot(context),101,pid+':reminder')
    assert context.sends==[]


@pytest.mark.asyncio
async def test_revocation_after_persisted_begin_wait_still_blocks_sdk(context,create,monkeypatch):
    pid=await create()
    context.client.ms=BASE+3600000
    delivery=CompanionDelivery(context.storage,schedule=immediate,allowed=lambda _:True)
    original=delivery.store.begin_send
    started,release=asyncio.Event(),asyncio.Event()
    original_thread=asyncio.to_thread
    async def thread(fn,*args,**kwargs):
        if fn==delivery.store.begin_send:
            value=await original_thread(original,*args,**kwargs)
            started.set()
            await release.wait()
            return value
        return await original_thread(fn,*args,**kwargs)
    monkeypatch.setattr(asyncio,'to_thread',thread)
    task=asyncio.create_task(delivery.deliver(Bot(context),101,pid+':reminder'))
    await started.wait()
    await execute(context,f'取消计划 {pid}',2)
    release.set()
    assert not await task and context.sends==[]
    aid=context.service.repo.get(101,pid)['steps']['reminder']['action_id']
    assert DeliveryStore(context.client).inspect(aid).state=='unknown'


@pytest.mark.asyncio
async def test_control_after_sdk_entry_preserves_real_ack_and_no_late_note(context,create):
    pid=await create()
    context.client.ms=BASE+3600000
    started,release=asyncio.Event(),asyncio.Event()
    class WaitingBot(Bot):
        async def send_private_msg(self,**kwargs):
            context.sends.append(kwargs); started.set(); await release.wait()
            return {'message_id':1}
    delivery=CompanionDelivery(context.storage,schedule=immediate,allowed=lambda _:True)
    task=asyncio.create_task(delivery.deliver(WaitingBot(context),101,pid+':reminder'))
    await started.wait()
    await execute(context,f'忘掉计划 {pid}',2)
    release.set()
    assert await task and len(context.sends)==1
    plan=context.service.repo.get(101,pid)
    assert plan['status']=='forgotten' and plan['title']=='' and context.storage.list_notes(101)==[]
    assert DeliveryStore(context.client).inspect(plan['steps']['reminder']['action_id']).state=='sent'
    assert not plan['steps']['reminder']['source_complete']
    from src.services.companion.projection import project
    assert '已停止正文补记' in project(context.service.repo,plan)['reminder']['effects']


@pytest.mark.asyncio
@pytest.mark.parametrize('timeout',[False,True])
async def test_unknown_reminder_is_not_retried_or_used_for_auto_review(context,create,timeout):
    pid=await create()
    await execute(context,f'同意回顾 {pid} 2026-10-09 16:00',2)
    context.client.ms=BASE+3600000
    bot=Bot(context,ack=False,error=timeout)
    delivery=CompanionDelivery(context.storage,schedule=immediate,allowed=lambda _:True)
    if timeout:
        with pytest.raises(TimeoutError):
            await delivery.deliver(bot,101,pid+':reminder')
    else:
        assert not await delivery.deliver(bot,101,pid+':reminder')
    context.client.ms=BASE+4*3600000
    scanner=CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:bot,schedule=immediate)
    await scanner.run(); await scanner.run()
    assert len(context.sends)==1
    plan=context.service.repo.get(101,pid)
    assert plan['steps']['review']['status']=='blocked'
    aid=plan['steps']['reminder']['action_id']
    assert DeliveryStore(context.client).inspect(aid).state=='unknown'
    assert (await execute(context,f'提交回顾 {pid} 完成=1 | 感受=a | 下次=b',3))['status']=='completed'
    assert DeliveryStore(context.client).inspect(aid).state=='unknown'


@pytest.mark.asyncio
async def test_sent_without_source_completion_blocks_review_then_recovers_effect_only(context,create,monkeypatch):
    pid=await create()
    await execute(context,f'同意回顾 {pid} 2026-10-09 16:00',2)
    context.client.ms=BASE+3600000
    import src.services.companion.delivery as module
    async def defer(attempt):
        pass
    monkeypatch.setattr(module,'settle_confirmed',defer)
    assert await CompanionDelivery(context.storage,schedule=immediate,allowed=lambda _:True).deliver(
        Bot(context),101,pid+':reminder')
    context.client.ms=BASE+4*3600000
    scanner=CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:Bot(context),schedule=immediate)
    await scanner.run()
    assert len(context.sends)==1
    aid=context.service.repo.get(101,pid)['steps']['reminder']['action_id']
    await EffectWorker(context.client).run_action(aid)
    await scanner.run()
    assert len(context.sends)==2


@pytest.mark.asyncio
async def test_expired_window_has_no_late_send_even_after_restart(context,create):
    pid=await create()
    context.client.ms=BASE+5400000  # Exact exclusive reminder window end.
    scanner=CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:Bot(context),schedule=immediate)
    await scanner.run()
    assert context.sends==[] and context.service.repo.get(101,pid)['steps']['reminder']['status']=='expired'
    await scanner.run()
    assert context.sends==[]


@pytest.mark.asyncio
async def test_review_revoked_in_queue_cannot_start_and_unknown_cannot_reconsent(context,create):
    pid=await create()
    context.client.ms=BASE+3600000
    await CompanionDelivery(context.storage,schedule=immediate,allowed=lambda _:True).deliver(Bot(context),101,pid+':reminder')
    await execute(context,f'同意回顾 {pid} 2026-10-09 16:00',2)
    context.client.ms=BASE+4*3600000
    async def queue(target,user,callback,**kwargs):
        await execute(context,f'撤销回顾 {pid}',3)
        return await callback()
    assert not await CompanionDelivery(context.storage,schedule=queue,allowed=lambda _:True).deliver(Bot(context),101,pid+':review')
    assert len(context.sends)==1
    # Proven-before-begin rejection allows a new explicitly timed authorization.
    assert (await execute(context,f'同意回顾 {pid} 2026-10-09 17:00',4))['status']=='active'
    context.client.ms=BASE+5*3600000
    assert not await CompanionDelivery(context.storage,schedule=immediate,allowed=lambda _:True).deliver(Bot(context,ack=False),101,pid+':review')
    assert (await execute(context,f'同意回顾 {pid} 2026-10-09 18:00',5))['status']=='transport_started'
    # Owner's "not delivered" finding does not prove that transport never began.
    aid=context.service.repo.get(101,pid)['steps']['review']['action_id']
    assert DeliveryStore(context.client).reconcile(aid,delivered=False,operator_id='1').ok
    assert (await execute(context,f'同意回顾 {pid} 2026-10-09 18:00',6))['status']=='transport_started'
