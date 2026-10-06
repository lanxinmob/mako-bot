"""Media safety: temporary files."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.core.config import Settings


class TestTempFileTracking:
    """Exercise real tracking and media output lifetime without external services."""

    @staticmethod
    def _make_minimal_executor():
        from src.services.tools.temporary_files import TemporaryFiles

        return TemporaryFiles()

    def test_track_adds_to_list(self):
        executor = self._make_minimal_executor()
        p = Path("/tmp/fake-test-file-12345.tmp")
        executor._track_temp_file(p)
        assert p in executor._temp_files

    def test_cleanup_removes_files(self, tmp_path):
        executor = self._make_minimal_executor()
        f1 = tmp_path / "a.tmp"
        f2 = tmp_path / "b.tmp"
        f1.write_text("hello")
        f2.write_text("world")
        executor._track_temp_file(f1)
        executor._track_temp_file(f2)
        assert len(executor._temp_files) == 2

        executor.cleanup_temp_files()
        assert not f1.exists()
        assert not f2.exists()
        assert len(executor._temp_files) == 0

    def test_cleanup_missing_file_no_error(self):
        executor = self._make_minimal_executor()
        missing = Path("/tmp/does-not-exist-99999.tmp")
        executor._track_temp_file(missing)
        executor.cleanup_temp_files()
        assert len(executor._temp_files) == 0

    def test_cleanup_multiple_calls_idempotent(self, tmp_path):
        executor = self._make_minimal_executor()
        f = tmp_path / "once.tmp"
        f.write_text("data")
        executor._track_temp_file(f)
        executor.cleanup_temp_files()
        executor.cleanup_temp_files()
        assert not f.exists()

    def test_temp_files_list_initialized_empty(self):
        executor = self._make_minimal_executor()
        assert executor._temp_files == []

    @pytest.mark.asyncio
    async def test_image_process_tracks_temp_file(self):
        await self._assert_media_lifetime("image.process", b"\x89PNGtest", ".png", "image")

    @pytest.mark.asyncio
    async def test_language_tts_tracks_temp_file(self):
        await self._assert_media_lifetime("language.tts", b"audio-test", ".mp3", "record")

    @staticmethod
    async def _assert_media_lifetime(name, payload, suffix, segment_type):
        from src.services.tools.executor import ToolExecutor
        from src.services.governance.service import AccessDecision
        from src.services.tools.intent import IntentDecision

        governance = MagicMock()
        governance.tool_allowed.return_value = AccessDecision(True)
        governance.can_consume_cost.return_value = AccessDecision(True)
        governance.estimate_tool_cost.return_value = 0.02
        executor = ToolExecutor(
            settings_factory=lambda: Settings(_env_file=None),
            governance_factory=lambda: governance,
            note_factory=MagicMock, affinity_factory=MagicMock,
        )
        # Inject adapters on the instance; file lifetime remains sender-owned.
        with (
            patch.object(executor.dependencies, "download_image_bytes", AsyncMock(return_value=b"input")),
            patch.object(executor.dependencies, "process_image", AsyncMock(return_value=payload)),
            patch.object(executor.dependencies, "text_to_speech", AsyncMock(return_value=payload)),
        ):
            try:
                result = await executor.run(
                    [IntentDecision(name=name, args={})], 1, "hello",
                    ["https://example.com/image.png"], [], [], message_type="private",
                )
                assert result.handled
                assert len(result.extra_messages) == 1
                assert result.extra_messages[0].type == segment_type
                path = Path(result.extra_messages[0].data["file"])
                assert path in executor._temp_files
                assert path.suffix == suffix
                assert path.read_bytes() == payload
                governance.consume_cost.assert_called_once_with(1, 0.02)
                # Simulate a failed sender; its finally must still reclaim the file.
                with pytest.raises(RuntimeError, match="send failed"):
                    try:
                        raise RuntimeError("send failed")
                    finally:
                        executor.cleanup_temp_files()
                assert not path.exists()
                assert executor._temp_files == []
            finally:
                executor.cleanup_temp_files()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,payload,segment", [
    ("image.process", b"\x89PNGtest", "image"),
    ("image.process", b"jpeg-test", "image"),
    ("language.tts", b"audio-test", "record"),
])
@pytest.mark.parametrize("fault", ["write", "close", "close_open", "message", "success"])
async def test_media_fault_lifecycle(tmp_path, monkeypatch, name, payload, segment, fault):
    import tempfile
    from src.services.tools import media
    from src.services.tools.dependencies import ToolDependencies
    from src.services.tools.intent import IntentDecision
    from src.services.tools.models import ToolExecutionResult
    from src.services.tools.temporary_files import TemporaryFiles

    tracker = TemporaryFiles()
    result = ToolExecutionResult()
    handles = []
    events = []
    real_factory = tempfile.NamedTemporaryFile
    real_unlink = Path.unlink
    real_segment = getattr(media.MessageSegment, segment)

    class FaultFile:
        def __init__(self, **kwargs):
            self.file = real_factory(dir=tmp_path, **kwargs)
            self.name = self.file.name
            self.close_calls = 0
            handles.append(self)

        @property
        def closed(self):
            return self.file.closed

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def write(self, data):
            assert Path(self.name) in tracker._temp_files
            self.file.write(data[:2])
            self.file.flush()
            events.append("write")
            if fault == "write":
                raise OSError("controlled write")
            return self.file.write(data[2:])

        def close(self):
            self.close_calls += 1
            if fault == "close_open" and self.close_calls == 1:
                raise OSError("controlled close_open")
            self.file.close()
            events.append("closed")
            if fault == "close" and self.close_calls == 1:
                raise OSError("controlled close")

    def checked_unlink(path, *args, **kwargs):
        assert all(handle.closed for handle in handles)
        events.append("unlink")
        return real_unlink(path, *args, **kwargs)

    def make_segment(*, file):
        assert all(handle.closed for handle in handles)
        assert Path(file).read_bytes() == payload
        if fault == "message":
            raise ValueError("controlled message")
        return real_segment(file=file)

    monkeypatch.setattr(media.tempfile, "NamedTemporaryFile", FaultFile)
    monkeypatch.setattr(Path, "unlink", checked_unlink)
    monkeypatch.setattr(media.MessageSegment, segment, make_segment)
    dependencies = ToolDependencies(
        download_image_bytes=AsyncMock(return_value=b"input"),
        process_image=AsyncMock(return_value=payload),
        text_to_speech=AsyncMock(return_value=payload),
    )
    try:
        call = media.handle(
            IntentDecision(name=name, args={}), result, "hello", ["synthetic"], [],
            track_temp_file=tracker._track_temp_file, dependencies=dependencies,
        )
        if fault == "success":
            assert await call
            path = Path(result.extra_messages[0].data["file"])
            assert path.read_bytes() == payload
            assert path in tracker._temp_files
            assert "unlink" not in events
        else:
            with pytest.raises((OSError, ValueError), match=f"controlled {fault}"):
                await call
            assert not result.extra_messages
            assert not result.fact_lines
            assert list(tmp_path.iterdir()) == []
            assert events.index("closed") < events.index("unlink")
        assert handles and all(handle.closed for handle in handles)
        tracker.cleanup_temp_files()
        tracker.cleanup_temp_files()
        assert tracker._temp_files == []
        assert list(tmp_path.iterdir()) == []
    finally:
        for handle in handles:
            handle.file.close()
        tracker.cleanup_temp_files()


def test_cleanup_retries_locked_file_without_losing_shared_list(tmp_path, monkeypatch):
    from src.services.tools import temporary_files

    tracker = temporary_files.TemporaryFiles()
    shared = tracker._temp_files
    path = tmp_path / "locked.tmp"
    path.write_bytes(b"data")
    tracker._track_temp_file(path)
    real_unlink = temporary_files.os.unlink
    with monkeypatch.context() as scoped:
        scoped.setattr(temporary_files.os, "unlink", MagicMock(side_effect=PermissionError("locked")))
        tracker.cleanup_temp_files()
    assert path.exists()
    assert tracker._temp_files is shared
    assert shared == [path]
    assert temporary_files.os.unlink is real_unlink
    tracker.cleanup_temp_files()
    tracker.cleanup_temp_files()
    assert not path.exists()
    assert shared == []


@pytest.mark.parametrize("cancelled", [False, True])
def test_media_preserves_primary_error_when_close_also_fails(tmp_path, monkeypatch, caplog, cancelled):
    import asyncio
    import tempfile
    from src.services.tools import media
    from src.services.tools.temporary_files import TemporaryFiles

    primary = asyncio.CancelledError("original cancellation") if cancelled else ValueError("original write")
    tracker = TemporaryFiles()
    real_factory = tempfile.NamedTemporaryFile
    handles = []

    class FaultFile:
        def __init__(self, **kwargs):
            self.file = real_factory(dir=tmp_path, **kwargs)
            self.name = self.file.name
            handles.append(self.file)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        @property
        def closed(self):
            return self.file.closed

        def write(self, payload):
            self.file.write(payload)
            raise primary

        def close(self):
            raise OSError("secondary close failure")

    monkeypatch.setattr(media.tempfile, "NamedTemporaryFile", FaultFile)
    try:
        with pytest.raises(type(primary)) as caught:
            with media._media_file(b"partial", ".png", tracker._track_temp_file):
                pytest.fail("a failed file must not be delivered")
        assert caught.value is primary
        assert len(tracker._temp_files) == 1
        assert tracker._temp_files[0].exists()
        assert "close failed during error cleanup" in caplog.text
    finally:
        for handle in handles:
            handle.close()
        tracker.cleanup_temp_files()
    assert not tracker._temp_files
    assert not list(tmp_path.iterdir())
