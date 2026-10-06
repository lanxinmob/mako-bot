"""Independent R4 constants/legacy exports check; no application startup."""
import ast
import importlib
from pathlib import Path
import subprocess
import sys
from types import ModuleType

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path.cwd()))


def guard(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        assert not Path(str(args[0])).name.startswith('.env'), 'dotenv forbidden'
    assert event not in {'socket.connect', 'socket.getaddrinfo', 'socket.bind'}, 'network forbidden'


sys.addaudithook(guard)
source = subprocess.check_output(['git', 'show', 'HEAD:src/web/dashboard/service.py'], encoding='utf-8')
baseline = {n.targets[0].id: n.value for n in ast.parse(source).body if isinstance(n, ast.Assign)}
stub = ModuleType('src.services.storage')


class ForbiddenStorage:
    def __init__(self):
        raise AssertionError('storage initialization forbidden')


stub.StorageService = ForbiddenStorage
sys.modules[stub.__name__] = stub
current_service = importlib.import_module('src.web.dashboard.service')
checked = []
for name in ['catalog', 'defaults', 'evidence']:
    module_name = 'src.web.dashboard.roadmap.' + name
    module = importlib.import_module(module_name)
    path = Path('src/web/dashboard/roadmap') / (name + '.py')
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign):
            key = node.targets[0].id
            assert ast.dump(node.value) == ast.dump(baseline[key]), key
            assert getattr(current_service, key) is getattr(module, key), key
            checked.append(key)
assert set(checked) == set(baseline) and len(checked) == 10
print('PASS: all 10 constant expression ASTs, ordering and legacy object identities')
print('LIMIT: current DashboardService also contains concurrent R5 edits; no R5 acceptance claimed')
