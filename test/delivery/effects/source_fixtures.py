"""Synthetic sent/task fixtures; production plan activation is tested separately."""
import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from src.models.schemas import ReminderRecord
from src.services.delivery.reminder_delivery import reminder_spec
from src.services.delivery.state import DeliverySpec, DeliveryStore
from src.services.persistence.effects.source import source_effect_id, source_payload
from src.services.persistence.followups import FollowupSource, revision_key
from src.services.persistence.relationships import RelationshipsRepository
from src.services.persistence.reminder_state import ReminderStateStore


def make_source(client, kind):
    if kind == "followup":
        repo = RelationshipsRepository(SimpleNamespace(redis=client))
        item = repo.add_relationship_memory(7, "promise", "synthetic",
                                          due_at=datetime.now() - timedelta(seconds=1))
        snapshot = FollowupSource(client).load(7, item.memory_id)
        spec = DeliverySpec("followup", "99", "private", "7", item.memory_id,
                            snapshot.revision, "synthetic", 2**52, "relationship:7",
                            item.memory_id, snapshot.digest, revision_key(7))
    else:
        repo = ReminderStateStore(client)
        item = ReminderRecord(reminder_id="fixture", session_id="group_1", user_id=7,
                              group_id=1, content="synthetic",
                              remind_time=datetime.now() + timedelta(hours=1))
        snapshot = repo.create(item, bot_id="99").snapshot
        spec = reminder_spec(snapshot, valid_until_ms=2**52)
    return repo, snapshot, spec


def install_task(client, spec, *, owner=False):
    store = DeliveryStore(client)
    claim = store.claim(spec)
    assert claim.ok
    if owner:
        assert store.mark_unknown(spec.action_id, claim.token).ok
        assert store.reconcile(spec.action_id, delivered=True, operator_id="99").ok
    else:
        assert store.begin_send(spec, claim.token).ok
        assert store.mark_sent(spec.action_id, claim.token).ok
    key = store.key(spec.action_id)
    action = json.loads(client.get(key))
    payload = source_payload(spec)
    action.update(effects_version=1, effects=[{
        "effect_id": source_effect_id(spec), "kind": spec.kind + "_complete", "codec_version": 1,
        "payload_json": payload, "payload_digest": hashlib.sha1(payload.encode()).hexdigest(),
        "state": "pending",
    }])
    client.set(key, json.dumps(action))
    return key


def replace_source(repo, snapshot, spec):
    if spec.kind == "followup":
        repo.update_relationship_memory(7, spec.business_id, "replacement")
    else:
        result = repo.replace(snapshot, snapshot.record.model_copy(update={"content": "replacement"}),
                              bot_id="99")
        assert result.ok
