"""Event-loop-owned cleanup; no directory scans or durable retry claims."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(eq=False)
class MediaResource:
    path: Path | None = None
    handle: Any = None
    identity: tuple[int, int] | None = None
    released: bool = False
    attempts: int = 0
    due: float | None = None


class MediaCleanupManager:
    def __init__(self, *, capacity=128, delays=(1.0, 5.0, 30.0), clock=time.monotonic):
        self.capacity, self.delays, self.clock = capacity, delays, clock
        self.resources: set[MediaResource] = set()
        self._worker: asyncio.Task | None = None
        self._wake: asyncio.Event | None = None
        self._closing = False

    def reserve(self) -> MediaResource:
        # Count active files too: every accepted allocation has a recovery slot
        # even if all senders encounter filesystem errors simultaneously.
        if self._closing or len(self.resources) >= self.capacity:
            raise RuntimeError("本地媒体回收容量不足或正在关闭，未创建新文件")
        resource = MediaResource()
        self.resources.add(resource)
        return resource

    def discard_uncreated(self, resource):
        if resource.path is None and resource.handle is None:
            self.resources.discard(resource)

    def bind(self, resource, path, handle):
        resource.path, resource.handle = path, handle
        stat = os.fstat(handle.fileno())
        resource.identity = (stat.st_dev, stat.st_ino)

    def try_cleanup(self, resource) -> bool:
        """Only caller-owned failed construction or released resources enter here."""
        if resource not in self.resources:
            return True
        try:
            if resource.handle is not None and not resource.handle.closed:
                resource.handle.close()
            if resource.path is not None:
                try:
                    stat = resource.path.lstat()
                except FileNotFoundError:
                    pass
                else:
                    if resource.identity is None:
                        return False  # Unknown ownership never authorizes deletion.
                    if (stat.st_dev, stat.st_ino) == resource.identity:
                        resource.path.unlink()
                    else:
                        logger.warning("Media path identity changed; replacement left untouched")
        except OSError:
            return False
        self.resources.discard(resource)
        resource.handle = None
        return True

    def release(self, resource):
        if resource not in self.resources or resource.released:
            return
        resource.released = True
        if self.try_cleanup(resource):
            return
        resource.due = self.clock() + self.delays[0] if self.delays else None
        self._start_worker()

    def _start_worker(self):
        if self._closing:
            logger.warning("Media cleanup deferred during shutdown; ownership retained")
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("Media cleanup deferred without event loop; ownership retained")
            return
        if self._worker is None or self._worker.done():
            self._wake = asyncio.Event()
            self._worker = loop.create_task(self._run(), name="mako-media-cleanup")
        else:
            self._wake.set()

    def retry_due(self):
        now = self.clock()
        for resource in tuple(self.resources):
            if not resource.released or resource.due is None or resource.due > now:
                continue
            resource.attempts += 1
            if self.try_cleanup(resource):
                continue
            if resource.attempts >= len(self.delays):
                resource.due = None
                logger.warning("Media cleanup retries exhausted; bounded ownership retained")
            else:
                resource.due = self.clock() + self.delays[resource.attempts]

    async def _run(self):
        try:
            while not self._closing:
                self.retry_due()
                pending = [item.due for item in self.resources if item.released and item.due is not None]
                if not pending:
                    return
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), max(0, min(pending) - self.clock()))
                except asyncio.TimeoutError:
                    pass
        except Exception:
            # A worker failure must be observable, and cannot drop ownership.
            logger.exception("Media cleanup worker stopped; resources retained for maintenance")

    def maintain(self):
        """Explicit bounded pass; never touch files still owned by an active sender."""
        for resource in tuple(self.resources):
            if resource.released:
                self.try_cleanup(resource)

    async def shutdown(self):
        self._closing = True
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        self.maintain()
        if self.resources:
            logger.warning("Media shutdown retained %s active/unresolved resources", len(self.resources))


cleanup_manager = MediaCleanupManager()
