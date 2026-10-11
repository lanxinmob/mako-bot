"""Redis-only plans, source bindings and recovery of accepted original intents."""
from copy import deepcopy
import hashlib
import json
import re

from src.services.persistence.ledger.repository import (
    LedgerRepository, LedgerUnavailable, _uncertain, pending_key, control_key, decode)
from .transitions import SCRIPT

PREFIX = 'mako:companion:v1:'


def key(kind, user):
    return PREFIX + kind + ':' + str(int(user))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class CompanionUnavailable(LedgerUnavailable):
    pass


class CompanionRepository:
    def __init__(self, backend):
        self.backend = backend
        self.ledger = LedgerRepository(backend)

    @property
    def client(self):
        client = self.backend.redis
        if client is None:
            raise CompanionUnavailable('companion persistence requires Redis')
        return client

    def now(self):
        try:
            seconds, micros = self.client.time()
            return seconds * 1000 + micros // 1000
        except Exception as exc:
            raise CompanionUnavailable('persistent clock unavailable') from exc

    def state(self, user):
        return self.ledger.state(user)

    def list(self, user):
        self.state(user)
        try:
            values = [json.loads(v) for v in self.client.hvals(key('plans', user))]
            if any(v['user_id'] != user or v.get('schema_version') != 1 for v in values):
                raise ValueError('invalid plan owner or schema')
            return sorted(values, key=lambda p: p['created_at_ms'], reverse=True)
        except Exception as exc:
            raise CompanionUnavailable('plan projection unavailable') from exc

    def raw(self, user, pid):
        if not re.fullmatch(r'[0-9a-f]{12}', pid):
            return None
        self.state(user)
        try:
            raw = self.client.hget(key('plans', user), pid)
            if raw:
                plan = json.loads(raw)
                if plan.get('user_id') != user or plan.get('schema_version') != 1 or plan.get('plan_id') != pid:
                    raise ValueError('invalid stored plan identity')
            return raw
        except Exception as exc:
            raise CompanionUnavailable('plan unavailable') from exc

    def get(self, user, pid):
        raw = self.raw(user, pid)
        if raw:
            plan = json.loads(raw)
            if plan['user_id'] != user or plan.get('schema_version') != 1:
                raise CompanionUnavailable('invalid plan identity')
            return plan
        return None

    def frozen(self, user, sid):
        self.state(user)
        try:
            raw = self.client.hget(key('steps', user), sid)
            revision = self.client.hget(key('source', user), sid)
            return (raw, revision) if raw and revision else None
        except Exception as exc:
            raise CompanionUnavailable('step source unavailable') from exc

    def users(self):
        try:
            # A reserved create may have no plan yet; startup still recovers it.
            return sorted({int(k.rsplit(':', 1)[1]) for kind in ('plans','operations')
                           for k in self.client.scan_iter(match=PREFIX + kind + ':*')})
        except Exception as exc:
            raise CompanionUnavailable('plan discovery unavailable') from exc

    def _keys(self, user, intent):
        old = json.loads(intent['expected']) if intent.get('expected') else {}
        def action(step):
            aid = old.get('steps', {}).get(step, {}).get('action_id')
            return 'mako:delivery:v1:' + (aid or 'companion-missing')
        return [key('plans', user), key('steps', user), key('source', user), PREFIX + 'due',
                key('operations', user), f'notes:{user}', control_key(user), action('reminder'), action('review')]

    def apply(self, user, event, intent):
        client = self.client
        local_key = pending_key(client, user)
        identity = 'companion:' + event
        prior = _uncertain.get(local_key)
        if prior and prior[0] != identity:
            raise CompanionUnavailable('another immutable intent is unconfirmed')
        if prior:
            intent = prior[1]
        else:
            _uncertain[local_key] = (identity, deepcopy(intent))
        try:
            keys = self._keys(user, intent)
            reserved = json.loads(client.eval(SCRIPT, len(keys), *keys, 'reserve', event, canonical(intent)))
            if reserved['status'] == 'pending':
                reserved = json.loads(client.eval(SCRIPT, len(keys), *keys, 'apply', event, '{}'))
            if reserved['status'] != 'unconfirmed':
                _uncertain.pop(local_key, None)
            return reserved
        except Exception as exc:
            raise CompanionUnavailable('original companion operation pending confirmation') from exc

    def recover(self, user, event):
        client = self.client
        try:
            seen = client.hget(key('operations', user), 'seen:' + event)
            if seen == 'complete':
                _uncertain.pop(pending_key(client, user), None)
                return json.loads(client.hget(key('operations', user), 'result:' + event) or
                                  '{"status":"already_processed"}')
            if seen == 'pending':
                intent = json.loads(client.hget(key('operations', user), 'intent:' + event))
                return self.apply(user, event, intent)
            local = _uncertain.get(pending_key(client, user))
            if local and local[0] == 'companion:' + event:
                return self.apply(user, event, local[1])
            return None
        except Exception as exc:
            raise CompanionUnavailable('original operation result unavailable') from exc

    def reconcile(self, user):
        client = self.client
        local = _uncertain.get(pending_key(client, user))
        pending = local[0] if local else decode(client.hget(control_key(user), 'state')).get('pending')
        if pending and pending.startswith('companion:'):
            event = pending.removeprefix('companion:')
            if not re.fullmatch(r'[0-9a-f]{64}', event):
                raise CompanionUnavailable('invalid pending identity')
            return self.recover(user, event)
        return self.ledger.reconcile(user) if pending else None

    def due(self, limit=20):
        self.now()  # No process-local clock can authorize transport.
        try:
            return self.client.zrangebyscore(PREFIX + 'due', '-inf', self.now(), start=0, num=limit)
        except Exception as exc:
            raise CompanionUnavailable('due index unavailable') from exc

    def guard(self, spec):
        user = int(spec.target_id)
        control = self.state(user)
        value = self.frozen(user, spec.business_id)
        if not value or value[1] != spec.revision or hashlib.sha1(value[0].encode()).hexdigest() != spec.source_digest:
            return False
        frozen = json.loads(value[0])
        plan = self.get(user, frozen['plan_id'])
        now = self.now()
        if (not plan or plan['status'] != 'active' or plan['bot_id'] != spec.bot_id
                or plan['content_revision'] != frozen['content_revision']
                or control['revision'] != frozen['memory_revision']
                or not frozen['at_ms'] <= now < frozen['until_ms']):
            return False
        if frozen['step'] == 'review':
            from src.services.delivery.state import DeliveryStore
            reminder = plan['steps']['reminder']
            if (plan['consent'] != 'granted' or plan['authorization_revision'] != frozen['authorization_revision']
                    or not reminder['source_complete'] or
                    DeliveryStore(self.client).inspect(reminder['action_id']).state != 'sent'):
                return False
        return True
