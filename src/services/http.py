from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


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


async def fetch_text(url: str, timeout: float = 20.0, max_bytes: int = 2_000_000) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", url, follow_redirects=False) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"response exceeds {max_bytes} bytes")
                chunks.append(chunk)
            encoding = resp.encoding or "utf-8"
            return b"".join(chunks).decode(encoding, errors="replace")
