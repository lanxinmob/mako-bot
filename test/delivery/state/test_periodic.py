import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.periodic import PeriodicDelivery, period_deadline
from src.services.delivery.state import DeliveryUnavailable
from test.autonomy.test_pending_atomic import isolated_redis


def setup(client):
    seconds, micros = client.time()
    now = datetime.fromtimestamp(seconds + micros / 1e6, timezone.utc)
    storage = Mock()
    dedup = Mock(check=Mock(return_value=SimpleNamespace(allowed=True)))

    async def schedule(_kind, _target, callback, **_kwargs):
        return await callback()

    service = PeriodicDelivery(client, storage, dedup, schedule=schedule, now=lambda _: now)
    bot = SimpleNamespace(self_id="99", send_group_msg=AsyncMock(return_value={"message_id": 1}))
    return service, bot, dict(task="scheduler.digest", period=now.date(), timezone=timezone.utc,
                              intent="digest", fingerprints=["old-article"])


@pytest.mark.asyncio
async def test_same_period_random_body_cannot_authorize_second_send(isolated_redis):
    service, bot, kwargs = setup(isolated_redis)
    assert await service.deliver(bot, 1, "first", **kwargs)
    assert not await service.deliver(bot, 1, "different", **kwargs)
    bot.send_group_msg.assert_awaited_once()
    assert set(isolated_redis.hkeys("news:sent")) == {"old-article"}
    assert isolated_redis.llen("all_memory") == 1
    service.storage.record_sent_news.assert_not_called()


@pytest.mark.asyncio
async def test_unsent_period_recovery_uses_frozen_body_and_fingerprints(isolated_redis):
    service, bot, kwargs = setup(isolated_redis)
    schedule = service.schedule
    service.schedule = AsyncMock(return_value=False)
    assert not await service.deliver(bot, 1, "frozen", **kwargs)
    service.schedule = schedule
    kwargs["fingerprints"] = ["new-article"]
    assert await service.deliver(bot, 1, "newly fetched", **kwargs)
    message = bot.send_group_msg.call_args.kwargs["message"]
    assert message.extract_plain_text() == "frozen"
    assert set(isolated_redis.hkeys("news:sent")) == {"old-article"}
    assert json.loads(isolated_redis.lindex("all_memory", 0))["content"] == "frozen"
    service.storage.record_sent_news.assert_not_called()
    service.storage.append_global_record.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_period_and_redis_outage_never_retry_transport(isolated_redis):
    service, bot, kwargs = setup(isolated_redis)
    bot.send_group_msg.side_effect = TimeoutError("ack lost")
    with pytest.raises(TimeoutError):
        await service.deliver(bot, 1, "body", **kwargs)
    assert not await service.deliver(bot, 1, "changed", **kwargs)
    service.store.redis = None
    with pytest.raises(DeliveryUnavailable):
        await service.deliver(bot, 2, "body", **kwargs)
    bot.send_group_msg.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_day_fetch_and_expiry_while_queued_do_not_send(isolated_redis):
    service, bot, kwargs = setup(isolated_redis)
    kwargs["period"] -= timedelta(days=1)
    assert not await service.deliver(bot, 1, "late result", **kwargs)
    assert not list(isolated_redis.scan_iter("mako:delivery:v1:*"))
    kwargs["period"] += timedelta(days=1)

    async def expire(_kind, _target, callback, **_kwargs):
        keys = list(isolated_redis.scan_iter("mako:delivery:v1:*"))
        assert len(keys) == 1
        record = json.loads(isolated_redis.get(keys[0]))
        record["valid_until_ms"] = 0
        isolated_redis.set(keys[0], json.dumps(record))
        return await callback()

    service.schedule = expire
    assert not await service.deliver(bot, 1, "expires while queued", **kwargs)
    bot.send_group_msg.assert_not_awaited()


@pytest.mark.asyncio
async def test_period_identity_separates_tasks_targets_and_bots(isolated_redis):
    service, bot, kwargs = setup(isolated_redis)
    assert await service.deliver(bot, 1, "digest", **kwargs)
    assert await service.deliver(bot, 2, "digest", **kwargs)
    kwargs["task"] = "scheduler.morning"
    assert await service.deliver(bot, 1, "morning", **kwargs)
    bot.self_id = "100"
    assert await service.deliver(bot, 1, "morning", **kwargs)
    assert bot.send_group_msg.await_count == 4


@pytest.mark.asyncio
async def test_fingerprint_failure_keeps_sent_and_does_not_skip_history(isolated_redis):
    service, bot, kwargs = setup(isolated_redis)
    isolated_redis.set("news:sent", "invalid target type")
    assert await service.deliver(bot, 1, "body", **kwargs)
    assert not await service.deliver(bot, 1, "new body", **kwargs)
    assert isolated_redis.llen("all_memory") == 1
    assert isolated_redis.llen("outbound:ledger:group:1") == 1
    assert isolated_redis.get("news:sent") == "invalid target type"
    service.storage.append_global_record.assert_not_called()
    service.dedup.record.assert_not_called()
    bot.send_group_msg.assert_awaited_once()


def test_period_deadline_uses_scheduler_timezone_midnight():
    tz = timezone(timedelta(hours=8))
    today = datetime(2026, 9, 24, tzinfo=tz).date()
    assert period_deadline(today, tz) == int(datetime(2026, 9, 25, tzinfo=tz).timestamp() * 1000)
