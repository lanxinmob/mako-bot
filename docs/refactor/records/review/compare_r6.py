"""Independent R6 comparison, only known dependency qualifiers normalized."""
import ast
import copy
import difflib
from pathlib import Path
import subprocess

baseline = ast.parse(subprocess.check_output(['git', 'show', 'HEAD:src/services/chat_context.py'], encoding='utf-8'))
files = [*Path('src/services/retrieval').glob('*.py'), Path('src/services/chat/context.py')]
current = {}
for path in files:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for method in node.body:
                if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    current[node.name + '.' + method.name] = method


class RestoreDependency(ast.NodeTransformer):
    def visit_Attribute(self, node):
        if ast.unparse(node.value) in {'self._deps', 'dependencies'}:
            return ast.Name(id=node.attr, ctx=node.ctx)
        return self.generic_visit(node)


count = 0
for item in baseline.body:
    methods = [(item.name, item)] if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
    if isinstance(item, ast.ClassDef):
        methods = [(item.name + '.' + n.name, n) for n in item.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name != '__init__']
    for name, original in methods:
        replacement = current.get(name) or current.get(original.name)
        if name == 'SearchContextBuilder._finalize':
            replacement = current['finalize']
        assert replacement is not None, name
        replaced = RestoreDependency().visit(copy.deepcopy(replacement))
        a = '\n'.join(ast.unparse(n) for n in original.body)
        b = '\n'.join(ast.unparse(n) for n in replaced.body)
        if a != b:
            print('DIFF', name)
            print('\n'.join(difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm='')))
        else:
            count += 1
print('Equivalent bodies with only dependency qualifiers restored:', count)
for path in files:
    source = path.read_text(encoding='utf-8')
    ast.parse(source, feature_version=(3, 10))
print('PASS Python 3.10 grammar for', len(files), 'R6 files')
