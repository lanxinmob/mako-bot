"""Independent offline storage boundary probes; run from project root."""
import ast
import inspect
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path.cwd()))


def guard(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        if Path(str(args[0])).name.startswith('.env'):
            raise RuntimeError('dotenv access forbidden')
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.bind', 'socket.sendto'}:
        raise RuntimeError('network forbidden')


sys.addaudithook(guard)
old_text = subprocess.check_output(['git', 'show', 'HEAD:src/services/storage.py'], encoding='utf-8')
old = ModuleType('review_head_storage')
sys.modules[old.__name__] = old
exec(compile(old_text, 'HEAD:storage.py', 'exec'), old.__dict__)
from src.services.persistence import facade
from src.services.persistence.backends import redis as backend_module
from src.services.persistence.backends.memory import MemoryStorage
from src.services import storage as shim

settings = SimpleNamespace(max_history_turns=1, global_memory_max_records=1000)


def settings_provider():
    return settings


class FakeRedis:
    def __init__(self, values=None):
        self.values = values or {}
        self.writes = []

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.writes.append((key, value))
        self.values[key] = value


def signatures_and_forwarding():
    tree = ast.parse(Path('src/services/persistence/facade.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    count = 0
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef) or method.name.startswith('_') or method.name in {'redis', 'settings', 'backend'}:
            continue
        original = inspect.signature(getattr(old.StorageService, method.name))
        revised = inspect.signature(getattr(facade.StorageService, method.name))
        assert original == revised, method.name
        call = method.body[0].value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        repo_name = call.func.value.func.id
        instance = object.__new__(facade.StorageService)
        instance._backend = object()
        positional, keywords = [], {}
        for name, parameter in original.parameters.items():
            if name == 'self':
                continue
            if parameter.kind == inspect.Parameter.KEYWORD_ONLY:
                keywords[name] = object()
            else:
                positional.append(object())
        expected = original.bind(instance, *positional, **keywords).arguments
        expected.pop('self')
        with patch.object(facade, repo_name) as repo:
            getattr(instance, method.name)(*positional, **keywords)
            repo.assert_called_once_with(instance._backend)
            calls = repo.return_value.method_calls
            assert len(calls) == 1 and calls[0][0] == method.name
            actual = original.bind(None, *calls[0][1], **calls[0][2]).arguments
            actual.pop('self')
            assert actual == expected, method.name
        count += 1
    print('PASS facade signatures and argument forwarding:', count)


def connection_and_memory():
    with patch.object(facade, 'get_settings', settings_provider), patch.object(backend_module, 'get_settings', settings_provider):
        first, second = FakeRedis(), FakeRedis()
        with patch.object(facade, 'get_redis', side_effect=[first, second]) as provider:
            service = facade.StorageService()
            assert service.redis is second
            service.redis = None
            assert service.redis is None and provider.call_count == 2
            service.redis = first
            assert service.redis is first and provider.call_count == 2
        with patch.object(facade, 'get_redis', return_value=None):
            a, b = facade.StorageService(), facade.StorageService()
            assert a.backend is not b.backend
            assert a.backend.memory is b.backend.memory is shim._memory
            a.save_history('review_offline', [{'content': 'shared'}])
            assert b.get_history('review_offline') == [{'content': 'shared'}]
    print('PASS automatic redis refresh, sticky explicit None/client, default memory identity')


def payload_and_legacy():
    with patch.object(facade, 'get_settings', settings_provider), patch.object(backend_module, 'get_settings', settings_provider):
        before = object.__new__(old.StorageService)
        after = object.__new__(facade.StorageService)
        old._memory = old.MemoryStorage()
        history = [{'content': str(i)} for i in range(4)]
        for service in [before, after]:
            service.redis = FakeRedis({'group_42': json.dumps(history)})
            service.settings = settings
            assert service.get_history('group_42') == history
            assert json.loads(service.redis.values['chat:history:group_42']) == history[-2:]
            service.redis = None
        after.backend.memory = MemoryStorage()
        for payload in [
            {'trace_id': 'legacy', 'created_at': '2024-01-02T03:04:05', 'trace_type': 'decision.sent', 'user_id': '42', 'payload': {'target_id': 99}},
            {'trace_id': 'old', 'created_at': '2024-01-02T03:04:05', 'payload': 'invalid', 'group_id': 'bad'},
        ]:
            assert before.append_thought_trace(payload).model_dump() == after.append_thought_trace(payload).model_dump()
        for value in ['', 'approve_custom', '取消', 'send_report', 'unknown']:
            payload = {'event_id': 'event', 'created_at': '2024-01-02T03:04:05', 'event_type': value}
            assert before.append_progress_event(payload).model_dump() == after.append_progress_event(payload).model_dump()
        for value in ['plain legacy', '[1,2]', 'null', '{"user_id":7}', 'bad json']:
            assert before._parse_profile_payload(value, key='user_profile:42') == after._parse_profile_payload(value, key='user_profile:42')
    print('PASS legacy history key/clipping, old trace/progress/profile normalization differential')


def injected_adapter_regression():
    for cls, label in [(old.StorageService, 'HEAD'), (facade.StorageService, 'current')]:
        with patch.object(backend_module, 'get_settings', side_effect=RuntimeError('unexpected config initialization')):
            service = object.__new__(cls)
            try:
                service.redis = FakeRedis()
                service.settings = settings
                service.save_history('injected', [])
            except RuntimeError as exc:
                print('REGRESSION', label, str(exc))
                assert label == 'current'
            else:
                print('PASS', label, 'explicit adapter needs no global config')
                assert label == 'HEAD'


signatures_and_forwarding()
connection_and_memory()
payload_and_legacy()
injected_adapter_regression()
