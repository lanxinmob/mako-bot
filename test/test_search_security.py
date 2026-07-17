from __future__ import annotations

import httpx
import pytest

from src.core.errors import UnsafeUrlError
from src.services import search
from src.services import http as http_service


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


@pytest.mark.asyncio
async def test_fetch_text_follows_public_redirect_with_browser_headers(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url) == "http://example.com/start":
            return httpx.Response(302, headers={"Location": "https://www.example.com/final"})
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=b"<html>redirected</html>",
        )

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        http_service.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )
    validated: list[str] = []

    async def validate_redirect(url: str) -> str:
        validated.append(url)
        return url

    result = await http_service.fetch_text(
        "http://example.com/start",
        validate_redirect=validate_redirect,
    )

    assert result == "<html>redirected</html>"
    assert validated == ["https://www.example.com/final"]
    assert len(requests) == 2
    assert requests[0].headers["user-agent"].startswith("Mozilla/5.0")
    assert requests[0].headers["accept-language"].startswith("zh-CN")


@pytest.mark.asyncio
async def test_fetch_text_revalidates_redirect_before_following(monkeypatch) -> None:
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        http_service.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(transport=transport, **kwargs),
    )

    async def reject_private_redirect(_url: str) -> str:
        raise UnsafeUrlError("private redirect")

    with pytest.raises(UnsafeUrlError, match="private redirect"):
        await http_service.fetch_text(
            "https://example.com/start",
            validate_redirect=reject_private_redirect,
        )

    assert request_count == 1
