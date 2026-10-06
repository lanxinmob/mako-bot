from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable
from src.services.persistence.history_commit.snapshot import HistorySnapshots
from test.autonomy.test_pending_atomic import isolated_redis


def test_exact_sources_are_read_only_and_views_do_not_mutate_evidence(isolated_redis):
    client = isolated_redis
    snapshots = HistorySnapshots(client)
    missing = snapshots.read("group_7")
    assert missing.source == "missing" and missing.raw is None and missing.messages() == []
    raw = b'[ {"role": "user", "content": "old", "extra": {"keep": true}} ]'
    client.set("group_7", raw)
    legacy = snapshots.read("group_7")
    assert legacy.source == "legacy" and legacy.raw == raw
    legacy.messages()[0]["extra"]["keep"] = False
    assert legacy.messages()[0]["extra"]["keep"] is True
    assert not client.exists("chat:history:group_7")
    client.set("chat:history:group_7", b"[]")
    before = {key: client.dump(key) for key in client.scan_iter()}
    current = snapshots.read("group_7")
    assert current.source == "current" and current.messages() == []
    assert {key: client.dump(key) for key in client.scan_iter()} == before


@pytest.mark.parametrize("raw", [b"", b"broken", b"{}", b"[1]", b"\xff"])
def test_corrupt_current_never_falls_back_to_legacy_or_empty(isolated_redis, raw):
    client = isolated_redis
    client.set("private_7", "[]")
    client.set("chat:history:private_7", raw)
    before = client.dump("chat:history:private_7")
    with pytest.raises(EffectNeedsReview):
        HistorySnapshots(client).read("private_7")
    assert client.dump("chat:history:private_7") == before


def test_wrong_type_and_unavailable_are_not_missing_history(isolated_redis):
    isolated_redis.hset("private_7", "evidence", "keep")
    with pytest.raises(EffectNeedsReview):
        HistorySnapshots(isolated_redis).read("private_7")
    for client in (None, SimpleNamespace(execute_command=Mock(side_effect=ConnectionError))):
        with pytest.raises(EffectUnavailable):
            HistorySnapshots(client).read("private_7")
