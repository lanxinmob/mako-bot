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


@pytest.mark.asyncio
async def test_ollama_fetch_page_posts_authenticated_json(monkeypatch) -> None:
    monkeypatch.setattr(
        search,
        "get_settings",
        lambda: SimpleNamespace(ollama_api_key="test-key"),
    )
    captured = {}

    async def fake_fetch_json(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return {"title": "Example", "content": "  Main page content  ", "links": []}

    monkeypatch.setattr(search, "fetch_json", fake_fetch_json)

    content = await search.ollama_fetch_page("https://example.com/article")

    assert content == "Main page content"
    assert captured == {
        "url": "https://ollama.com/api/web_fetch",
        "json_data": {"url": "https://example.com/article"},
        "headers": {
            "Authorization": "Bearer test-key",
            "Content-Type": "application/json",
        },
        "method": "POST",
        "timeout": 30.0,
    }


@pytest.mark.asyncio
async def test_fetch_page_prefers_ollama_web_fetch(monkeypatch) -> None:
    async def fake_validate(url: str) -> str:
        return url

    async def fake_ollama_fetch(_url: str) -> str:
        return "Ollama extracted content"

    async def unexpected_local_fetch(*_args, **_kwargs) -> str:
        raise AssertionError("local fetch should not run when Ollama succeeds")

    monkeypatch.setattr(search, "validate_public_url", fake_validate)
    monkeypatch.setattr(search, "ollama_fetch_page", fake_ollama_fetch)
    monkeypatch.setattr(search, "fetch_text", unexpected_local_fetch)

    assert await search.fetch_page_text("https://example.com") == "Ollama extracted content"


@pytest.mark.asyncio
async def test_fetch_page_falls_back_to_local_fetch(monkeypatch) -> None:
    async def fake_validate(url: str) -> str:
        return url

    async def failed_ollama_fetch(_url: str) -> str:
        raise RuntimeError("upstream unavailable")

    async def fake_local_fetch(_url: str, **kwargs) -> str:
        assert kwargs["validate_redirect"] is fake_validate
        return "<html><body>Local fallback content</body></html>"

    monkeypatch.setattr(search, "validate_public_url", fake_validate)
    monkeypatch.setattr(search, "ollama_fetch_page", failed_ollama_fetch)
    monkeypatch.setattr(search, "fetch_text", fake_local_fetch)

    assert await search.fetch_page_text("https://example.com") == "Local fallback content"
