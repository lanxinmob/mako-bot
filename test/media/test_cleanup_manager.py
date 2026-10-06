"""Real owned files with bounded retries and synthetic failure injection."""
import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.services.tools import media
from src.services.tools.media_cleanup import MediaCleanupManager
from src.services.tools.temporary_files import TemporaryFiles


def create(tracker):
    with media._media_file(b"owned", ".png", tracker._track_temp_file, tracker) as path:
        return path


@pytest.mark.asyncio
async def test_active_file_survives_maintenance_and_cleanup_is_idempotent():
    manager = MediaCleanupManager()
    tracker = TemporaryFiles(manager=manager)
    path = create(tracker)
    manager.retry_due()
    manager.maintain()
    assert path.read_bytes() == b"owned"
    tracker.cleanup_temp_files()
    tracker.cleanup_temp_files()
    assert not path.exists() and not manager.resources and not tracker._temp_files
    await manager.shutdown()


@pytest.mark.asyncio
async def test_capacity_rejection_happens_before_file_creation(monkeypatch):
    manager = MediaCleanupManager(capacity=1)
    first, second = TemporaryFiles(manager=manager), TemporaryFiles(manager=manager)
    path = create(first)
    factory = Mock(side_effect=AssertionError("must reserve before allocation"))
    with monkeypatch.context() as scoped:
        scoped.setattr(media.tempfile, "NamedTemporaryFile", factory)
        with pytest.raises(RuntimeError, match="容量不足"):
            create(second)
    factory.assert_not_called()
    first.cleanup_temp_files()
    assert not path.exists() and not manager.resources
    await manager.shutdown()


@pytest.mark.asyncio
async def test_failed_allocation_releases_reservation(monkeypatch):
    manager = MediaCleanupManager(capacity=1)
    tracker = TemporaryFiles(manager=manager)
    monkeypatch.setattr(media.tempfile, "NamedTemporaryFile", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        create(tracker)
    assert not manager.resources
    await manager.shutdown()


@pytest.mark.asyncio
async def test_replaced_path_is_not_deleted(tmp_path):
    manager = MediaCleanupManager()
    tracker = TemporaryFiles(manager=manager)
    path = create(tracker)
    # Keeping the original inode alive prevents filesystem inode reuse in this test.
    moved = tmp_path / "original.png"
    path.replace(moved)
    path.write_bytes(b"replacement")
    try:
        tracker.cleanup_temp_files()
        assert path.read_bytes() == b"replacement"
        assert not manager.resources
    finally:
        path.unlink(missing_ok=True)
        moved.unlink(missing_ok=True)
        await manager.shutdown()


@pytest.mark.asyncio
async def test_exhausted_retries_keep_ownership_until_explicit_maintenance(monkeypatch):
    manager = MediaCleanupManager(delays=(0, 0, 0))
    tracker = TemporaryFiles(manager=manager)
    path = create(tracker)
    with monkeypatch.context() as scoped:
        unlink = Mock(side_effect=PermissionError("locked"))
        scoped.setattr(Path, "unlink", unlink)
        tracker.cleanup_temp_files()
        worker = manager._worker
        tracker.cleanup_temp_files()
        assert manager._worker is worker
        await asyncio.wait_for(worker, 1)
        assert unlink.call_count == 4  # Initial cleanup plus exactly three retries.
        assert len(manager.resources) == 1 and path.exists()
        resource = next(iter(manager.resources))
        assert resource.attempts == 3 and resource.due is None
    manager.maintain()
    assert not manager.resources and not path.exists()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_cancelled_write_and_failed_close_are_retained_then_recovered(monkeypatch, tmp_path):
    manager = MediaCleanupManager(delays=(0, 0, 0))
    tracker = TemporaryFiles(manager=manager)
    factory = tempfile.NamedTemporaryFile
    primary = asyncio.CancelledError("original")
    locked = [True]
    handles = []

    class FaultFile:
        def __init__(self, **kwargs):
            self.file = factory(dir=tmp_path, **kwargs)
            self.name = self.file.name
            handles.append(self)

        def fileno(self):
            return self.file.fileno()

        @property
        def closed(self):
            return self.file.closed

        def write(self, payload):
            self.file.write(payload)
            raise primary

        def close(self):
            if locked[0]:
                raise OSError("close failed")
            self.file.close()

    monkeypatch.setattr(media.tempfile, "NamedTemporaryFile", FaultFile)
    try:
        with pytest.raises(asyncio.CancelledError) as caught:
            create(tracker)
        assert caught.value is primary
        tracker.cleanup_temp_files()
        assert next(iter(manager.resources)).handle is handles[0]
        locked[0] = False
        await asyncio.wait_for(manager._worker, 1)
        assert handles[0].closed and not manager.resources and not list(tmp_path.iterdir())
    finally:
        locked[0] = False
        for handle in handles:
            handle.close()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_retry_wait_and_preserves_active_sender(monkeypatch):
    manager = MediaCleanupManager(delays=(30, 30, 30))
    finished, active = TemporaryFiles(manager=manager), TemporaryFiles(manager=manager)
    old, current = create(finished), create(active)
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", Mock(side_effect=PermissionError("locked")))
        finished.cleanup_temp_files()
    await asyncio.wait_for(manager.shutdown(), 1)
    assert manager._worker.done() and not old.exists()
    assert current.read_bytes() == b"owned"
    with pytest.raises(RuntimeError, match="正在关闭"):
        create(TemporaryFiles(manager=manager))
    active.cleanup_temp_files()
    assert not manager.resources and not current.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows open handle denies unlink")
async def test_actual_windows_file_lock_recovers_after_sender_releases():
    manager = MediaCleanupManager(delays=(.01, .01, .01))
    tracker = TemporaryFiles(manager=manager)
    path = create(tracker)
    try:
        with path.open("rb") as blocker:
            assert blocker.read() == b"owned"
            tracker.cleanup_temp_files()
            assert path.exists() and manager.resources
        await asyncio.wait_for(manager._worker, 1)
        assert not path.exists() and not manager.resources
    finally:
        await manager.shutdown()
