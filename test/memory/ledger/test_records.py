import asyncio
import json
from types import SimpleNamespace
from datetime import datetime

import pytest
from test.autonomy.test_pending_atomic import isolated_redis
from src.services.persistence import StorageService
from src.services.persistence.backends import StorageBackend
from src.services.persistence.ledger import LedgerUnavailable
from src.services.persistence.ledger.repository import control_key
from src.services.memory.ledger.service import LedgerService
from src.services.memory.ledger.runtime import for_storage


@pytest.fixture
def ledger(isolated_redis):
    storage = StorageService.__new__(StorageService)
    storage._backend = StorageBackend(redis_provider=lambda: isolated_redis)
    return LedgerService(storage)


def source(message, user=101):
    return dict(bot_id='999', user_id=user, message_id=str(message), scene='private',
                occurred_at='2026-10-09T12:00:00+08:00', received_at='2026-10-09T12:00:01+08:00')


def run(ledger, operation, mid=None, text='', message=1, user=101, **kwargs):
    return asyncio.run(ledger.mutate(user, operation, mid, text, source(message, user), **kwargs))


def test_source_replace_forget_replay_and_explicit_relearn(ledger):
    first = run(ledger, 'auto', text='我喜欢乌龙茶')
    mid = first['memory_id']
    assert '依据：我喜欢乌龙茶' in ledger.explain(101, mid)
    assert ledger.list(101)[0].source_ref['message_id'] == '1'
    old = for_storage(ledger.storage, [101, 102])
    second = run(ledger, 'correct', mid, '现在不喜欢乌龙茶了', message=2)
    assert not old.current()  # First control from version 0 must invalidate existing requests.
    rows = ledger.list(101)
    assert [(m.content, m.status) for m in rows if m.status == 'active'] == [('不喜欢：乌龙茶', 'active')]
    assert next(m for m in rows if m.memory_id == mid).replaced_by == second['memory_id']
    assert run(ledger, 'forget', mid, message=3)['status'] == 'forgotten'
    assert all(m.content == '' and m.source_excerpt == '' and not m.source_ref for m in ledger.list(101))
    assert ledger.repo.notes(101) == {}
    assert run(ledger, 'auto', text='我喜欢乌龙茶')['memory_id'] == mid
    assert all(m.status == 'forgotten' for m in ledger.list(101))
    assert run(ledger, 'auto', text='我喜欢乌龙茶', message=4)['status'] == 'blocked'
    relearned = run(ledger, 'relearn', mid, '我喜欢乌龙茶', message=5)
    assert relearned['memory_id'] != mid
    assert next(m for m in ledger.list(101) if m.memory_id == mid).status == 'forgotten'
    assert len([m for m in ledger.list(101) if m.status == 'active']) == 1


def test_other_id_cross_topic_and_quoted_statement_do_not_mutate(ledger):
    mid = run(ledger, 'auto', text='我喜欢乌龙茶')['memory_id']
    before = ledger.repo.rows(101)
    assert run(ledger, 'correct', mid, '我喜欢红茶', message=2)['status'] == 'wrong_topic'
    assert run(ledger, 'forget', mid, message=3, user=102)['status'] == 'not_found'
    quoted = dict(source(4), quoted=True)
    assert asyncio.run(ledger.mutate(101, 'auto', None, '我不喜欢乌龙茶', quoted))['status'] == 'ignored'
    assert run(ledger, 'auto', text='他说我喜欢红茶', message=5)['status'] == 'ignored'
    assert ledger.repo.rows(101) == before


def test_forget_only_exact_mirrors_and_cancel_due(ledger):
    mid = run(ledger, 'auto', text='提醒我明天喝水', due_at=datetime(2020, 1, 1))['memory_id']
    user_note = ledger.storage.add_note(101, '自己的笔记', '提到了 ' + mid)
    assert ledger.storage.list_due_followups()
    run(ledger, 'forget', mid, message=2)
    assert not ledger.storage.list_due_followups()
    assert list(ledger.repo.notes(101)) == [user_note.note_id]
    assert ledger.storage.redis.hgetall(control_key(101))['state'].find('controlled') >= 0
    assert ledger.storage.redis.ttl(control_key(101)) == -1


def test_done_promise_stays_done_and_legacy_source_unknown(ledger):
    old = ledger.storage.add_relationship_memory(101, 'promise', '提醒我明天喝水', due_at=datetime(2020, 1, 1))
    ledger.storage.mark_relationship_done(101, old.memory_id)
    assert '未保存原始来源' in ledger.explain(101, old.memory_id)
    new = run(ledger, 'correct', old.memory_id, '提醒我明天喝水', message=2)
    row = next(m for m in ledger.list(101) if m.memory_id == new['memory_id'])
    assert row.status == 'done' and row.due_at == old.due_at
    assert not ledger.storage.list_due_followups()


def test_production_memory_fallback_is_unavailable():
    storage = StorageService()
    storage.redis = None
    ledger = LedgerService(storage)
    with pytest.raises(LedgerUnavailable):
        run(ledger, 'auto', text='我喜欢乌龙茶')
    view = for_storage(storage, [101])
    assert not view.available and view.controlled and view.history('b', 's', [{'content': '旧正文'}]) == []


def test_wrong_key_type_changes_no_business_data(ledger):
    mid = run(ledger, 'auto', text='我喜欢乌龙茶')['memory_id']
    before = ledger.repo.rows(101)
    client = ledger.storage.redis
    client.set('relationship:followups', 'wrong-type')
    with pytest.raises(LedgerUnavailable):
        run(ledger, 'forget', mid, message=2)
    assert ledger.repo.rows(101) == before


def test_response_lost_resumes_same_immutable_intent(ledger):
    mid = run(ledger, 'auto', text='我喜欢乌龙茶')['memory_id']
    client = ledger.storage.redis
    class LostResponse:
        def __getattr__(self, key):
            return getattr(client, key)
        def eval(self, script, nkeys, *args):
            result = client.eval(script, nkeys, *args)
            if args[nkeys] == 'reserve':
                raise ConnectionError('synthetic response loss')
            return result
    ledger.storage.redis = LostResponse()
    with pytest.raises(LedgerUnavailable):
        run(ledger, 'forget', mid, message=2)
    assert not for_storage(ledger.storage, [101]).available
    ledger.storage.redis = client
    result = run(ledger, 'correct', mid, '我喜欢红茶', message=2)
    assert result['status'] == 'forgotten'  # Reusing identity cannot rebind its original intent.
    assert all(not m.content for m in ledger.list(101))


def test_uncertain_request_without_server_receipt_still_closes_local_sources(ledger):
    mid = run(ledger, 'auto', text='我喜欢乌龙茶')['memory_id']
    client = ledger.storage.redis
    class LostBeforeServer:
        def __getattr__(self, key):
            return getattr(client, key)
        def eval(self, *args):
            raise ConnectionError('synthetic delivery uncertain before server receipt')
    ledger.storage.redis = LostBeforeServer()
    with pytest.raises(LedgerUnavailable):
        run(ledger, 'forget', mid, message=2)
    ledger.storage.redis = client
    assert not for_storage(ledger.storage, [101]).available
    # The original immutable plan is recovered; changed retry arguments do not matter.
    assert run(ledger, 'correct', mid, '我喜欢红茶', message=2)['status'] == 'forgotten'
    assert all(not m.content for m in ledger.list(101))


def test_cache_eviction_does_not_reauthorize_old_relearn(ledger):
    mid = run(ledger, 'auto', text='我喜欢乌龙茶')['memory_id']
    run(ledger, 'forget', mid, message=2)
    restored = run(ledger, 'relearn', mid, '我喜欢乌龙茶', message=3)['memory_id']
    run(ledger, 'forget', restored, message=4)
    for index in range(110):
        run(ledger, 'auto', text=f'我喜欢合成主题{index}', message=100 + index)
    assert run(ledger, 'relearn', mid, '我喜欢乌龙茶', message=3)['status'] == 'already_processed'
    assert not any(m.status == 'active' and '乌龙茶' in m.content for m in ledger.list(101))
