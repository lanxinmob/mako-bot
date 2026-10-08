"""Media safety: download."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from src.core.errors import AppError, ImageTooLargeError
from src.services.integrations.image import download_image_data
from .image_fixtures import _make_jpeg_bytes, _make_png_bytes


class TestDownloadImageData:
    """Mock httpx to exercise the download size-guard logic."""

    @pytest.fixture(autouse=True)
    def _allow_mock_public_url(self, monkeypatch):
        validator = AsyncMock(side_effect=lambda url: url)
        monkeypatch.setattr("src.services.integrations.image.validate_public_url", validator)

    @pytest.mark.asyncio
    async def test_normal_download_returns_bytes_and_mime(self):
        fake_body = _make_jpeg_bytes(10, 10)

        with patch("src.services.integrations.image.httpx.AsyncClient") as mock_client_cls:
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
            mock_client.stream.return_value.__aenter__.return_value = get_mock

            content, mime = await download_image_data("http://example.com/img.jpg")
            assert content == fake_body
            assert mime == "image/jpeg"
            mock_client.head.assert_awaited_once()
            mock_client.stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_head_content_length_exceeds_limit_raises(self):
        with patch("src.services.integrations.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {"content-length": "999999999"}
            mock_client.head = AsyncMock(return_value=head_mock)

            with pytest.raises(ImageTooLargeError, match="Content-Length"):
                await download_image_data("http://example.com/big.jpg", max_size=1024)

            mock_client.stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_chunk_exceeds_limit_raises(self):
        with patch("src.services.integrations.image.httpx.AsyncClient") as mock_client_cls:
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
            mock_client.stream.return_value.__aenter__.return_value = get_mock

            with pytest.raises(ImageTooLargeError, match="downloaded .* exceeds"):
                await download_image_data("http://example.com/img.png", max_size=1024)

    @pytest.mark.asyncio
    async def test_none_max_size_uses_config_default(self):
        fake_body = _make_jpeg_bytes(10, 10)

        with patch("src.services.integrations.image.httpx.AsyncClient") as mock_client_cls:
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
            mock_client.stream.return_value.__aenter__.return_value = get_mock

            content, mime = await download_image_data("http://example.com/img.jpg")
            assert content == fake_body

    @pytest.mark.asyncio
    async def test_head_no_content_length_still_downloads(self):
        fake_body = _make_jpeg_bytes(10, 10)

        with patch("src.services.integrations.image.httpx.AsyncClient") as mock_client_cls:
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
            mock_client.stream.return_value.__aenter__.return_value = get_mock

            content, mime = await download_image_data("http://example.com/img.jpg")
            assert content == fake_body

    @pytest.mark.asyncio
    async def test_mime_falls_back_to_magic_detection(self):
        fake_body = _make_png_bytes(10, 10)

        with patch("src.services.integrations.image.httpx.AsyncClient") as mock_client_cls:
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
            mock_client.stream.return_value.__aenter__.return_value = get_mock

            content, mime = await download_image_data("http://example.com/img.bin")
            assert mime == "image/png"

    @pytest.mark.asyncio
    async def test_explicit_max_size_overrides_default(self):
        fake_body = _make_jpeg_bytes(5, 5)

        with patch("src.services.integrations.image.httpx.AsyncClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            head_mock = MagicMock()
            head_mock.headers = {"content-length": str(len(fake_body))}
            mock_client.head = AsyncMock(return_value=head_mock)

            with pytest.raises(ImageTooLargeError, match="Content-Length"):
                await download_image_data("http://example.com/img.jpg", max_size=1)


@pytest.mark.asyncio
async def test_image_download_rejects_private_network_targets() -> None:
    with patch("src.services.integrations.image.httpx.AsyncClient") as client:
        with pytest.raises(AppError, match="非公网"):
            await download_image_data("http://127.0.0.1/internal.png")
        client.assert_not_called()
