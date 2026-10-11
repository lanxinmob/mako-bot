"""Confirmed Redis intent handling. Memory writes require explicit test opt-in."""
import json
from copy import deepcopy
from threading import RLock

from src.services.persistence.followups import revision_key
from .script import SCRIPT

EMPTY = dict(revision=0, controlled=False, cutoff_ns=0)
_memory_lock = RLock()
_uncertain = {}


def pending_key(client, user_id):
    options = getattr(getattr(client, 'connection_pool', None), 'connection_kwargs', {})
    endpoint = tuple(options.get(k) for k in ('host', 'port', 'db')) if isinstance(options, dict) and options else id(client)
    return endpoint, user_id


class LedgerUnavailable(RuntimeError):
    pass


def control_key(user_id):
    return f'mako:memory:v1:control:{user_id}'


def decode(value):
    return json.loads(value) if value else deepcopy(EMPTY)


class LedgerRepository:
    def __init__(self, backend, *, allow_memory=False):
        self.backend, self.allow_memory = backend, allow_memory

    def _memory(self):
        memory = self.backend.memory
        if not hasattr(memory, 'ledger'):
            memory.ledger = {}
        return memory.ledger

    def state(self, user_id):
        try:
            client = self.backend.redis
            state = decode(client.hget(control_key(user_id), 'state')) if client else deepcopy(
                self._memory().get(user_id, {}).get('state', EMPTY))
            if client:
                local = _uncertain.get(pending_key(client, user_id))
                if local and client.hget(control_key(user_id), 'seen:' + local[0]) == 'complete':
                    _uncertain.pop(pending_key(client, user_id), None)
                elif local:
                    raise LedgerUnavailable('local mutation result unconfirmed')
            if state.get('pending') or (not client and not self.allow_memory):
                raise LedgerUnavailable('memory control persistence unavailable or pending')
            if (type(state.get('revision')) is not int or state['revision'] < 0 or
                    type(state.get('controlled')) is not bool or int(state.get('cutoff_ns', -1)) < 0):
                raise LedgerUnavailable('invalid memory control state')
            return state
        except Exception as exc:
            raise LedgerUnavailable('memory control unavailable') from exc

    def blocked(self, user_id, subject):
        client = self.backend.redis
        if client:
            return bool(client.hexists(control_key(user_id), 'blocked:' + subject))
        if not self.allow_memory:
            raise LedgerUnavailable('memory control persistence unavailable')
        return subject in self._memory().get(user_id, {}).get('blocked', set())

    def users(self):
        try:
            client = self.backend.redis
            if client:
                prefix = 'mako:memory:v1:control:'
                return [int(key[len(prefix):]) for key in client.scan_iter(match=prefix + '*')]
            if self.allow_memory:
                return list(self._memory())
            raise LedgerUnavailable('memory persistence unavailable')
        except Exception as exc:
            raise LedgerUnavailable('memory control discovery unavailable') from exc

    def rows(self, user_id):
        client = self.backend.redis
        if client:
            return dict(client.hgetall(f'relationship:{user_id}'))
        return {k: json.dumps(v, ensure_ascii=False) for k, v in
                self.backend.memory.relationship_memories.get(user_id, {}).items()}

    def notes(self, user_id):
        client = self.backend.redis
        if client:
            return dict(client.hgetall(f'notes:{user_id}'))
        return {k: json.dumps(v, ensure_ascii=False) for k, v in self.backend.memory.notes.get(user_id, {}).items()}

    def apply(self, user_id, event_id, plan):
        client = self.backend.redis
        if not client:
            if not self.allow_memory:
                raise LedgerUnavailable('Redis confirmation required')
            return self._apply_memory(user_id, event_id, plan)
        keys = [control_key(user_id), f'relationship:{user_id}', f'notes:{user_id}', revision_key(user_id),
                'relationship:followups', 'mako:delivery:v1:legacy:followups',
                f'mako:memory:v1:operations:{user_id}']
        local_key = pending_key(client, user_id)
        prior = _uncertain.get(local_key)
        if prior and prior[0] != event_id:
            raise LedgerUnavailable('another immutable mutation is unconfirmed')
        if prior:
            plan = prior[1]
        else:
            _uncertain[local_key] = (event_id, deepcopy(plan))
        try:
            reserved = decode(client.eval(SCRIPT, len(keys), *keys, 'reserve', event_id,
                                          json.dumps(plan, ensure_ascii=False)))
            if reserved['status'] != 'pending':
                _uncertain.pop(local_key, None)
                return reserved
            # An identical reservation resumes its immutable persisted plan.
            result = decode(client.eval(SCRIPT, len(keys), *keys, 'apply', event_id, '{}'))
            if result['status'] != 'unconfirmed':
                _uncertain.pop(local_key, None)
            return result
        except Exception as exc:
            raise LedgerUnavailable('ledger result pending; reuse the same operation identity') from exc

    def reconcile(self, user_id):
        """Finish only the immutable intent already accepted for this user."""
        client = self.backend.redis
        if not client:
            if self.allow_memory:
                return None
            raise LedgerUnavailable('Redis confirmation required')
        try:
            local = _uncertain.get(pending_key(client, user_id))
            pending = local[0] if local else decode(client.hget(control_key(user_id), 'state')).get('pending')
            if pending:
                if isinstance(pending, str) and pending.startswith('companion:'):
                    from src.services.persistence.companion.repository import CompanionRepository
                    return CompanionRepository(self.backend).reconcile(user_id)
                if not isinstance(pending, str) or len(pending) != 64:
                    raise LedgerUnavailable('invalid pending operation identity')
                return self.recover(user_id, pending)
            return None
        except Exception as exc:
            raise LedgerUnavailable('original operation result unconfirmed') from exc

    def recover(self, user_id, event_id):
        client = self.backend.redis
        if not client:
            if not self.allow_memory:
                raise LedgerUnavailable('Redis confirmation required')
            data = self._memory().get(user_id, {})
            return data.get('results', {}).get(event_id, dict(status='already_processed')) if event_id in data.get('seen', set()) else None
        try:
            seen = client.hget(control_key(user_id), 'seen:' + event_id)
            if seen == 'complete':
                _uncertain.pop(pending_key(client, user_id), None)
                return decode(client.hget(control_key(user_id), 'result:' + event_id) or '{"status":"already_processed"}')
            if seen == 'pending':
                return self.apply(user_id, event_id, {})
            local = _uncertain.get(pending_key(client, user_id))
            if local and local[0] == event_id:
                return self.apply(user_id, event_id, local[1])
            return None
        except Exception as exc:
            raise LedgerUnavailable('operation result unconfirmed') from exc

    def _apply_memory(self, user_id, event_id, plan):
        with _memory_lock:
            data = self._memory().setdefault(user_id, dict(state=deepcopy(EMPTY), seen=set(), results={}, blocked=set()))
            if event_id in data['seen']:
                return data['results'].get(event_id, dict(status='already_processed'))
            state, rows, notes = data['state'], self.rows(user_id), self.notes(user_id)
            if state['revision'] != plan['expected_revision'] or any(rows.get(k, False) != v for k, v in plan['expected'].items()) or any(
                    notes.get(k, False) != v for k, v in plan['expected_notes'].items()):
                return dict(status='conflict')
            if plan.get('no_change'):
                result = dict(status=plan['status'], memory_id=plan['memory_id'], revision=state['revision'])
                data['seen'].add(event_id)
                data['results'][event_id] = result
                while len(data['results']) > 100:
                    data['results'].pop(next(iter(data['results'])))
                return result
            mem = self.backend.memory
            records = mem.relationship_memories.setdefault(user_id, {})
            records.update({k: decode(v) for k, v in plan['records'].items()})
            target_notes = mem.notes.setdefault(user_id, {})
            for key in plan['delete_notes']:
                target_notes.pop(key, None)
            target_notes.update({k: decode(v) for k, v in plan['notes'].items()})
            for key in plan['cancel']:
                mem.relationship_followups.pop(key, None)
            for key, value in plan['due'].items():
                mem.relationship_followups[key] = (user_id, value['at'])
            state['revision'] += 1
            if plan['controlled']:
                state.update(controlled=True, cutoff_ns=plan['cutoff_ns'])
            for key, value in plan['blocked'].items():
                data['blocked'].add(key) if value else data['blocked'].discard(key)
            result = dict(status=plan['status'], memory_id=plan['memory_id'], revision=state['revision'])
            data['seen'].add(event_id)
            data['results'][event_id] = result
            while len(data['results']) > 100:
                data['results'].pop(next(iter(data['results'])))
            return result
