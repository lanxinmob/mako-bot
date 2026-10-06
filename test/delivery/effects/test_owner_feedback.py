"""Owner task details are read-only and never hide confirmed delivery."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery.effects.worker import EffectWorker
from src.services.delivery.state import DeliveryStore
from test.autonomy.owner_loader import load_owner
from test.autonomy.test_pending_atomic import isolated_redis
from test.delivery.effects.test_effect_leases import activate


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["owner", "partial", "legacy", "corrupt", "unavailable"])
async def test_owner_inspection_reports_effects_without_mutation(isolated_redis, monkeypatch, mode):
    client = isolated_redis
    spec, _ = activate(client, kind="followup" if mode == "owner" else "periodic",
                       owner=mode == "owner")
    if mode == "partial":
        client.set("all_memory", "wrong type")
    if mode in {"owner", "partial"}:
        await EffectWorker(client).run_action(spec.action_id)
    key = DeliveryStore.key(spec.action_id)
    if mode in {"legacy", "corrupt"}:
        raw = json.loads(client.get(key))
        if mode == "legacy":
            for name in ("effects_version", "effects", "plan_json", "plan_digest", "plan_sha1"):
                raw.pop(name, None)
        else:
            raw["effects"][0]["payload_json"] = "PRIVATE CORRUPT PAYLOAD"
        client.set(key, json.dumps(raw))
    before = {key: client.dump(key) for key in client.scan_iter()}
    owner = load_owner()
    feedback = AsyncMock()
    monkeypatch.setitem(owner.process_delivery_command.__globals__, "send_to_event", feedback)

    def unavailable_get(key):
        raise ConnectionError("PRIVATE CONNECTION DETAILS")

    reader = (SimpleNamespace(eval=client.eval, get=unavailable_get)
              if mode == "unavailable" else client)
    ctx = SimpleNamespace(settings=SimpleNamespace(autonomy_owner_id=99),
                          repository=SimpleNamespace(redis_client=reader))
    event = Mock(spec=owner.PrivateMessageEvent, user_id=99)
    assert await owner.process_delivery_command(ctx, Mock(), event, f"发送状态 {spec.action_id}")
    message = feedback.await_args.args[2]
    assert "：sent。" in message
    if mode == "owner":
        assert "跟进源完成：已完成" in message
        assert "出站去重：待核对（实际送达时间未知）" in message
    elif mode == "partial":
        assert "全局历史：待核对" in message
        assert "资讯指纹：已完成" in message
        assert "出站去重：已完成" in message
    elif mode == "unavailable":
        assert "补记状态暂不可用" in message
    else:
        assert "补记待核对" in message and "不能据此判断已完成" in message
    assert "PRIVATE" not in message
    assert {key: client.dump(key) for key in client.scan_iter()} == before
