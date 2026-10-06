"""Public metadata only: fixed endpoints, bounded reads, pacing and caching."""
import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import json
import re
import time
from urllib.parse import urlsplit

import httpx


class LookupUnavailable(RuntimeError):
    """The source did not provide a confirmed usable result."""


def valid_endpoint(url: str) -> bool:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.username or parts.password
            or parts.port not in (None, 443) or parts.query or parts.fragment):
        return False
    paths = {
        "api.inaturalist.org": r"/v1/taxa",
        "api.crossref.org": r"/(?:journals(?:/\d{4}-\d{3}[\dX](?:/works)?)?|works)",
        "en.wikipedia.org": r"/w/api\.php",
        "zh.wikipedia.org": r"/w/api\.php",
    }
    return bool(parts.hostname in paths and re.fullmatch(paths[parts.hostname], parts.path))


class PublicAPI:
    def __init__(self, *, transport=None, timeout=10.0, spacing=1.1, clock=time.monotonic):
        self.transport, self.timeout, self.spacing, self.clock = transport, timeout, spacing, clock
        self.cache = OrderedDict()
        self._locks, self._last, self._daily = {}, {}, {}
        self._slots = asyncio.Semaphore(3)
        self._waiting = 0

    async def get(self, url: str, params: dict[str, str | int] | None = None) -> tuple[dict, str]:
        try:
            allowed = valid_endpoint(url)
        except (TypeError, ValueError):
            allowed = False
        if not allowed:
            raise ValueError("unsupported public metadata endpoint")
        params = params or {}
        key = (url, tuple(sorted(params.items())))
        cached = self.cache.get(key)
        if cached is not None and cached[0] > self.clock():
            self.cache.move_to_end(key)
            if cached[1] is None:
                raise LookupUnavailable("来源暂不可用，请稍后再试")
            return cached[1]
        if self._waiting >= 24:
            raise LookupUnavailable("检索请求较多，请稍后再试")
        self._waiting += 1
        try:
            result = await asyncio.wait_for(self._retrieve(url, params, key), self.timeout)
        except (asyncio.TimeoutError, httpx.HTTPError, ValueError, OSError) as exc:
            self._remember(key, None, 20)
            raise LookupUnavailable("来源暂时没有返回可核对资料，请稍后再试") from exc
        finally:
            self._waiting -= 1
        self._remember(key, result, 3600)
        return result

    def _remember(self, key, result, ttl):
        self.cache[key] = (self.clock() + ttl, result)
        self.cache.move_to_end(key)
        while len(self.cache) > 32:
            self.cache.popitem(last=False)

    async def _retrieve(self, url, params, key):
        host = urlsplit(url).hostname
        async with self._slots:
            async with self._locks.setdefault(host, asyncio.Lock()):
                cached = self.cache.get(key)
                if cached is not None and cached[0] > self.clock():
                    if cached[1] is None:
                        raise LookupUnavailable("来源暂不可用，请稍后再试")
                    return cached[1]
                delay = self.spacing - (self.clock() - self._last.get(host, float("-inf")))
                if delay > 0:
                    await asyncio.sleep(delay)
                day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
                previous, count = self._daily.get(host, (day, 0))
                count = count if previous == day else 0
                if count >= 8000:
                    raise LookupUnavailable("今天的公开检索次数较多，请明天再试")
                self._daily[host] = (day, count + 1)
                self._last[host] = self.clock()
                async with httpx.AsyncClient(
                    transport=self.transport, timeout=self.timeout,
                    follow_redirects=False, trust_env=False,
                    headers={"User-Agent": "MakoDiscoveries/1.0 (https://github.com/lanxinmob/mako-bot)",
                             "Accept": "application/json"},
                ) as client:
                    async with client.stream("GET", url, params=params) as response:
                        response.raise_for_status()
                        if "json" not in response.headers.get("content-type", ""):
                            raise ValueError("expected metadata JSON")
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 524288:
                                raise ValueError("metadata exceeds 512 KiB")
                            chunks.append(chunk)
                        data = json.loads(b"".join(chunks))
                        if not isinstance(data, dict):
                            raise ValueError("expected a metadata object")
                        result = (data, day)
                        # Publish before releasing the host lock to coalesce identical requests.
                        self._remember(key, result, 3600)
                        return result
