"""Actual sender boundaries leave durable tasks for independent discovery."""
import asyncio
import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.effects.discovery import EffectScanner
from src.services.delivery.effects.worker import EffectWorker
from src.services.delivery.state import DeliveryUnavailable
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.state.test_followups import setup as followup_setup
from test.delivery.state.test_periodic import setup as periodic_setup
from test.delivery.state.test_reminder_delivery import setup as reminder_setup


def sender(client, kind):
    if kind == "followup":
        _, memory, service, bot = followup_setup(client)
        return service, bot.send_private_msg, "followups", lambda: service.deliver(bot, 7, memory.memory_id)
    if kind == "periodic":
        service, bot, kwargs = periodic_setup(client)
        return service, bot.send_group_msg, "periodic", lambda: service.deliver(bot, 1, "synthetic", **kwargs)
    _, snapshot, bot, service = reminder_setup(client)
    return service, bot.send_group_msg, "reminder_delivery", lambda: service.deliver(
        bot, "fixture", snapshot.revision, valid_until_ms=2**52)


def action_key(client):
    keys = [key for key in client.scan_iter("mako:delivery:v1:*")
            if re.fullmatch(r"mako:delivery:v1:[0-9a-f]{64}", key)]
    assert len(keys) == 1
    return keys[0]


async def recover_effects(client, key):
    # No sender instance/bot/settings supplied; discovery only has storage.
    scan = SimpleNamespace(scan=Mock(return_value=(0, [key])))
    return await EffectScanner(scan, worker=EffectWorker(client)).run_page()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["followup", "periodic", "reminder"])
async def test_cancel_after_durable_ack_is_finished_by_discovery_without_resend(isolated_redis, monkeypatch, kind):
    client = isolated_redis
    _, transport, module, deliver = sender(client, kind)
    monkeypatch.setattr("src.services.delivery." + module + ".settle_confirmed",
                        AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await deliver()
    key = action_key(client)
    before = json.loads(client.get(key))
    assert before["state"] == "sent" and before["effects_version"] == 1
    assert all(task["state"] == "pending" for task in before["effects"])
    page = await recover_effects(client, key)
    assert page.outcomes and all(code == "applied" for _, code in page.outcomes)
    assert json.loads(client.get(key))["effects_state"] == "complete"
    assert not await deliver()
    transport.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["followup", "periodic", "reminder"])
@pytest.mark.parametrize("committed", [False, True])
async def test_uncertain_sent_persistence_never_bypasses_tasks_or_retries_send(isolated_redis, monkeypatch, kind, committed):
    client = isolated_redis
    service, transport, _, deliver = sender(client, kind)
    original = service.store.mark_sent

    def lose_sent(*args):
        if committed:
            original(*args)
        raise DeliveryUnavailable("synthetic sent persistence unknown")

    monkeypatch.setattr(service.store, "mark_sent", lose_sent)
    assert await deliver()
    key = action_key(client)
    before = json.loads(client.get(key))
    assert before["state"] == ("sent" if committed else "sending")
    assert all(task["state"] == ("pending" if committed else "not_started") for task in before["effects"])
    assert not client.exists("all_memory")
    page = await recover_effects(client, key)
    after = json.loads(client.get(key))
    if committed:
        assert page.outcomes and after["effects_state"] == "complete"
    else:
        assert page.outcomes == () and after == before
    assert not await deliver()
    transport.assert_awaited_once()


@pytest.mark.asyncio
async def test_periodic_observation_failure_preserves_ack_and_durable_effects(isolated_redis, monkeypatch):
    client = isolated_redis
    _, transport, _, deliver = sender(client, "periodic")
    monkeypatch.setattr("src.services.delivery.periodic.observe_group_output", Mock(side_effect=RuntimeError))
    assert await deliver()
    assert json.loads(client.get(action_key(client)))["effects_state"] == "complete"
    assert client.llen("all_memory") == 1
    transport.assert_awaited_once()
