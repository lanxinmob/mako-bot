"""Classify an abandoned observation; it never grants another send attempt."""
from .delivery import HistoryDeliveryStore
from .plans import integer


CLASSIFY = """
local kind = redis.call('TYPE', KEYS[1]).ok
if kind == 'none' then return 'missing' end
if kind ~= 'string' then return redis.error_reply('invalid chat classification type') end
local raw = redis.call('GET', KEYS[1])
if raw ~= ARGV[1] then return 'changed' end
if redis.call('PTTL', KEYS[1]) ~= -1 then
    return redis.error_reply('unexpected chat classification TTL')
end
local item = cjson.decode(raw)
if item.state ~= 'sending' then return 'unchanged' end
local tm = redis.call('TIME')
local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
if now < 1 or now > 99999999999999 then
    return redis.error_reply('chat classification time capacity exceeded')
end
if now - item.begun_at_ms <= 300000 then return 'unchanged' end
item.state, item.unknown_reason = 'unknown', 'send_confirmation_timeout'
redis.call('SET', KEYS[1], cjson.encode(item))
return 'send_unknown'
"""


RECONCILE = """
local kind = redis.call('TYPE', KEYS[1]).ok
if kind == 'none' then return 'missing' end
if kind ~= 'string' then return redis.error_reply('invalid chat reconciliation type') end
local raw = redis.call('GET', KEYS[1])
if raw ~= ARGV[1] then return 'changed' end
if redis.call('PTTL', KEYS[1]) ~= -1 then
    return redis.error_reply('unexpected chat reconciliation TTL')
end
local item = cjson.decode(raw)
local outcome = ARGV[2]
if item.confirmation_source == 'owner' then
    if item.owner_conclusion == outcome then return item.state end
    return 'denied'
end
if item.state ~= 'unknown' then return 'denied' end
local tm = redis.call('TIME')
local now = tonumber(tm[1])*1000+math.floor(tonumber(tm[2])/1000)
if now < 1 or now > 99999999999999 then
    return redis.error_reply('chat reconciliation time capacity exceeded')
end
item.state, item.confirmation_source = outcome, 'owner'
item.owner_id, item.owner_conclusion, item.reviewed_at_ms = ARGV[3], outcome, now
item.delivered_at_ms = cjson.null
if outcome == 'sent' then item.tasks = {session='needs_review', global='needs_review'} end
redis.call('SET', KEYS[1], cjson.encode(item))
return item.state
"""


class HistoryReconciliation:
    def __init__(self, redis_client):
        self.store = HistoryDeliveryStore(redis_client)

    def classify(self, action_id: str) -> str:
        snapshot = self.store.inspect(action_id)
        if snapshot is None:
            return "missing"
        if snapshot.state != "sending":
            return "unchanged"

        def run():
            result = self.store.redis.eval(CLASSIFY, 1, self.store.key(action_id), snapshot.raw)
            result = result.decode("utf-8") if isinstance(result, bytes) else result
            if result not in {"missing", "changed", "unchanged", "send_unknown"}:
                raise ValueError("invalid chat classification response")
            return result
        return self.store._read(run)

    def reconcile(self, action_id: str, *, delivered: bool, operator_id: str) -> str:
        if (type(delivered) is not bool or not isinstance(operator_id, str)
                or not operator_id.isascii() or not operator_id.isdigit()):
            raise ValueError("invalid chat reconciliation operator")
        integer(int(operator_id), 1)
        snapshot = self.store.inspect(action_id)
        if snapshot is None:
            return "missing"
        from .tasks import decode_tasks
        self.store._read(lambda: decode_tasks(snapshot))

        def run():
            result = self.store.redis.eval(RECONCILE, 1, self.store.key(action_id),
                                          snapshot.raw, "sent" if delivered else "abandoned", operator_id)
            result = result.decode("utf-8") if isinstance(result, bytes) else result
            if result not in {"missing", "changed", "denied", "sent", "abandoned"}:
                raise ValueError("invalid chat reconciliation response")
            return result
        return self.store._read(run)
