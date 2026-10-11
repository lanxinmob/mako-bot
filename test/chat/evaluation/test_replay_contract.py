import asyncio
import copy
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.services.chat.evaluation.schema import load_cases, validate
from src.services.chat.evaluation.clock import VirtualClock
from src.services.chat.evaluation.isolation import environment
from src.services.chat.evaluation.runner import Replay

DATA = Path(__file__).resolve().parents[3] / 'eval/group_rhythm/cases.jsonl'


def test_frozen_labels_and_malformed_input():
    cases, digest = load_cases(DATA)
    assert len(cases) == 40
    manifest = __import__('json').loads(DATA.with_name('frozen.json').read_text(encoding='utf-8'))
    assert digest == manifest['sha256']
    invalid = copy.deepcopy(cases[0])
    invalid['checkpoints'][0]['target_message_id'] = 'does-not-exist'
    with pytest.raises(ValueError, match='unknown target'):
        validate(invalid)
    invalid = copy.deepcopy(cases[0])
    invalid['events'][0]['at_ms'] = invalid['end_at_ms'] + 1
    with pytest.raises(ValueError, match='outside'):
        validate(invalid)


def test_changed_context_retries_once_without_repeating_memory_or_admission():
    cases, _ = load_cases(DATA)
    case = next(c for c in cases if c['case_id'] == '6-3')
    async def run():
        clock = VirtualClock()
        with environment(clock) as settings:
            replay = Replay(case, clock, settings)
            absorb = Mock()
            replay.deps.services.relationship.absorb_user_message = absorb
            admit = replay.deps.rhythm.admit
            replay.deps.rhythm.admit = Mock(wraps=admit)
            report = await replay.run()
            assert report['passed'], report['errors']
            assert len(report['generations']) == 2
            assert '只看前两章' in report['generations'][1]['context']
            assert len(report['sends']) == 1
            absorb.assert_called_once()
            replay.deps.rhythm.admit.assert_called_once()
    asyncio.run(run())


def test_reply_after_generation_changes_again_is_bounded():
    cases, _ = load_cases(DATA)
    case = copy.deepcopy(next(c for c in cases if c['case_id'] == '6-3'))
    case['generation']['g1/a1']['delay_ms'] = 1000
    case['events'].append(dict(at_ms=5500, seq=10001, op='inbound', group='g1',
        message_id='b2', user='B', text='再补充条件'))
    case['events'].sort(key=lambda e: (e['at_ms'], e['seq']))
    async def run():
        clock = VirtualClock()
        with environment(clock) as settings:
            replay = Replay(case, clock, settings)
            report = await replay.run()
            assert len(report['generations']) == 2
            assert report['sends'] == []
    asyncio.run(run())


def test_metric_counts_group_windows_and_exact_invalidated_candidate():
    from types import SimpleNamespace as NS
    replay = object.__new__(Replay)
    replay.errors = []
    replay.groups = {'g1': 1001, 'g2': 1002}
    first = NS(group_id='1001', target_message_id='a1')
    second = NS(group_id='1001', target_message_id='a1')
    replay.candidates = [first, second]
    common = dict(normal_transport=True, start_ms=100, end_ms=200)
    replay.case = {'opportunities': [
        dict(common, id='silent', kind='forbid_reply', group='g2', target_message_id='b1'),
        dict(common, id='stale', kind='invalidated_candidate', group='g1', target_message_id='a1',
             candidate_of=dict(group='g1', message_id='a1', ordinal=1))]}
    replay.deps = NS(sends=[dict(category='chat', target='g1/a1', at_ms=150, candidate_ordinal=2)])
    metrics = replay.metrics()
    assert metrics['forbid_reply'] == dict(numerator=0, denominator=1)
    assert metrics['invalidated_candidate'] == dict(numerator=0, denominator=1)
    replay.deps.sends[0]['candidate_ordinal'] = 1
    assert replay.metrics()['invalidated_candidate']['numerator'] == 1
