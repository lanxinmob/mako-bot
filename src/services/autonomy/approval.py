"""Redis-only approval fencing. No configuration, connections or memory fallback.

Synchronous API: callers in asyncio must offload calls with asyncio.to_thread.
Only a successful begin_send authorizes one transport invocation. Never retry
that invocation after a timeout, cancellation or an ambiguous Redis response.
"""
from __future__ import annotations

import hashlib
import asyncio
import json
import math
import secrets
from dataclasses import dataclass
from typing import Any

from .models import PendingAction


class ApprovalUnavailable(RuntimeError):
    """Redis outcome unavailable; stop approval, including on ambiguous writes."""


class InvalidPending(ValueError):
    """Stored pending is malformed; it cannot authorize a send."""


@dataclass(frozen=True)
class ApprovalSnapshot:
    pending_id: str
    digest: str
    raw: str

    def pending(self) -> PendingAction:
        """Return a fresh copy; send exactly this approved target and content."""
        return PendingAction(**json.loads(self.raw))


@dataclass(frozen=True)
class ApprovalResult:
    ok: bool
    code: str
    state: str
    token: str
    lease_until_ms: int


# All decisions and timestamps use one Redis operation. Records have no TTL:
# losing a sending/unknown tombstone would make an old approval retryable.
_TRANSITION = r"""
local op, id, digest, token = ARGV[1], ARGV[2], ARGV[3], ARGV[4]
local approved_digest = ARGV[8]
local ttl, lease, sending_timeout = tonumber(ARGV[5]), tonumber(ARGV[6]), tonumber(ARGV[7])
local tm = redis.call('TIME')
local now = tonumber(tm[1]) * 1000 + math.floor(tonumber(tm[2]) / 1000)
local raw_state = redis.call('GET', KEYS[2])
local s = nil
if raw_state then
    local valid, decoded = pcall(cjson.decode, raw_state)
    if not valid or type(decoded) ~= 'table' or decoded.schema_version ~= 1
        or type(decoded.state) ~= 'string' or type(decoded.claim_token) ~= 'string'
        or type(decoded.lease_until_ms) ~= 'number' then
        return redis.error_reply('invalid approval record')
    end
    s = decoded
end
local function result(ok, code)
    return {ok, code, s and s.state or '', s and s.claim_token or '',
        tostring(s and s.lease_until_ms or 0)}
end
local function save(state)
    s.state = state
    s.updated_at = now
    redis.call('SET', KEYS[2], cjson.encode(s))
end
if s and s.state == 'sending' and now >= s.lease_until_ms then
    save('unknown')
end
if op == 'inspect' then return result(1, 'observed') end
if op == 'reconcile_sent' or op == 'reconcile_cancelled' then
    if not s then return result(0, 'missing') end
    local target = op == 'reconcile_sent' and 'sent' or 'cancelled'
    if s.state == target then return result(1, 'already_resolved') end
    if s.state ~= 'unknown' then return result(0, 'blocked') end
    s.resolution_source = 'owner'
    s.resolved_at = now
    save(target)
    return result(1, 'resolved')
end
if op == 'cleanup' then
    if not s or s.claim_token ~= token then return result(0, 'fenced') end
    if s.state ~= 'sent' and s.state ~= 'cancelled' then return result(0, 'blocked') end
    -- Validate latest type before any deletion (Lua errors do not roll back).
    local latest = redis.call('GET', KEYS[3])
    local raw = redis.call('GET', KEYS[1])
    if raw and redis.sha1hex(raw) ~= s.digest then return result(0, 'changed') end
    redis.call('DEL', KEYS[1])
    if latest == id then redis.call('DEL', KEYS[3]) end
    return result(1, 'cleaned')
end
if op == 'sent' or op == 'unknown' or op == 'reject' then
    if not s or s.claim_token ~= token then return result(0, 'fenced') end
    if op == 'reject' then
        if s.state ~= 'queued' then return result(0, 'blocked') end
        save('rejected_before_send')
    else
        if s.state ~= 'sending' then return result(0, 'blocked') end
        save(op)
    end
    return result(1, 'transitioned')
end
if op ~= 'claim' and op ~= 'begin' and op ~= 'cancel' then
    return redis.error_reply('invalid approval operation')
end
if op == 'begin' and (not s or s.claim_token ~= token) then return result(0, 'fenced') end
if s then
    if s.state ~= 'queued' and s.state ~= 'rejected_before_send' then
        return result(0, 'blocked')
    end
    if s.digest ~= digest then return result(0, 'changed') end
end
local raw = redis.call('GET', KEYS[1])
if not raw then return result(0, 'missing') end
if redis.sha1hex(raw) ~= digest then return result(0, 'changed') end
local valid, p = pcall(cjson.decode, raw)
if not valid or type(p) ~= 'table' or p.pending_id ~= id
    or (p.target_type ~= 'group' and p.target_type ~= 'private')
    or type(p.target_id) ~= 'number' or p.target_id <= 0 or p.target_id % 1 ~= 0
    or type(p.message) ~= 'string' or p.message == ''
    or type(p.reason) ~= 'string' or type(p.created_at) ~= 'number'
    or p.created_at ~= p.created_at then return result(0, 'invalid') end
local created = p.created_at * 1000
if created > now or now >= created + ttl then return result(0, 'expired') end
if op == 'begin' then
    if s.state ~= 'queued' then return result(0, 'blocked') end
    if s.approved_digest ~= approved_digest then return result(0, 'changed') end
    if now >= s.lease_until_ms then return result(0, 'lease_expired') end
    s.lease_until_ms = now + sending_timeout
    save('sending')
    return result(1, 'started')
end
if op == 'claim' and s and s.state == 'queued' and now < s.lease_until_ms then
    return result(0, 'busy')
end
s = {schema_version=1, state='', claim_token=token, digest=digest,
    approved_digest=approved_digest,
    target_type=p.target_type, target_id=p.target_id, updated_at=now,
    lease_until_ms=now + lease}
if op == 'cancel' then save('cancelled') else save('queued') end
return result(1, op == 'cancel' and 'cancelled' or 'claimed')
"""


class ApprovalStore:
    """Inject a synchronous redis-py client with bounded socket timeouts.

    Use load/load_latest rather than the repository's fallback reads. Missing
    Redis raises ApprovalUnavailable. Business refusals return ok=False.
    No operation creates pending JSON or deletes execution evidence.
    """

    def __init__(self, redis_client: Any, *, pending_ttl_seconds: float,
                 queued_lease_seconds: float = 30, sending_timeout_seconds: float = 120):
        self.redis = redis_client
        self.ttl_ms = self._milliseconds(pending_ttl_seconds)
        self.lease_ms = self._milliseconds(queued_lease_seconds)
        self.sending_ms = self._milliseconds(sending_timeout_seconds)

    @staticmethod
    def _milliseconds(value: float) -> int:
        if not math.isfinite(value) or value < 0.001:
            raise ValueError('durations must be finite and at least one millisecond')
        return int(value * 1000)

    @staticmethod
    def _id(pending_id: str) -> str:
        if not isinstance(pending_id, str) or not pending_id or pending_id == 'latest':
            raise ValueError('invalid pending id')
        return pending_id

    def _call(self, method: str, *args: Any) -> Any:
        if self.redis is None:
            raise ApprovalUnavailable('approval requires Redis')
        try:
            return getattr(self.redis, method)(*args)
        except Exception as exc:
            # Do not include exception text: clients may embed sensitive payloads.
            raise ApprovalUnavailable('approval Redis operation failed; stop sending') from exc

    @staticmethod
    def _text(value: Any) -> str:
        return value.decode('utf-8') if isinstance(value, bytes) else str(value)

    def load(self, pending_id: str) -> ApprovalSnapshot | None:
        """Read a snapshot; validity/expiry are checked atomically on claim/begin."""
        pending_id = self._id(pending_id)
        raw = self._call('get', f'autonomy:pending:{pending_id}')
        if raw is None:
            return None
        try:
            raw = self._text(raw)
            p = PendingAction(**json.loads(raw))
            if (p.pending_id != pending_id or p.target_type not in ('group', 'private')
                    or type(p.target_id) is not int or p.target_id <= 0
                    or not isinstance(p.message, str) or not p.message.strip()
                    or not isinstance(p.reason, str) or not isinstance(p.intent, str)
                    or type(p.created_at) not in (int, float) or not math.isfinite(p.created_at)):
                raise ValueError('invalid pending fields')
        except (ValueError, TypeError, UnicodeError) as exc:
            raise InvalidPending('malformed approval pending') from exc
        return ApprovalSnapshot(pending_id, hashlib.sha1(raw.encode('utf-8')).hexdigest(), raw)

    def load_latest(self) -> ApprovalSnapshot | None:
        """Resolve latest once; subsequent transitions fence the exact snapshot."""
        pending_id = self._call('get', 'autonomy:pending:latest')
        return self.load(self._text(pending_id)) if pending_id is not None else None

    def _transition(self, op: str, pending_id: str, *, digest: str = '',
                    token: str = '', approved_digest: str = '') -> ApprovalResult:
        pending_id = self._id(pending_id)
        values = self._call(
            'eval', _TRANSITION, 3, f'autonomy:pending:{pending_id}',
            f'autonomy:execution:{pending_id}', 'autonomy:pending:latest',
            op, pending_id, digest, token, self.ttl_ms, self.lease_ms, self.sending_ms,
            approved_digest,
        )
        try:
            ok, code, state, returned_token, until = values
            # A refusal must not disclose the current holder's capability token.
            return ApprovalResult(bool(int(ok)), self._text(code), self._text(state),
                                  token if int(ok) and token else '', int(until))
        except (ValueError, TypeError) as exc:
            raise ApprovalUnavailable('invalid approval Redis response') from exc

    @staticmethod
    def content_digest(snapshot: ApprovalSnapshot, message: str) -> str:
        pending = snapshot.pending()
        data = [pending.target_type, pending.target_id, pending.intent, message]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode('utf-8')).hexdigest()

    def claim(self, snapshot: ApprovalSnapshot, message: str) -> ApprovalResult:
        """Explicit approval only. Every attempt uses a fresh unguessable token."""
        return self._transition('claim', snapshot.pending_id, digest=snapshot.digest,
                                token=secrets.token_hex(32),
                                approved_digest=self.content_digest(snapshot, message))

    def begin_send(self, snapshot: ApprovalSnapshot, token: str, message: str) -> ApprovalResult:
        """Guard immediately before transport; ok grants exactly one attempt."""
        return self._transition('begin', snapshot.pending_id, digest=snapshot.digest, token=token,
                                approved_digest=self.content_digest(snapshot, message))

    def reject_before_send(self, pending_id: str, token: str) -> ApprovalResult:
        """Release only queued work; sending can never become retryable."""
        return self._transition('reject', pending_id, token=token)

    def mark_sent(self, pending_id: str, token: str) -> ApprovalResult:
        """Record confirmed transport success, independent of later bookkeeping."""
        return self._transition('sent', pending_id, token=token)

    def mark_unknown(self, pending_id: str, token: str) -> ApprovalResult:
        """Transport started but delivery is uncertain; never automatically retry."""
        return self._transition('unknown', pending_id, token=token)

    def cancel(self, snapshot: ApprovalSnapshot) -> ApprovalResult:
        """Owner cancellation wins against queued/begin atomically, not sending."""
        return self._transition('cancel', snapshot.pending_id, digest=snapshot.digest,
                                token=secrets.token_hex(32))

    def inspect(self, pending_id: str) -> ApprovalResult:
        """Observe state; overdue sending becomes unknown, without releasing it."""
        return self._transition('inspect', pending_id)

    def reconcile(self, pending_id: str, *, delivered: bool) -> ApprovalResult:
        """Owner-only caller: resolve unknown without granting a transport attempt."""
        return self._transition('reconcile_sent' if delivered else 'reconcile_cancelled', pending_id)

    def cleanup(self, pending_id: str, token: str) -> ApprovalResult:
        """For sent/cancelled only: remove matching pending and compare-delete latest."""
        return self._transition('cleanup', pending_id, token=token)


@dataclass
class ApprovalAttempt:
    """One caller's transport boundary; persistent state remains authoritative."""

    store: ApprovalStore
    snapshot: ApprovalSnapshot
    token: str
    boundary_uncertain: bool = False
    acknowledged: bool = False

    async def begin(self, message: str) -> bool:
        self.boundary_uncertain = True
        result = await asyncio.to_thread(self.store.begin_send, self.snapshot, self.token, message)
        if not result.ok:
            self.boundary_uncertain = False
        return result.ok

    async def finish(self) -> bool:
        operation = (self.store.mark_sent if self.acknowledged else
                     self.store.mark_unknown if self.boundary_uncertain else
                     self.store.reject_before_send)
        result = await asyncio.to_thread(operation, self.snapshot.pending_id, self.token)
        return result.ok
