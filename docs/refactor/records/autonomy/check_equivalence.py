"""Compare moved function bodies against A HEAD, undoing dependency qualification."""
import ast
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[4]
baseline = subprocess.check_output(
    ["git", "show", "8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9:src/plugins/autonomy.py"],
    cwd=root,
).decode("utf-8")
original = {node.name: node for node in ast.parse(baseline).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


class Unqualify(ast.NodeTransformer):
    def visit_Attribute(self, node):
        # Only remove explicit dependency paths rooted at self.
        direct = isinstance(node.value, ast.Name) and node.value.id == "self"
        dependency = (isinstance(node.value, ast.Attribute)
                      and isinstance(node.value.value, ast.Name)
                      and node.value.value.id == "self"
                      and node.value.attr in {"repository", "policy", "planner", "executor", "workflow"})
        if direct or dependency:
            name = {"clock": "now_ts", "message_factory": "Message"}.get(node.attr, node.attr)
            return ast.copy_location(ast.Name(id=name, ctx=node.ctx), node)
        return self.generic_visit(node)


checked = []
paths = list((root / "src/services/autonomy").glob("*.py"))
plugin = root / "src/plugins/autonomy.py"
paths += [plugin] if plugin.exists() else list((root / "src/plugins/autonomy").glob("*.py"))
for path in paths:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in original:
            continue
        # Adapter entrypoints are tested via NoneBot, not a body equivalence assertion.
        if node.name in {"autonomy_rule", "handle_autonomy_message", "autonomy_scan", "is_owner"}:
            continue
        body = ast.Module(body=node.body, type_ignores=[])
        expected = ast.Module(body=original[node.name].body, type_ignores=[])
        assert ast.dump(Unqualify().visit(body)) == ast.dump(expected), (path, node.name)
        checked.append(node.name)
print(f"{len(checked)} original bodies equivalent, including literal strings and branches")
