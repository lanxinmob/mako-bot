"""Isolated contracts: never import application settings or real service clients here."""
from pathlib import Path
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("script", ["service_contract.py", "routes_contract.py"])
def test_dashboard_contract_in_isolated_process(script):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-B", str(Path(__file__).with_name(script))],
        cwd=root,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
