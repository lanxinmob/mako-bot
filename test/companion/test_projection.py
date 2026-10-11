from dataclasses import replace
from types import SimpleNamespace
import pytest

from src.core.config import Settings
from src.services.companion.commands import parse
from src.services.companion.projection import reply
from src.services.persistence.companion.models import spec_for
from src.services.delivery.effects.plans import build_plan
from src.services.delivery.state import DeliveryStore
from src.web.dashboard.presenters.companion import snapshot
from .conftest import execute,BASE


@pytest.mark.asyncio
async def test_dashboard_current_unknown_forgotten_and_paused(context,create,monkeypatch):
    import src.web.dashboard.presenters.companion as module
    monkeypatch.setattr('src.core.config.get_settings',lambda:Settings(_env_file=None,PLUGIN_ENABLE_LIST='chat,companion'))
    pid=await create()
    repo=context.service.repo
    spec=spec_for(101,pid+':reminder',*repo.frozen(101,pid+':reminder'))
    store=DeliveryStore(context.client,require_effects=True)
    claim=store.claim(spec,plan=build_plan(spec))
    context.client.ms=BASE+3600000
    store.begin_send(spec,claim.token); store.mark_unknown(spec.action_id,claim.token)
    data=snapshot(context.storage)
    assert data['available'] and data['enabled'] and data['items'][0]['reminder']['transport']=='unknown'
    await execute(context,f'忘掉计划 {pid}',2)
    item=snapshot(context.storage)['items'][0]
    assert item['title']=='' and item['tasks']==[] and item['reminder']['transport']=='unknown'
    context.storage.redis=None
    data=snapshot(context.storage)
    assert not data['available'] and data['items']==[] and '失败' in data['reason']


@pytest.mark.asyncio
async def test_reply_final_view_and_qualification_cancel_old_plaintext(context,create):
    pid=await create()
    text,view=reply(context.service,101,parse(f'查看计划 {pid}'),dict(status='query'),'999')
    assert '合成数学' in text
    sends=[]
    async def sender(): sends.append(text); return True
    assert not await view.send(sender,admit=lambda:False)
    await execute(context,f'忘掉计划 {pid}',2)
    assert not await view.send(sender,admit=lambda:True) and sends==[]


@pytest.mark.asyncio
async def test_companion_effect_plan_rejects_forged_target_or_keys(context,create):
    pid=await create()
    spec=spec_for(101,pid+':reminder',*context.service.repo.frozen(101,pid+':reminder'))
    assert 'companion_complete' in build_plan(spec).raw
    for changes in ({'target_type':'group'},{'source_key':'notes:102'},{'source_field':'foreign'},
                    {'revision_key':'relationship:101'},{'business_id':'arbitrary'}):
        with pytest.raises(ValueError):
            build_plan(replace(spec,**changes))
