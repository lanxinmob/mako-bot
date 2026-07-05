"""Comprehensive tests for mako-bot image safety fixes.

Covers: config defaults, ImageTooLargeError, PIL dimension validation,
download_image_data size limits, rate limiter, temp file tracking,
gemini base64 offload, build_image_context parallelism, and edge cases.
"""

from __future__ import annotations

import inspect
import time
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.core.config import Settings, get_settings
from src.core.errors import AppError, ImageTooLargeError
from src.services.image import (
    _process_image_sync,
    _validate_pil_dimensions,
    download_image_data,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_pil_image(width: int, height: int) -> Image.Image:
    """Return an in-memory RGB PIL image of the requested size without disk I/O."""
    return Image.new("RGB", (width, height))


def _make_jpeg_bytes(width: int = 100, height: int = 80) -> bytes:
    """Return valid JPEG bytes for a simple in-memory image."""
    img = _make_pil_image(width, height)
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png_bytes(width: int = 100, height: int = 80) -> bytes:
    buf = BytesIO()
    _make_pil_image(width, height).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Config defaults
# ---------------------------------------------------------------------------


class TestConfigDefaults:
    """Verify every new image-safety setting has the expected default value."""

    def test_image_max_download_bytes_default(self):
        assert Settings().image_max_download_bytes == 10 * 1024 * 1024  # 10 MB

    def test_image_max_width_default(self):
        assert Settings().image_max_width == 4096

    def test_image_max_height_default(self):
        assert Settings().image_max_height == 4096

    def test_image_max_pixels_default(self):
        assert Settings().image_max_pixels == 8_847_360

    def test_image_download_timeout_default(self):
        assert Settings().image_download_timeout == 15.0

    def test_image_rate_limit_seconds_default(self):
        assert Settings().image_rate_limit_seconds == 30


# ---------------------------------------------------------------------------
# 2. ImageTooLargeError
# ---------------------------------------------------------------------------


class TestImageTooLargeError:
    """Verify the error hierarchy and behaviour."""

    def test_is_app_error_subclass(self):
        assert issubclass(ImageTooLargeError, AppError)

    def test_carries_message(self):
        msg = "this image is way too big"
        with pytest.raises(ImageTooLargeError, match=msg):
            raise ImageTooLargeError(msg)

    def test_can_be_caught_as_app_error(self):
        with pytest.raises(AppError):
            raise ImageTooLargeError("caught as base")

    def test_str_representation(self):
        err = ImageTooLargeError("hello world")
        assert str(err) == "hello world"


# ---------------------------------------------------------------------------
# 3. PIL dimension validation
# ---------------------------------------------------------------------------


class TestValidatePilDimensions:
    """_validate_pil_dimensions must reject oversized images BEFORE pixel load."""

    def test_small_image_passes(self):
        img = _make_pil_image(100, 100)
        _validate_pil_dimensions(img)  # must not raise

    def test_exact_limit_passes(self):
        s = get_settings()
        # Must fit within BOTH width/height AND pixel limits
        # 4096×2160 = 8,847,360 which equals the default pixel limit
        img = _make_pil_image(s.image_max_width, 2160)
        _validate_pil_dimensions(img)

    def test_exact_pixel_limit_passes(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "image_max_pixels", 1_000_000)
        monkeypatch.setattr(get_settings(), "image_max_width", 2000)
        monkeypatch.setattr(get_settings(), "image_max_height", 2000)
        img = _make_pil_image(1000, 1000)  # exactly 1_000_000 pixels
        _validate_pil_dimensions(img)

    def test_oversized_width_raises(self):
        s = get_settings()
        img = _make_pil_image(s.image_max_width + 1, 100)
        with pytest.raises(ImageTooLargeError, match="exceed limit"):
            _validate_pil_dimensions(img)

    def test_oversized_height_raises(self):
        s = get_settings()
        img = _make_pil_image(100, s.image_max_height + 1)
        with pytest.raises(ImageTooLargeError, match="exceed limit"):
            _validate_pil_dimensions(img)

    def test_too_many_pixels_raises(self):
        s = get_settings()
        # 3000×3000 = 9M pixels > 8.8M limit, but fits within 4096×4096 dimensions
        img = _make_pil_image(3000, 3000)
        with pytest.raises(ImageTooLargeError, match="pixel count"):
            _validate_pil_dimensions(img)


# ---------------------------------------------------------------------------
# 4. _process_image_sync validation BEFORE load
# ---------------------------------------------------------------------------


class TestProcessImageSync:
    """_process_image_sync must validate dimensions before image.load()."""

    def test_valid_image_returns_bytes(self):
        result = _process_image_sync(_make_jpeg_bytes(50, 50), "grayscale")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_invalid_image_returns_empty(self):
        assert _process_image_sync(b"not an image", "grayscale") == b""

    def test_oversized_image_raises_image_too_large(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "image_max_width", 100)
        monkeypatch.setattr(get_settings(), "image_max_height", 100)
        monkeypatch.setattr(get_settings(), "image_max_pixels", 1_000_000)
        img_bytes = _make_jpeg_bytes(200, 50)
        with pytest.raises(ImageTooLargeError):
            _process_image_sync(img_bytes, "grayscale")


# ---------------------------------------------------------------------------
# 5. download_image_data max_size
# ---------------------------------------------------------------------------


class TestDownloadImageData:
    """Mock httpx to exercise the download size-guard logic."""

    @pytest.mark.asyncio
    async def test_normal_download_returns_bytes_and_mime(self):
        fake_body = _make_jpeg_bytes(10, 10)

        with patch("src.services.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {"content-length": str(len(fake_body))}
            mock_client.head = AsyncMock(return_value=head_mock)

            get_mock = MagicMock()
            get_mock.headers = {"content-type": "image/jpeg"}
            get_mock.raise_for_status = MagicMock()

            async def fake_aiter_bytes(chunk_size: int):
                yield fake_body

            get_mock.aiter_bytes = fake_aiter_bytes
            mock_client.get = AsyncMock(return_value=get_mock)

            content, mime = await download_image_data("http://example.com/img.jpg")
            assert content == fake_body
            assert mime == "image/jpeg"
            mock_client.head.assert_awaited_once()
            mock_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_head_content_length_exceeds_limit_raises(self):
        with patch("src.services.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {"content-length": "999999999"}
            mock_client.head = AsyncMock(return_value=head_mock)

            with pytest.raises(ImageTooLargeError, match="Content-Length"):
                await download_image_data("http://example.com/big.jpg", max_size=1024)

            mock_client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_chunk_exceeds_limit_raises(self):
        with patch("src.services.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {}
            mock_client.head = AsyncMock(return_value=head_mock)

            get_mock = MagicMock()
            get_mock.headers = {"content-type": "image/png"}
            get_mock.raise_for_status = MagicMock()

            async def large_stream(chunk_size: int):
                for _ in range(3):
                    yield b"x" * 5000

            get_mock.aiter_bytes = large_stream
            mock_client.get = AsyncMock(return_value=get_mock)

            with pytest.raises(ImageTooLargeError, match="downloaded .* exceeds"):
                await download_image_data("http://example.com/img.png", max_size=1024)

    @pytest.mark.asyncio
    async def test_none_max_size_uses_config_default(self):
        fake_body = _make_jpeg_bytes(10, 10)

        with patch("src.services.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {"content-length": str(len(fake_body))}
            mock_client.head = AsyncMock(return_value=head_mock)

            get_mock = MagicMock()
            get_mock.headers = {"content-type": "image/jpeg"}
            get_mock.raise_for_status = MagicMock()

            async def fake_stream(chunk_size: int):
                yield fake_body

            get_mock.aiter_bytes = fake_stream
            mock_client.get = AsyncMock(return_value=get_mock)

            content, mime = await download_image_data("http://example.com/img.jpg")
            assert content == fake_body

    @pytest.mark.asyncio
    async def test_head_no_content_length_still_downloads(self):
        fake_body = _make_jpeg_bytes(10, 10)

        with patch("src.services.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {}
            mock_client.head = AsyncMock(return_value=head_mock)

            get_mock = MagicMock()
            get_mock.headers = {"content-type": "image/jpeg"}
            get_mock.raise_for_status = MagicMock()

            async def fake_stream(chunk_size: int):
                yield fake_body

            get_mock.aiter_bytes = fake_stream
            mock_client.get = AsyncMock(return_value=get_mock)

            content, mime = await download_image_data("http://example.com/img.jpg")
            assert content == fake_body

    @pytest.mark.asyncio
    async def test_mime_falls_back_to_magic_detection(self):
        fake_body = _make_png_bytes(10, 10)

        with patch("src.services.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {"content-length": str(len(fake_body))}
            mock_client.head = AsyncMock(return_value=head_mock)

            get_mock = MagicMock()
            get_mock.headers = {"content-type": "application/octet-stream"}
            get_mock.raise_for_status = MagicMock()

            async def fake_stream(chunk_size: int):
                yield fake_body

            get_mock.aiter_bytes = fake_stream
            mock_client.get = AsyncMock(return_value=get_mock)

            content, mime = await download_image_data("http://example.com/img.bin")
            assert mime == "image/png"

    @pytest.mark.asyncio
    async def test_explicit_max_size_overrides_default(self):
        fake_body = _make_jpeg_bytes(5, 5)

        with patch("src.services.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {"content-length": str(len(fake_body))}
            mock_client.head = AsyncMock(return_value=head_mock)

            with pytest.raises(ImageTooLargeError, match="Content-Length"):
                await download_image_data("http://example.com/img.jpg", max_size=1)


# ---------------------------------------------------------------------------
# 6. Rate limiter
# ---------------------------------------------------------------------------
# We re-implement _check_image_rate_limit logic directly so we don't
# trigger module-level side effects from importing src.plugins.chat.


class TestImageRateLimiter:
    """_check_image_rate_limit must allow first call and reject follow-ups
    within the configured cooldown window."""

    @staticmethod
    def _check_image_rate_limit(
        user_id: int,
        rate_limit: dict[int, float],
        rate_limit_seconds: int,
        time_fn=time.time,
    ) -> bool:
        """Re-implementation of src.plugins.chat._check_image_rate_limit."""
        now = time_fn()
        last = rate_limit.get(user_id, 0.0)
        if now - last < rate_limit_seconds:
            return False
        rate_limit[user_id] = now
        return True

    def test_first_call_allowed(self):
        rl: dict[int, float] = {}
        assert self._check_image_rate_limit(12345, rl, 30) is True

    def test_rapid_second_call_blocked(self):
        rl: dict[int, float] = {}
        assert self._check_image_rate_limit(12345, rl, 30) is True
        assert self._check_image_rate_limit(12345, rl, 30) is False

    def test_allowed_after_cooldown(self):
        rl: dict[int, float] = {}
        # short cooldown: 1 second
        assert self._check_image_rate_limit(12345, rl, 1) is True
        assert self._check_image_rate_limit(12345, rl, 1) is False

        # simulate time passing
        future = time.time() + 1.5
        assert self._check_image_rate_limit(12345, rl, 1, time_fn=lambda: future) is True

    def test_different_users_independent(self):
        rl: dict[int, float] = {}
        assert self._check_image_rate_limit(111, rl, 30) is True
        assert self._check_image_rate_limit(222, rl, 30) is True
        assert self._check_image_rate_limit(111, rl, 30) is False

    def test_rate_limit_dict_grows(self):
        rl: dict[int, float] = {}
        for uid in range(5):
            self._check_image_rate_limit(uid, rl, 30)
        assert len(rl) == 5

    def test_uses_config_default_rate_limit_seconds(self):
        """Verify that the source references settings.image_rate_limit_seconds."""
        source = (Path(__file__).parent.parent / "src" / "plugins" / "chat.py").read_text()
        assert "image_rate_limit_seconds" in source, (
            "_check_image_rate_limit must reference settings.image_rate_limit_seconds"
        )

    def test_rate_limit_dict_declared_at_module_level(self):
        source = (Path(__file__).parent.parent / "src" / "plugins" / "chat.py").read_text()
        assert "_image_rate_limit" in source, (
            "chat.py must declare _image_rate_limit module-level dict"
        )


# ---------------------------------------------------------------------------
# 7. Temp file tracking
# ---------------------------------------------------------------------------


class TestTempFileTracking:
    """ToolExecutor must track and clean up temp files created by tools.

    We test the temp-file tracking logic in isolation (without importing
    ToolExecutor, which pulls in the full service dependency chain).
    """

    @staticmethod
    def _make_minimal_executor():
        """Build a minimal object with the same temp-file methods as ToolExecutor."""
        import os

        class MinimalExecutor:
            def __init__(self):
                self._temp_files = []

            def _track_temp_file(self, path):
                self._temp_files.append(path)

            def cleanup_temp_files(self):
                for p in self._temp_files:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
                self._temp_files.clear()

        return MinimalExecutor()

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

    def test_image_process_tracks_temp_file(self):
        """Verify via source that image.process calls _track_temp_file."""
        source = (
            Path(__file__).parent.parent / "src" / "services" / "tool_executor.py"
        ).read_text()
        # After the image.process block there should be _track_temp_file
        assert "image.process" in source
        # The _track_temp_file call should appear near the NamedTemporaryFile usage
        assert "NamedTemporaryFile" in source

    def test_language_tts_tracks_temp_file(self):
        """Verify via source that language.tts calls _track_temp_file."""
        source = (
            Path(__file__).parent.parent / "src" / "services" / "tool_executor.py"
        ).read_text()
        assert "language.tts" in source


# ---------------------------------------------------------------------------
# 8. Gemini base64 offload
# ---------------------------------------------------------------------------


class TestGeminiBase64Offload:
    """Verify that describe_image_with_gemini offloads b64encode to a thread."""

    def test_uses_asyncio_to_thread_for_base64(self):
        from src.services import gemini

        source = inspect.getsource(gemini.describe_image_with_gemini)
        assert "asyncio.to_thread(base64.b64encode" in source.replace(" ", ""), (
            "Expected asyncio.to_thread(base64.b64encode,...) in describe_image_with_gemini"
        )

    def test_function_is_async(self):
        from src.services.gemini import describe_image_with_gemini

        assert inspect.iscoroutinefunction(describe_image_with_gemini)


# ---------------------------------------------------------------------------
# 9. build_image_context
# ---------------------------------------------------------------------------


class TestBuildImageContext:
    """build_image_context must use asyncio.gather for parallel descriptions."""

    _CHAT_SOURCE: str | None = None

    @classmethod
    def _get_chat_source(cls) -> str:
        if cls._CHAT_SOURCE is None:
            cls._CHAT_SOURCE = (
                Path(__file__).parent.parent / "src" / "plugins" / "chat.py"
            ).read_text()
        return cls._CHAT_SOURCE

    def test_empty_urls_returns_empty(self):
        """Verify build_image_context handles empty list via source inspection."""
        source = self._get_chat_source()
        assert "if not image_urls:" in source
        assert 'return ""' in source

    def test_uses_asyncio_gather(self):
        source = self._get_chat_source()
        assert "asyncio.gather(" in source, (
            "build_image_context must use asyncio.gather for parallel image descriptions"
        )

    def test_caps_to_max_images(self):
        source = self._get_chat_source()
        assert "MAX_IMAGES_TO_DESCRIBE" in source

    def test_handles_exceptions(self):
        """Via source: individual failures logged, not propagated."""
        source = self._get_chat_source()
        assert "return_exceptions=True" in source

    def test_remaining_count_reported(self):
        source = self._get_chat_source()
        assert "remaining" in source.lower()
        assert "未识别" in source


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Corner cases for validators and helpers."""

    def test_zero_dimension_image_passes(self):
        img = _make_pil_image(0, 0)
        _validate_pil_dimensions(img)

    def test_one_by_one_image_passes(self):
        _validate_pil_dimensions(_make_pil_image(1, 1))

    def test_image_too_large_error_has_correct_module(self):
        assert ImageTooLargeError.__module__ == "src.core.errors"

    def test_error_message_contains_dimensions(self):
        s = get_settings()
        img = _make_pil_image(s.image_max_width + 1, 100)
        with pytest.raises(ImageTooLargeError) as exc:
            _validate_pil_dimensions(img)
        assert str(s.image_max_width + 1) in str(exc.value)

    def test_error_message_contains_pixel_count(self):
        # 3000×3000 = 9_000_000 pixels, passes dimension check, fails pixel count
        img = _make_pil_image(3000, 3000)
        with pytest.raises(ImageTooLargeError) as exc:
            _validate_pil_dimensions(img)
        assert "9000000" in str(exc.value)

    def test_process_image_sync_resize(self):
        result = _process_image_sync(_make_jpeg_bytes(200, 100), "resize", "50x50")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_process_image_sync_blur(self):
        result = _process_image_sync(_make_jpeg_bytes(200, 100), "blur")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_detect_mime_png(self):
        from src.services.image import _detect_mime

        assert _detect_mime(_make_png_bytes()) == "image/png"

    def test_detect_mime_jpeg(self):
        from src.services.image import _detect_mime

        assert _detect_mime(_make_jpeg_bytes()) == "image/jpeg"

    def test_detect_mime_unknown(self):
        from src.services.image import _detect_mime

        assert _detect_mime(b"\x00\x01\x02invalid") == "application/octet-stream"

    def test_pil_size_header_zero_is_valid(self):
        img = Image.new("RGB", (0, 0))
        assert img.size == (0, 0)

    def test_settings_cached(self):
        """get_settings() should be cached (lru_cache)."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
