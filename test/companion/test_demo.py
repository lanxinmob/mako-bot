"""Optional exported evidence uses actual Redis states and fake QQ receipts."""
import json
import os
from pathlib import Path
import pytest

from src.services.companion.delivery import CompanionDelivery
from src.services.companion.scanning import CompanionScanner
from src.services.companion.projection import project
from src.services.companion.workflow import CompanionService
from src.services.companion.commands import parse
from .conftest import BASE,Bot,execute,immediate,source


@pytest.mark.asyncio
async def test_export_complete_flow_and_four_failure_boundaries(context,create):
    evidence=dict(scope='synthetic OneBot ACK, isolated Redis, fixed Redis TIME; no real QQ/model',timeline=[],failures=[])
    pid=await create()
    repo=context.service.repo
    def capture(stage,user,plan):
        item=project(repo,repo.get(user,plan))
        rows=context.client.hgetall(f'notes:{user}')
        return dict(stage=stage,plan=item,private_notes={k:json.loads(v) for k,v in rows.items()},
                    qq_sdk_starts=len([s for s in context.sends if s['user_id']==user]))
    evidence['timeline'].append(capture('created',101,pid))
    context.client.ms=BASE+3600000
    delivery=CompanionDelivery(context.storage,schedule=immediate,allowed=lambda _:True)
    assert await delivery.deliver(Bot(context),101,pid+':reminder')
    evidence['timeline'].append(capture('reminder_ack_and_source_complete',101,pid))
    await execute(context,f'同意回顾 {pid} 2026-10-09 16:00',2)
    evidence['timeline'].append(capture('review_explicitly_consented',101,pid))
    context.client.ms=BASE+4*3600000
    assert await delivery.deliver(Bot(context),101,pid+':review')
    await execute(context,f'提交回顾 {pid} 完成=1 | 感受=紧张 | 下次=提前整理错题',3)
    evidence['timeline'].append(capture('self_review_completed',101,pid))
    assert evidence['timeline'][-1]['qq_sdk_starts']==2

    context.client.ms=BASE
    quiet=await create(4,user=102)
    context.client.ms=BASE+3600000
    await delivery.deliver(Bot(context),102,quiet+':reminder')
    context.client.ms=BASE+4*3600000
    await CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:Bot(context),schedule=immediate).run()
    evidence['failures'].append(capture('no_review_consent_no_invitation',102,quiet))
    assert evidence['failures'][-1]['qq_sdk_starts']==1

    context.client.ms=BASE
    unknown=await create(5,user=103)
    await execute(context,f'同意回顾 {unknown} 2026-10-09 16:00',6,user=103)
    context.client.ms=BASE+3600000
    assert not await delivery.deliver(Bot(context,ack=False),103,unknown+':reminder')
    context.client.ms=BASE+4*3600000
    await CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:Bot(context),schedule=immediate).run()
    evidence['failures'].append(capture('unknown_receipt_no_retry_or_review',103,unknown))
    assert evidence['failures'][-1]['qq_sdk_starts']==1

    context.client.ms=BASE
    cancelled=await create(7,user=104)
    context.client.ms=BASE+3600000
    async def cancel_queue(target,user,callback,**kwargs):
        await execute(context,f'取消计划 {cancelled}',8,user=104)
        return await callback()
    await CompanionDelivery(context.storage,schedule=cancel_queue,allowed=lambda _:True).deliver(Bot(context),104,cancelled+':reminder')
    evidence['failures'].append(capture('cancelled_after_queue_zero_sdk_starts',104,cancelled))
    assert evidence['failures'][-1]['qq_sdk_starts']==0

    context.client.ms=BASE
    forgotten=await create(9,user=105)
    await execute(context,f'忘掉计划 {forgotten}',10,user=105)
    await CompanionService(context.storage).execute(105,parse('创建考试计划 合成数学 | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=复习章节；练习真题'),source(9,105))
    evidence['failures'].append(capture('forgotten_then_old_create_replayed_after_service_reconstruction',105,forgotten))
    assert evidence['failures'][-1]['plan']['title']=='' and evidence['failures'][-1]['private_notes']=={}
    context.client.ms=BASE+5400000
    await CompanionScanner(context.service,allowed=lambda _:True,bot_lookup=lambda _:Bot(context),schedule=immediate).run()
    assert len(context.sends)==4
    target=os.environ.get('MAKO_C3_DEMO')
    if target:
        Path(target).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
