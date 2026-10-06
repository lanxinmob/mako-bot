"""Only connection/timeout failures qualify for an identical-payload retry."""
from types import SimpleNamespace

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.models.schemas import ChatRecord
from src.services.persistence.effects import EffectNeedsReview, EffectUnavailable, EffectWriter
from test.autonomy.test_pending_atomic import isolated_redis


@pytest.mark.parametrize("failure", [RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError])
def test_connection_failures_remain_distinct_from_review(failure):
    def fail(*args):
        raise failure("synthetic unavailable")

    with pytest.raises(EffectUnavailable):
        EffectWriter(SimpleNamespace(eval=fail)).append_global_record(
            "a" * 64, ChatRecord(role="assistant", content="synthetic"), max_records=1000)
    assert not issubclass(EffectNeedsReview, EffectUnavailable)


def test_server_error_after_partial_script_write_requires_review(isolated_redis):
    # Real Redis deliberately writes then errors. Lua atomic execution does not
    # roll back this write, so absence of the receipt cannot authorize replay.
    def partial_script(*args):
        return isolated_redis.eval(
            "redis.call('RPUSH', KEYS[1], 'synthetic'); return redis.error_reply('synthetic error')",
            1, "all_memory")

    with pytest.raises(EffectNeedsReview) as caught:
        EffectWriter(SimpleNamespace(eval=partial_script)).append_global_record(
            "b" * 64, ChatRecord(role="assistant", content="synthetic"), max_records=1000)
    assert isinstance(caught.value.__cause__, ResponseError)
    assert isolated_redis.lrange("all_memory", 0, -1) == ["synthetic"]
    assert not isolated_redis.exists("mako:delivery:v1:effect:" + "b" * 64)


@pytest.mark.parametrize("response", [None, "unexpected", []])
def test_unrecognized_response_requires_review(response):
    with pytest.raises(EffectNeedsReview):
        EffectWriter(SimpleNamespace(eval=lambda *args: response)).append_global_record(
            "c" * 64, ChatRecord(role="assistant", content="synthetic"), max_records=1000)
