"""Load owner adapters under a test package without registering plugin jobs."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType


def load_owner():
    path = Path(__file__).resolve().parents[2] / "src/plugins/autonomy"
    package_name = "_mako_owner_test_adapter"
    if package_name not in sys.modules:
        package = ModuleType(package_name)
        package.__path__ = [str(path)]
        sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(f"{package_name}.owner", path / "owner.py")
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    return owner
