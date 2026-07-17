from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.errors import NotConfiguredError
from src.services import search


@pytest.mark.asyncio
async def test_ollama_search_posts_authenticated_json_and_maps_results(monkeypatch) -> None:
    monkeypatch.setattr(
        search,
        "get_settings",
        lambda: SimpleNamespace(ollama_api_key="test-key", ollama_search_result_count=5),
    )
    captured = {}

    async def fake_fetch_json(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return {
            "results": [
                {
                    "title": "Ollama docs",
                    "url": "https://docs.ollama.com/capabilities/web-search",
                    "content": "Official web search documentation",
                }
            ]
        }

    monkeypatch.setattr(search, "fetch_json", fake_fetch_json)

    results = await search.ollama_search("ollama web search", num=3)

    assert captured == {
        "url": "https://ollama.com/api/web_search",
        "json_data": {"query": "ollama web search", "max_results": 3},
        "headers": {
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
        "method": "POST",
        "timeout": 25.0,
    }
    assert results == [
        search.SearchResult(
            title="Ollama docs",
            link="https://docs.ollama.com/capabilities/web-search",
            snippet="Official web search documentation",
            source="ollama",
        )
    ]


@pytest.mark.asyncio
async def test_ollama_search_requires_api_key(monkeypatch) -> None:
    monkeypatch.setattr(
        search,
        "get_settings",
        lambda: SimpleNamespace(ollama_api_key=None, ollama_search_result_count=5),
    )

    with pytest.raises(NotConfiguredError, match="OLLAMA_API_KEY"):
        await search.ollama_search("query")


@pytest.mark.asyncio
async def test_ollama_search_caps_requested_results_at_api_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        search,
        "get_settings",
        lambda: SimpleNamespace(ollama_api_key="test-key", ollama_search_result_count=5),
    )
    captured = {}

    async def fake_fetch_json(_url: str, **kwargs):
        captured.update(kwargs)
        return {"results": []}

    monkeypatch.setattr(search, "fetch_json", fake_fetch_json)

    await search.ollama_search("query", num=99)

    assert captured["json_data"]["max_results"] == 10
