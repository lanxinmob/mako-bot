"""Files stay alive until the sender explicitly requests cleanup."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from .media_cleanup import cleanup_manager


class TemporaryFiles:
    def __init__(self, *, manager=None) -> None:
        self._temp_files: List[Path] = []
        self.manager = manager if manager is not None else cleanup_manager
        self._resources = {}

    def reserve(self):
        return self.manager.reserve()

    def bind(self, resource, path, handle):
        self._resources[path] = resource
        self.manager.bind(resource, path, handle)

    def _track_temp_file(self, path: Path) -> None:
        self._temp_files.append(path)

    def cleanup_temp_files(self) -> None:
        """Remove all tracked temporary files. Call after messages are sent."""
        remaining = []
        # Resource handles also survive failures before the legacy path callback.
        managed_paths = set(self._resources)
        for path, resource in tuple(self._resources.items()):
            self.manager.release(resource)
            del self._resources[path]
        for path in self._temp_files:
            if path in managed_paths:
                continue  # Manager now owns failures and checks identity on retry.
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError:
                remaining.append(path)
        # Keep the list identity shared with ToolExecutor, and retry failures.
        self._temp_files[:] = remaining
