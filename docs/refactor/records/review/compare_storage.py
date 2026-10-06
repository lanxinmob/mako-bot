"""Read-only AST comparison against HEAD; no application imports."""
import ast
import copy
import difflib
from pathlib import Path
import subprocess


def parse(text):
    return ast.parse(text)


old = parse(subprocess.check_output(
    ['git', 'show', 'HEAD:src/services/storage.py'], encoding='utf-8'))
old_class = next(n for n in old.body if isinstance(n, ast.ClassDef) and n.name == 'StorageService')
current = {}
for path in Path('src/services/persistence').rglob('*.py'):
    if path.name == 'facade.py':
        continue
    tree = parse(path.read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name not in {'__init__', 'redis', 'settings'}:
            current[node.name] = (path, node)


class Normalize(ast.NodeTransformer):
    def visit_Attribute(self, node):
        text = ast.unparse(node)
        if text == 'self.backend.memory':
            return ast.Name(id='_memory', ctx=node.ctx)
        if text.startswith('normalization.'):
            return ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()),
                                 attr='_' + node.attr, ctx=node.ctx)
        return self.generic_visit(node)


same = 0
for node in old_class.body:
    if not isinstance(node, ast.FunctionDef) or node.name in {'__init__', 'redis'}:
        continue
    candidate = current.get(node.name) or current.get(node.name.lstrip('_'))
    if candidate is None:
        print('MISSING', node.name)
        continue
    path, new_node = candidate
    candidate_node = Normalize().visit(copy.deepcopy(new_node))
    candidate_node.name = node.name
    candidate_node.decorator_list = node.decorator_list
    a, b = ast.unparse(node), ast.unparse(candidate_node)
    if a == b:
        same += 1
    else:
        print(path, node.name)
        print('\n'.join(difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm='')))
print('Equivalent method ASTs after explicit memory/normalization remapping:', same)
