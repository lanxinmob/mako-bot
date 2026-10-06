import ast
import importlib
from collections import Counter
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import Mock

root = Path.cwd().resolve()
assert (root / "pyproject.toml").is_file()
sys.path.insert(0, str(root))
sys.dont_write_bytecode = True


def deny_external(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        name = Path(str(args[0])).name
        assert name != '.env' and not name.startswith('.env.'), 'env read denied'
    assert event not in {'socket.connect', 'socket.getaddrinfo'}, 'network denied'


sys.addaudithook(deny_external)
base_text = subprocess.check_output([
    'git', 'show', '8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9:src/web/dashboard/service.py'
]).decode('utf-8')
path = root / 'src/web/dashboard/service.py'
current_text = path.read_text(encoding='utf-8')
base_tree, current_tree = ast.parse(base_text), ast.parse(current_text)
get_class = lambda tree: next(n for n in tree.body if isinstance(n, ast.ClassDef))
# R5 moves methods; full JSON and storage-call equivalence below are the contract.
constant_nodes = {
    n.targets[0].id: n for n in base_tree.body if isinstance(n, ast.Assign)
}
assert len(constant_nodes) == 10

storage_stub = types.ModuleType('src.services.storage')
storage_stub.StorageService = Mock(side_effect=AssertionError('real storage forbidden'))
sys.modules[storage_stub.__name__] = storage_stub
# Baseline uses storage; current implementation uses persistence.
sys.modules["src.services.persistence"] = storage_stub
from src.models import schemas as models
from src.web.dashboard import schemas

stamp = datetime(2026, 1, 2, 3, 4, 5)
for namespace in (models, schemas):
    for model in vars(namespace).values():
        if model is models.BaseModel:
            continue
        if isinstance(model, type) and issubclass(model, models.BaseModel):
            for field in model.model_fields.values():
                if field.default_factory == datetime.now:
                    field.default_factory = lambda: stamp
            model.model_rebuild(force=True)

current = importlib.import_module('src.web.dashboard.service')
# Only the historical module needs this name; production has no compatibility shim.
sys.modules['src.services.mako_context'] = importlib.import_module('src.services.memory.mako_context')
baseline = types.ModuleType('dashboard_r4_baseline')
exec(compile(base_text, '<A-baseline-dashboard>', 'exec'), baseline.__dict__)


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return stamp


baseline.datetime = current.datetime = FixedDatetime
import src.web.dashboard.roadmap.progress as progress_module
progress_module.datetime = FixedDatetime
for module_name in ('catalog', 'defaults', 'evidence'):
    module = importlib.import_module('src.web.dashboard.roadmap.' + module_name)
    module_tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
    for node in module_tree.body:
        if isinstance(node, ast.Assign):
            name = node.targets[0].id
            assert ast.dump(node) == ast.dump(constant_nodes[name]), name
            assert getattr(current, name) is getattr(module, name), name
            assert getattr(current, name) == getattr(baseline, name), name

titles = current.ROADMAP_TASK_TITLES['foundation']
tasks = [models.AutonomyTask(
    task_id=f'stored-{index}', goal_id='foundation', title=titles[index],
    status=status, summary='fixture summary', evidence='stored evidence',
    next_step='fixture next step', priority=42,
) for index, status in enumerate(('todo', 'doing', 'blocked', 'done', 'skipped', 'cancelled'))]
tasks.append(models.AutonomyTask(task_id='custom-1', title='fixture custom', status='done'))
events = [models.AutonomyProgressEvent(
    event_id=f'event-{index}', task_id='foundation-01', summary=summary,
) for index, summary in enumerate(('first event', 'last event'))]
complete_tasks = [models.AutonomyTask(
    task_id=f'{group}-{index:02d}', goal_id=group, title=title, status='done',
) for group, names in current.ROADMAP_TASK_TITLES.items()
    for index, title in enumerate(names, 1)]
empty = {}
populated = {
    'list_bot_profiles': [models.BotProfile(profile_id='fixture', name='Fixture')],
    'list_autonomy_goals': [models.AutonomyGoal(
        goal_id='foundation', title='Fixture goal', progress=25)],
    'list_autonomy_tasks': tasks,
    'list_autonomy_progress_events': events,
    'list_all_notes': [models.NoteRecord(note_id='n1', user_id=1, title='Note', content='Fixture')],
    'list_profiles': [{'user_id': '1', 'profile_text': 'Fixture profile'}],
    'list_all_relationship_memories': [models.RelationshipMemory(
        memory_id='r1', user_id=1, memory_type='preference', content='Fixture preference')],
    'list_thought_traces': [models.ThoughtTrace(
        trace_id='t1', source='autonomy', summary='Fixture legacy trace',
        payload={'action': 'silent', 'target_id': 1, 'token': 'synthetic'})],
    'list_global_records': [models.ChatRecord(role='user', content='Fixture')],
    'list_long_term_memory_points': [{'id': 'l1', 'content': 'Fixture memory'}],
}
storage_methods = (
    'list_bot_profiles', 'list_profiles', 'list_autonomy_goals', 'list_autonomy_tasks',
    'list_autonomy_progress_events', 'list_all_notes', 'list_all_relationship_memories',
    'list_thought_traces', 'list_global_records', 'list_long_term_memory_points',
)


def run(module, fixture, limit):
    storage = Mock(spec=storage_methods)
    for name in storage_methods:
        getattr(storage, name).side_effect = (
            lambda rows=fixture.get(name, []), **kw: rows[:kw.get('limit', len(rows))]
        )
    result = module.DashboardService(storage).get_frontend_summary(limit=limit)
    return result, storage.mock_calls


for label, fixture in (
    ('empty', empty), ('populated', populated),
    ('legacy', {'list_thought_traces': [models.ThoughtTrace(
        trace_id='legacy-' + source, source=source, summary='legacy fixture',
        payload={'action': 'silent', 'target_type': 'group', 'target_id': 7,
                 'token': 'synthetic', 'messages': ['synthetic'],
                 'memories': [{'content_preview': 'fixture'}, 'old item']})
        for source in ('autonomy', 'chat', 'notes', 'relationship', 'unknown')]}),
    ('complete', {'list_autonomy_tasks': complete_tasks}),
):
    for limit in (1, 200):
        expected, expected_calls = run(baseline, fixture, limit)
        actual, actual_calls = run(current, fixture, limit)
        assert actual == expected, (label, limit, 'JSON mismatch')
        assert actual_calls == expected_calls, (label, limit, 'storage calls mismatch')
        data = actual['data']
        if label == 'empty':
            assert len(data['roadmap_groups']) == len(data['goals']) == 10
            assert len(data['roadmap_tasks']) == 100
            counts = Counter(t['status'] for t in data['roadmap_tasks'])
            assert counts == {'done': 53, 'doing': 27, 'blocked': 19, 'todo': 1}, counts
            assert data['progress']['percent'] == 53
        elif label == 'populated':
            assert data['roadmap_tasks'][0]['evidence'] == 'last event'
            assert data['roadmap_tasks'][-1]['id'] == 'custom-1'
        elif label == 'complete':
            assert data['progress']['percent'] == 100
            assert data['progress']['achieved'] is True
        print('PASS', label, 'limit=', limit)

for name, module in list(sys.modules.items()):
    if name == 'src' or name.startswith('src.'):
        filename = getattr(module, '__file__', None)
        if filename:
            assert Path(filename).resolve().is_relative_to(root), (name, filename)
assert 'src.core.config' not in sys.modules
assert 'nonebot' not in sys.modules
for item in (root / 'src/web/dashboard').rglob('*.py'):
    text = item.read_text(encoding='utf-8')
    ast.parse(text, filename=str(item), feature_version=(3, 10))
    compile(text, str(item), 'exec')
print('PASS 10 constants, legacy exports, local imports, Python 3.10 syntax')
print('Runtime:', sys.version.split()[0])
