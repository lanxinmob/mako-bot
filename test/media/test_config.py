"""Media safety: config."""
from __future__ import annotations
import pytest
from src.core.config import Settings
from src.core.errors import AppError, ImageTooLargeError


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
