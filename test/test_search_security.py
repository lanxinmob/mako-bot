from __future__ import annotations

import pytest

from src.core.errors import UnsafeUrlError
from src.services import search


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8080/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.10/internal",
        "http://user:secret@example.com/",
    ],
)
async def test_validate_public_url_rejects_server_side_fetch_targets(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        await search.validate_public_url(url)


@pytest.mark.asyncio
async def test_validate_public_url_accepts_public_literal() -> None:
    assert await search.validate_public_url("https://8.8.8.8/status") == "https://8.8.8.8/status"


@pytest.mark.asyncio
async def test_fetch_page_does_not_call_http_for_private_target(monkeypatch) -> None:
    called = False

    async def fake_fetch(_url: str):
        nonlocal called
        called = True
        return "secret"

    monkeypatch.setattr(search, "fetch_text", fake_fetch)
    assert await search.fetch_page_text("http://127.0.0.1/private") == ""
    assert called is False
