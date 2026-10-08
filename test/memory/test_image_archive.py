"""Archive expiry, scope, and multimodal attribution with synthetic images."""
import asyncio
import base64
import os
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.models.schemas import ChatRecord
from src.services.memory.image_archive import MemoryImageArchive, memory_model_content
from src.services.persistence.effects import EffectWriter
from test.media.image_fixtures import _make_png_bytes


@pytest.mark.asyncio
async def test_saved_image_survives_restart_and_expired_source(tmp_path):
    content = _make_png_bytes(2, 2)
    download = AsyncMock(return_value=(content, "image/jpeg"))
    url = "https://example.com/a.png?signed=private"
    archive = MemoryImageArchive(tmp_path, download=download)
    archive.enqueue([url])
    await asyncio.gather(*archive._pending.values())
    restored = MemoryImageArchive(tmp_path, download=AsyncMock(side_effect=OSError("expired")))
    data = await restored.load(url)
    assert data.startswith("data:image/png;base64,")
    assert base64.b64decode(data.split(",", 1)[1]) == content
    restored.download.assert_not_awaited()
    assert all("private" not in path.name for path in tmp_path.iterdir())


@pytest.mark.asyncio
async def test_background_capture_is_bounded_and_can_shutdown(tmp_path):
    entered = asyncio.Event()
    async def download(_url):
        entered.set()
        await asyncio.Event().wait()
    archive = MemoryImageArchive(tmp_path, capacity=1, download=download)
    archive.enqueue(["https://example.com/a", "https://example.com/b"])
    assert len(archive._pending) == 1
    await entered.wait()
    await archive.close()
    assert not archive._pending


@pytest.mark.asyncio
async def test_model_content_attribution_and_missing_images_never_expose_source_urls():
    archive = Mock(load=AsyncMock(side_effect=["data:image/png;base64,fixture", None]))
    record = ChatRecord(role="user", user_id=7, group_id=123, content="分享图片",
                        time=datetime(2026, 10, 8, 12),
                        image_urls=["https://example.com/private-a", "https://example.com/private-b"])
    parts = await memory_model_content("summarize", [record], archive, vision_enabled=True)
    assert [part["type"] for part in parts].count("image_url") == 1
    assert "群 123，发送者 7" in str(parts)
    assert "不得推测" in str(parts)
    assert "private-a" not in str(parts) and "private-b" not in str(parts)
    archive.load.reset_mock()
    parts = await memory_model_content("summarize", [record], archive, vision_enabled=False)
    archive.load.assert_not_awaited()
    assert not any(part["type"] == "image_url" for part in parts)


def test_prune_preserves_referenced_recent_and_unowned_files(tmp_path):
    archive = MemoryImageArchive(tmp_path)
    retained, expired, recent = ["https://example.com/" + name for name in ("keep", "old", "new")]
    for url in (retained, expired, recent):
        archive._save(url, _make_png_bytes(2, 2))
    for url in (retained, expired):
        os.utime(archive._path(url), (1, 1))
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("unrelated")
    archive.prune([retained])
    assert archive._path(retained).exists()
    assert not archive._path(expired).exists()
    assert archive._path(recent).exists() and unrelated.exists()


def test_prune_aborts_before_deleting_when_reference_scan_fails(tmp_path):
    archive = MemoryImageArchive(tmp_path)
    url = "https://example.com/keep"
    archive._save(url, _make_png_bytes(2, 2))
    os.utime(archive._path(url), (1, 1))
    def uncertain():
        yield "https://example.com/other"
        raise RuntimeError("Redis unavailable")
    with pytest.raises(RuntimeError):
        archive.prune(uncertain())
    assert archive._path(url).exists()


def test_legacy_history_effect_payload_omits_empty_new_field():
    record = ChatRecord(role="assistant", content="fixture", time=datetime(2026, 10, 8))
    writer = EffectWriter(None)
    writer._apply = Mock(return_value="applied")
    writer.append_global_record("a" * 64, record, max_records=1000)
    raw = writer._apply.call_args.args[-1]["record"]
    assert raw == record.model_dump_json(exclude={"image_urls"})
    assert "image_urls" not in raw
