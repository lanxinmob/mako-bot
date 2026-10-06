from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.models.schemas import ChatRecord, OutboundMessageRecord
from src.services.persistence.effects import EffectConflict, EffectNeedsReview, EffectUnavailable, EffectWriter
from test.autonomy.test_pending_atomic import isolated_redis


@pytest.mark.parametrize("kind", ["history", "outbound", "cost", "news"])
def test_lost_response_then_same_effect_retry_does_not_repeat_target_write(isolated_redis, kind):
    client = isolated_redis
    timestamp = datetime(2026, 9, 26, 12)
    effect_id = "a" * 64
    record = ChatRecord(role="assistant", content="synthetic", time=timestamp)
    outbound = OutboundMessageRecord(message_id=effect_id, target_type="group", target_id=1,
                                     content="synthetic", created_at=timestamp)

    def apply(writer):
        if kind == "history":
            return writer.append_global_record(effect_id, record, max_records=1000)
        if kind == "outbound":
            return writer.record_outbound(effect_id, outbound, max_records=20, ttl=86400)
        if kind == "cost":
            return writer.consume_cost(effect_id, 7, 0.25, at=timestamp)
        return writer.record_news(effect_id, ["fingerprint"], sent_at=timestamp)

    def lost_response(*args):
        client.eval(*args)
        raise ConnectionError("response lost after mutation")

    with pytest.raises(EffectUnavailable):
        apply(EffectWriter(SimpleNamespace(eval=lost_response)))
    assert apply(EffectWriter(client)) == "already_applied"
    if kind == "history":
        assert client.llen("all_memory") == 1
    elif kind == "outbound":
        assert client.llen("outbound:ledger:group:1") == 1
    elif kind == "cost":
        assert float(client.get("cost:global:20260926")) == 0.25
        assert float(client.get("cost:user:7:20260926")) == 0.25
    else:
        assert float(client.hget("news:sent", "fingerprint")) == timestamp.timestamp()
    assert client.ttl(f"mako:delivery:v1:effect:{effect_id}") == -1


def test_competing_same_cost_effect_applies_once_and_conflicting_content_is_rejected(isolated_redis):
    writer = EffectWriter(isolated_redis)
    timestamp = datetime(2026, 9, 26)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: writer.consume_cost("b" * 64, 7, 0.5, at=timestamp), range(2)))
    assert sorted(results) == ["already_applied", "applied"]
    with pytest.raises(EffectConflict):
        writer.consume_cost("b" * 64, 7, 1.0, at=timestamp)
    assert float(isolated_redis.get("cost:global:20260926")) == 0.5


@pytest.mark.parametrize("bad_value", ["not-a-number", "1e999"])
def test_bad_second_cost_counter_cannot_increment_first(isolated_redis, bad_value):
    client = isolated_redis
    client.set("cost:global:20260926", "1")
    client.set("cost:user:7:20260926", bad_value)
    with pytest.raises(EffectNeedsReview):
        EffectWriter(client).consume_cost("c" * 64, 7, 0.25, at=datetime(2026, 9, 26))
    assert client.get("cost:global:20260926") == "1"
    assert client.get("cost:user:7:20260926") == bad_value
    assert not client.exists("mako:delivery:v1:effect:" + "c" * 64)


def test_old_news_effect_never_moves_a_newer_timestamp_backwards(isolated_redis):
    writer = EffectWriter(isolated_redis)
    timestamp = datetime(2026, 9, 26)
    writer.record_news("d" * 64, ["fp"], sent_at=timestamp)
    writer.record_news("e" * 64, ["fp"], sent_at=timestamp - timedelta(days=1))
    assert float(isolated_redis.hget("news:sent", "fp")) == timestamp.timestamp()


def test_wrong_list_type_and_invalid_retention_never_write_receipt(isolated_redis):
    client = isolated_redis
    writer = EffectWriter(client)
    record = ChatRecord(role="assistant", content="synthetic")
    client.set("all_memory", "wrong type")
    with pytest.raises(EffectNeedsReview):
        writer.append_global_record("f" * 64, record, max_records=1000)
    with pytest.raises(ValueError):
        writer.append_global_record("f" * 64, record, max_records=2**80)
    assert client.get("all_memory") == "wrong type"
    assert not client.exists("mako:delivery:v1:effect:" + "f" * 64)
