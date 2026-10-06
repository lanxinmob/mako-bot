from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest

from src.services.persistence.effects import EffectConflict, EffectNeedsReview, EffectUnavailable
from src.services.persistence.history_commit.session import HistoryConflict, SessionHistoryWriter
from src.services.persistence.history_commit.snapshot import HistorySnapshots
from test.autonomy.test_pending_atomic import isolated_redis


def apply(writer, effect_id, snapshot, text):
    return writer.apply(effect_id, snapshot, [{"role": "assistant", "content": text}],
                        max_history_turns=2)


def test_missing_then_new_session_and_late_retry_do_not_overwrite_newer(isolated_redis):
    client = isolated_redis
    writer = SessionHistoryWriter(client)
    first = HistorySnapshots(client).read("group_7")
    assert apply(writer, "a" * 64, first, "first") == "applied"
    second = HistorySnapshots(client).read("group_7")
    assert apply(writer, "b" * 64, second, "second") == "applied"
    before = client.get("chat:history:group_7")
    assert apply(writer, "a" * 64, first, "first") == "already_applied"
    assert client.get("chat:history:group_7") == before
    assert client.ttl(writer.receipt_key("a" * 64)) == -1
    with pytest.raises(EffectConflict):
        apply(writer, "a" * 64, first, "changed payload")


def test_concurrent_old_baselines_only_one_wins_and_conflict_is_terminal(isolated_redis):
    client = isolated_redis
    writer = SessionHistoryWriter(client)
    baseline = HistorySnapshots(client).read("private_7")

    def attempt(number):
        try:
            return apply(writer, str(number) * 64, baseline, str(number))
        except HistoryConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert sorted(results) == ["applied", "conflict"]
    loser = results.index("conflict") + 1
    winner_raw = client.get("chat:history:private_7")
    with pytest.raises(HistoryConflict):
        apply(writer, str(loser) * 64, baseline, str(loser))
    assert client.get("chat:history:private_7") == winner_raw
    # An external restoration of the baseline cannot revive a rejected effect.
    client.delete("chat:history:private_7")
    with pytest.raises(HistoryConflict):
        apply(writer, str(loser) * 64, baseline, str(loser))
    assert not client.exists("chat:history:private_7")


@pytest.mark.parametrize("change", ["modern", "legacy", "legacy_created"])
def test_legacy_or_missing_baseline_detects_concurrent_writes(isolated_redis, change):
    client = isolated_redis
    if change != "legacy_created":
        client.set("group_7", ' [ {"role":"user", "content":"old"} ] ')
    baseline = HistorySnapshots(client).read("group_7")
    changed_key = "chat:history:group_7" if change == "modern" else "group_7"
    client.set(changed_key, '[{"role":"user","content":"newer"}]')
    before = {key: client.dump(key) for key in ("group_7", "chat:history:group_7")}
    with pytest.raises(HistoryConflict):
        apply(SessionHistoryWriter(client), "c" * 64, baseline, "old response")
    assert {key: client.dump(key) for key in before} == before


def test_legacy_commit_keeps_source_and_clips_only_new_canonical_history(isolated_redis):
    client = isolated_redis
    raw = ' [ {"role":"user", "content":"old"} ] '
    client.set("group_7", raw)
    snapshot = HistorySnapshots(client).read("group_7")
    messages = [{"role": "user", "content": str(i), "extra": True} for i in range(7)]
    writer = SessionHistoryWriter(client)
    assert writer.apply("d" * 64, snapshot, messages, max_history_turns=2) == "applied"
    assert client.get("group_7") == raw
    assert json.loads(client.get("chat:history:group_7")) == messages[-4:]


def test_response_loss_after_commit_receipt_prevents_replacement_on_retry(isolated_redis):
    client = isolated_redis
    snapshot = HistorySnapshots(client).read("group_7")

    def lost(*args):
        client.eval(*args)
        raise ConnectionError("synthetic history response loss")

    with pytest.raises(EffectUnavailable):
        apply(SessionHistoryWriter(SimpleNamespace(eval=lost)), "e" * 64, snapshot, "once")
    client.set("chat:history:group_7", '[{"content":"newer"}]')
    assert apply(SessionHistoryWriter(client), "e" * 64, snapshot, "once") == "already_applied"
    assert json.loads(client.get("chat:history:group_7")) == [{"content": "newer"}]


def test_bad_receipt_and_unavailable_never_change_session(isolated_redis):
    client = isolated_redis
    snapshot = HistorySnapshots(client).read("private_7")
    writer = SessionHistoryWriter(client)
    receipt = writer.receipt_key("f" * 64)
    client.hset(receipt, "evidence", "keep")
    with pytest.raises(EffectNeedsReview):
        apply(writer, "f" * 64, snapshot, "discard")
    assert not client.exists("chat:history:private_7")
    with pytest.raises(EffectUnavailable):
        apply(SessionHistoryWriter(None), "f" * 64, snapshot, "discard")
