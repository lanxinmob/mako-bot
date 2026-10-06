"""Media safety: edge cases."""
from __future__ import annotations
import pytest
from PIL import Image
from src.core.config import get_settings
from src.core.errors import ImageTooLargeError
from src.services.integrations.image import _process_image_sync
from src.services.integrations.image import _validate_pil_dimensions
from .image_fixtures import _make_pil_image, _make_jpeg_bytes, _make_png_bytes


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
        from src.services.integrations.image import _detect_mime

        assert _detect_mime(_make_png_bytes()) == "image/png"

    def test_detect_mime_jpeg(self):
        from src.services.integrations.image import _detect_mime

        assert _detect_mime(_make_jpeg_bytes()) == "image/jpeg"

    def test_detect_mime_unknown(self):
        from src.services.integrations.image import _detect_mime

        assert _detect_mime(b"\x00\x01\x02invalid") == "application/octet-stream"

    def test_pil_size_header_zero_is_valid(self):
        img = Image.new("RGB", (0, 0))
        assert img.size == (0, 0)

    def test_settings_cached(self):
        """get_settings() should be cached (lru_cache)."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
