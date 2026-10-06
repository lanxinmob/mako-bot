import asyncio

import httpx
import pytest

from src.features.discoveries.network import LookupUnavailable, PublicAPI


@pytest.mark.asyncio
async def test_fixed_endpoints_cache_and_request_identity():
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    api = PublicAPI(transport=httpx.MockTransport(respond), spacing=0)
    endpoint = "https://api.inaturalist.org/v1/taxa"
    await asyncio.gather(*(api.get(endpoint, {"q": "麻雀"}) for _ in range(3)))
    assert len(seen) == 1
    assert seen[0].url.params["q"] == "麻雀"
    assert "MakoDiscoveries" in seen[0].headers["User-Agent"]
    await api.get(endpoint, {"q": "robin"})
    assert len(seen) == 2
    with pytest.raises(ValueError):
        await api.get("https://api.inaturalist.org@127.0.0.1/private")
    assert len(seen) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["redirect", "too_large", "malformed", "rate_limit"])
async def test_unusable_source_is_not_cached_as_success(kind):
    calls = []

    def respond(request):
        calls.append(request)
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        if kind == "too_large":
            return httpx.Response(200, content=b" " * 524289,
                                  headers={"Content-Type": "application/json"})
        if kind == "rate_limit":
            return httpx.Response(429)
        return httpx.Response(200, json=[])

    api = PublicAPI(transport=httpx.MockTransport(respond), spacing=0)
    for _ in range(2):
        with pytest.raises(LookupUnavailable):
            await api.get("https://api.crossref.org/journals", {"query": "Nature"})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_timeout_cleans_pending_requests_without_retry():
    calls = []

    async def stalled(request):
        calls.append(request)
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    api = PublicAPI(transport=httpx.MockTransport(stalled), spacing=0, timeout=0.01)
    with pytest.raises(LookupUnavailable):
        await api.get("https://api.crossref.org/journals", {"query": "Nature"})
    assert api._waiting == 0
    with pytest.raises(LookupUnavailable):
        await api.get("https://api.crossref.org/journals", {"query": "Nature"})
    assert len(calls) == 1
