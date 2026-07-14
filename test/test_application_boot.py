from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_complete_application_imports_in_a_fresh_process() -> None:
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        {
            "AUTONOMY_ENABLED": "false",
            "PROACTIVE_ENABLED": "false",
            "REDIS_REQUIRED": "false",
            "LLM_REQUIRED": "false",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", "import bot; print('BOOT_OK')"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "BOOT_OK" in completed.stdout
