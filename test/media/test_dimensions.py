"""Media safety: dimensions."""
from __future__ import annotations
import pytest
from src.core.config import get_settings
from src.core.errors import ImageTooLargeError
from src.services.integrations.image import _process_image_sync
from src.services.integrations.image import _validate_pil_dimensions
from .image_fixtures import _make_pil_image, _make_jpeg_bytes


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
