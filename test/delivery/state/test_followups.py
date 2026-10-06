import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.models.schemas import RelationshipMemory
from src.services.delivery.followups import FollowupDelivery
from src.services.persistence.followups import FollowupSource, revision_key
from src.services.persistence.relationships import RelationshipsRepository
from test.autonomy.test_pending_atomic import isolated_redis


def setup(client):
    repository = RelationshipsRepository(SimpleNamespace(redis=client))
    memory = repository.add_relationship_memory(7, "promise", "fixture", due_at=datetime.now() - timedelta(seconds=1))
    dedup = Mock(check=Mock(return_value=SimpleNamespace(allowed=True)))

    async def schedule(_kind, _user, callback, **_kwargs):
        return await callback()

    service = FollowupDelivery(client, dedup, schedule=schedule)
    bot = SimpleNamespace(self_id="99", send_private_msg=AsyncMock(return_value={"message_id": 1}))
    return repository, memory, service, bot


@pytest.mark.asyncio
async def test_confirmed_followup_records_once_and_removes_only_matching_due_version(isolated_redis):
    repository, memory, service, bot = setup(isolated_redis)
    assert await service.deliver(bot, 7, memory.memory_id)
    assert not await service.deliver(bot, 7, memory.memory_id)
    assert repository.get_relationship_memory(7, memory.memory_id).status == "done"
    assert isolated_redis.zscore("relationship:followups", f"7:{memory.memory_id}") is None
    bot.send_private_msg.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_transport_is_never_repeated_on_next_scan(isolated_redis):
    repository, memory, service, bot = setup(isolated_redis)
    bot.send_private_msg.side_effect = TimeoutError("ack lost")
    with pytest.raises(TimeoutError):
        await service.deliver(bot, 7, memory.memory_id)
    assert not await service.deliver(bot, 7, memory.memory_id)
    assert repository.get_relationship_memory(7, memory.memory_id).status == "active"
    bot.send_private_msg.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_ack_is_unknown_not_completed_or_resent(isolated_redis):
    repository, memory, service, bot = setup(isolated_redis)
    bot.send_private_msg.return_value = {}
    assert not await service.deliver(bot, 7, memory.memory_id)
    assert not await service.deliver(bot, 7, memory.memory_id)
    assert repository.get_relationship_memory(7, memory.memory_id).status == "active"
    bot.send_private_msg.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["update", "delete", "done"])
async def test_queued_source_change_prevents_actual_transport(isolated_redis, mutation):
    repository, memory, service, bot = setup(isolated_redis)

    async def schedule(_kind, _user, callback, **_kwargs):
        if mutation == "update":
            repository.update_relationship_memory(7, memory.memory_id, "new version")
        elif mutation == "delete":
            repository.delete_relationship_memory(7, memory.memory_id)
        else:
            repository.mark_relationship_done(7, memory.memory_id)
        return await callback()

    service.schedule = schedule
    assert not await service.deliver(bot, 7, memory.memory_id)
    bot.send_private_msg.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_ack_cannot_complete_new_content(isolated_redis):
    repository, memory, service, bot = setup(isolated_redis)
    old_revision = isolated_redis.hget(revision_key(7), memory.memory_id)

    async def send(**_kwargs):
        repository.update_relationship_memory(7, memory.memory_id, "corrected version")
        return {"message_id": 1}

    bot.send_private_msg.side_effect = send
    assert await service.deliver(bot, 7, memory.memory_id)
    current = repository.get_relationship_memory(7, memory.memory_id)
    assert current.content == "corrected version" and current.status == "active"
    assert isolated_redis.hget(revision_key(7), memory.memory_id) != old_revision
    assert isolated_redis.zscore("relationship:followups", f"7:{memory.memory_id}") is not None


def test_legacy_is_quarantined_without_changing_business_record(isolated_redis):
    memory = RelationshipMemory(memory_id="legacy", user_id=7, memory_type="promise", content="old",
                                due_at=datetime.now() - timedelta(days=1))
    raw = memory.model_dump_json()
    isolated_redis.hset("relationship:7", "legacy", raw)
    isolated_redis.zadd("relationship:followups", {"7:legacy": memory.due_at.timestamp()})
    assert FollowupSource(isolated_redis).load(7, "legacy") is None
    assert isolated_redis.hget("relationship:7", "legacy") == raw
    assert isolated_redis.zscore("relationship:followups", "7:legacy") is None
    assert isolated_redis.zscore("mako:delivery:v1:legacy:followups", "7:legacy") is not None


def test_wrong_index_type_cannot_partially_create_source(isolated_redis):
    isolated_redis.set("relationship:followups", "wrong type")
    with pytest.raises(Exception, match="invalid followup key type"):
        setup(isolated_redis)
    assert not isolated_redis.exists("relationship:7")
    assert not isolated_redis.exists(revision_key(7))


def test_complete_repairs_index_after_legacy_done_partial_failure(isolated_redis):
    repository, memory, _, _ = setup(isolated_redis)
    source = FollowupSource(isolated_redis)
    snapshot = source.load(7, memory.memory_id)
    proxy = Mock(wraps=isolated_redis)
    proxy.zrem.side_effect = ConnectionError("after done write")
    legacy = RelationshipsRepository(SimpleNamespace(redis=proxy))
    with pytest.raises(ConnectionError):
        legacy.mark_relationship_done(7, memory.memory_id)
    key = f"7:{memory.memory_id}"
    assert isolated_redis.zscore("relationship:followups", key) is not None
    raw_done = isolated_redis.hget("relationship:7", memory.memory_id)
    assert source.complete(snapshot)
    assert isolated_redis.zscore("relationship:followups", key) is None
    assert source.complete(snapshot)
    assert isolated_redis.hget("relationship:7", memory.memory_id) == raw_done


@pytest.mark.asyncio
async def test_redis_outage_cannot_use_in_memory_delivery():
    client = Mock(eval=Mock(side_effect=ConnectionError("offline")))
    service = FollowupDelivery(client, Mock())
    bot = SimpleNamespace(self_id="99", send_private_msg=AsyncMock())
    with pytest.raises(ConnectionError):
        await service.deliver(bot, 7, "fixture")
    bot.send_private_msg.assert_not_awaited()
    with pytest.raises(RuntimeError, match="requires Redis"):
        FollowupDelivery(None, Mock())
