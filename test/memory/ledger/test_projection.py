import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from src.web.dashboard.service import DashboardService
from src.services.memory.ledger.runtime import for_storage
from src.services.persistence.ledger.repository import control_key
from test.memory.ledger.test_records import ledger, isolated_redis, run


def test_dashboard_discovers_control_outside_paginated_records(ledger, monkeypatch):
    mid = run(ledger, 'auto', text='我喜欢乌龙茶')['memory_id']
    ledger.storage.set_profile(101, '合成人物', '旧画像乌龙茶')
    run(ledger, 'forget', mid, message=2)
    vector = Mock(side_effect=AssertionError('unscoped vectors forbidden'))
    monkeypatch.setattr(ledger.storage, 'list_long_term_memory_points', vector)
    data = DashboardService(ledger.storage).get_frontend_summary()['data']
    assert data['relationship_memories'][0]['status'] == 'forgotten'
    assert data['relationship_memories'][0]['source_excerpt'] == ''
    assert data['people'][0]['focus'] == '历史档案，暂停使用'
    assert data['raw']['profiles'][0]['profile_state'] == '历史档案，暂停使用'
    # A window with no personal records still must not re-expose old shared vectors.
    monkeypatch.setattr(ledger.storage, 'list_all_relationship_memories', lambda **kwargs: [])
    monkeypatch.setattr(ledger.storage, 'list_profiles', lambda: [])
    data = DashboardService(ledger.storage).get_frontend_summary()['data']
    assert not data['long_term_memory'] and data['memory_control'][0]['user_id'] == 101
    vector.assert_not_called()


def test_malformed_control_state_and_control_discovery_failure_close_sources(ledger, monkeypatch):
    ledger.storage.redis.hset(control_key(101), 'state', json.dumps({'revision': 1}))
    assert not for_storage(ledger.storage, [101]).available
    vector = Mock(side_effect=AssertionError('unscoped vectors forbidden'))
    monkeypatch.setattr(ledger.storage, 'list_long_term_memory_points', vector)
    data = DashboardService(ledger.storage).get_frontend_summary()['data']
    assert not data['long_term_memory']
    assert data['memory_control'][0]['persistence'] == '记忆控制读取失败'
    vector.assert_not_called()
