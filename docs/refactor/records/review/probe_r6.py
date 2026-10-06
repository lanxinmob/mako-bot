"""Offline HEAD/current differential probes with immediate async substitutes."""
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path.cwd()))


def guard(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        assert not Path(str(args[0])).name.startswith('.env'), 'dotenv forbidden'
    assert event not in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'socket.sendto'}, 'network forbidden'


sys.addaudithook(guard)
source = subprocess.check_output(['git', 'show', 'HEAD:src/services/chat_context.py'], encoding='utf-8')
old = ModuleType('review_head_context')
sys.modules[old.__name__] = old
exec(compile(source, 'HEAD:chat_context.py', 'exec'), old.__dict__)
from src.services import chat_context as current
from src.services.retrieval.context import SearchContextBuilder as NativeBuilder
from src.services.retrieval import dependencies as native_dependencies


def run(coroutine):
    # All awaits target local immediate substitutes; no event loop/socketpair.
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coroutine.close()
    raise AssertionError('unexpected suspension in offline probe')


async def gather(*coroutines):
    return [await coroutine for coroutine in coroutines]


async def wait_for(coroutine, *, timeout):
    return await coroutine


def replacements(metrics):
    return dict(
        has_deepseek=lambda: False,
        get_settings=lambda: SimpleNamespace(search_cost_per_call=0.25, image_rate_limit_seconds=10),
        time=SimpleNamespace(perf_counter=lambda: 5.0, time=lambda: 100.0),
        asyncio=SimpleNamespace(gather=gather, wait_for=wait_for),
        search_metrics=metrics,
        logger=Mock(),
        decide_intents=lambda *_args, **_kwargs: [SimpleNamespace(name='search.web', args={})],
        is_correction_request=lambda text: False,
        is_dynamic_fact_query=lambda text: True,
    )


def differential_pipeline():
    for scenario in ['supported', 'unreadable', 'provider_error']:
        outputs = []
        for module in [old, current]:
            metrics = Mock()

            async def search(query, **kwargs):
                if scenario == 'provider_error':
                    raise RuntimeError('fixture provider unavailable')
                return [module.SearchResult(title='fixture', link='https://' + domain + '/evidence', snippet='2026-09-09', score=1.0) for domain in ['a.example', 'b.example']]

            async def fetch(url, **kwargs):
                return '' if scenario == 'unreadable' else '2026-09-09 今天 官方 数据 fixture'

            async def verifier(text, sources, correction_mode, disputed_answer):
                return {'status': 'supported', 'claims': [{'text': 'fixture fact', 'source_ids': ['S1', 'S2']}]}

            with patch.multiple(module, **replacements(metrics)):
                builder = module.SearchContextBuilder(search=search, fetch=fetch, verifier=verifier)
                outcome = run(builder.build('今天的数据', now=datetime(2026, 9, 9, tzinfo=timezone(timedelta(hours=8)))))
                metrics.record_pipeline.assert_called_once()
                assert outcome.success == (scenario == 'supported')
                assert outcome.provider_unavailable == (scenario == 'provider_error')
                outputs.append((asdict(outcome), metrics.record_pipeline.call_args, metrics.record_routing.call_args))
        assert outputs[0] == outputs[1], scenario
        print('PASS HEAD/current output and metrics:', scenario)


def late_dependency_and_deadlines():
    metrics = Mock()
    builder = current.SearchContextBuilder()
    timeouts = []
    model_calls = []

    async def timed(coroutine, *, timeout):
        timeouts.append(timeout)
        return await coroutine

    async def create(**kwargs):
        model_calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='fixture'))])

    with patch.multiple(current, **replacements(metrics)):
        assert run(builder.plan_queries('fixture')) == []
        with patch.multiple(current,
                            has_deepseek=lambda: True,
                            asyncio=SimpleNamespace(wait_for=timed, gather=gather),
                            get_deepseek_client=lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
                            get_deepseek_model=lambda: 'fixture-model',
                            extract_json_object=lambda raw: {'queries': ['fixture query'], 'status': 'supported'}):
            assert run(builder.plan_queries('fixture')) == ['fixture query']
            assert run(builder._verify('fixture', [], correction_mode=False, disputed_answer=''))['status'] == 'supported'
        assert timeouts == [12.0, 18.0]
        assert [c['max_tokens'] for c in model_calls] == [500, 900]
        assert all(c['model'] == 'fixture-model' for c in model_calls)
        outcome = current.SearchContextBuilder._finalize(current.SearchOutcome(search_calls=2), 4.0)
        assert outcome.estimated_cost == 0.5 and outcome.latency_ms == 1000.0
        limiter = current.ImageRateLimiter()
        assert limiter.allow(42) and not limiter.allow(42)
        with patch.object(current, 'time', SimpleNamespace(time=lambda: 111.0)):
            assert limiter.allow(42)
    print('PASS late legacy dependency patch, 12s/18s deadlines, static finalize, image clock')
    with patch.multiple(native_dependencies, **replacements(Mock())):
        assert run(NativeBuilder().plan_queries('fixture')) == []
    print('PASS new builder resolves default native dependencies')


differential_pipeline()
late_dependency_and_deadlines()
