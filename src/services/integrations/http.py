from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional
from urllib.parse import urljoin

import httpx


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


async def fetch_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    method: str = "GET",
    timeout: float = 20.0,
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method.upper() == "POST":
            resp = await client.post(
                url,
                params=params,
                data=data,
                json=json_data,
                headers=headers,
            )
        else:
            resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def fetch_text(
    url: str,
    timeout: float = 20.0,
    max_bytes: int = 2_000_000,
    max_redirects: int = 5,
    validate_redirect: Optional[Callable[[str], Awaitable[str]]] = None,
) -> str:
    """Fetch text while bounding and optionally validating every redirect hop."""

    if max_redirects < 0:
        raise ValueError("max_redirects cannot be negative")
    current_url = url
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers=_BROWSER_HEADERS,
    ) as client:
        for redirect_count in range(max_redirects + 1):
            async with client.stream("GET", current_url) as resp:
                if resp.status_code in _REDIRECT_STATUS_CODES:
                    location = resp.headers.get("location")
                    if not location:
                        resp.raise_for_status()
                        raise ValueError("redirect response is missing Location header")
                    if redirect_count >= max_redirects:
                        raise httpx.TooManyRedirects(
                            f"response exceeded {max_redirects} redirects",
                            request=resp.request,
                        )
                    next_url = urljoin(str(resp.url), location)
                    if validate_redirect is not None:
                        next_url = await validate_redirect(next_url)
                    current_url = next_url
                    continue

                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").lower()
                allowed_types = ("text/html", "text/plain", "application/xhtml+xml")
                if not any(item in content_type for item in allowed_types):
                    raise ValueError(f"unsupported content type: {content_type or 'missing'}")

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"response exceeds {max_bytes} bytes")
                    chunks.append(chunk)
                encoding = resp.encoding or "utf-8"
                return b"".join(chunks).decode(encoding, errors="replace")

    raise RuntimeError("unreachable redirect state")
