from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.delivery import dispatcher
from test.delivery.test_sender_acknowledgement import load_function


class Finished(Exception):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_admin_finish_routes_through_dispatch_and_keeps_authorization(monkeypatch, allowed):
    send = AsyncMock(return_value=False)
    monkeypatch.setattr(dispatcher, "send_to_event", send)
    matcher = SimpleNamespace(finish=AsyncMock(side_effect=Finished))
    event = SimpleNamespace(user_id=1, get_plaintext=lambda: "mako-admin block 2")
    storage = Mock()
    handle = load_function("src/plugins/governance.py", "handle_admin", {
        "governance": SimpleNamespace(is_admin_user=lambda user: allowed),
        "storage": storage, "finish_to_event": dispatcher.finish_to_event,
    })
    with pytest.raises(Finished):
        await handle(matcher, event)
    assert storage.add_user_blacklist.call_count == int(allowed)
    send.assert_awaited_once()
    assert send.call_args.args[:2] == (matcher, event)
    matcher.finish.assert_awaited_once_with()
