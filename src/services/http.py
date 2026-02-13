from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


async def fetch_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    method: str = "GET",
    timeout: float = 20.0,
) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method.upper() == "POST":
            resp = await client.post(url, params=params, data=data, headers=headers)
        else:
            resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def fetch_text(url: str, timeout: float = 20.0) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text
