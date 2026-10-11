"""Canonical step sources and immutable private delivery bindings."""
import hashlib
import json

from src.services.delivery.state import DeliverySpec
from .repository import key, canonical


def spec_for(user, sid, raw, revision):
    source = json.loads(raw)
    if (source.get('schema_version') != 1 or source['user_id'] != user
            or sid != source['plan_id'] + ':' + source['step'] or source['revision'] != revision):
        raise ValueError('invalid companion source identity')
    return DeliverySpec('companion', source['bot_id'], 'private', str(user), sid, revision,
        source['payload'], source['until_ms'], key('steps', user), sid,
        hashlib.sha1(raw.encode()).hexdigest(), key('source', user))


def validate_spec(spec):
    if spec.kind != 'companion' or spec.target_type != 'private' or not spec.target_id.isdecimal():
        raise ValueError('invalid companion private target')
    user = int(spec.target_id)
    import re
    if (not re.fullmatch(r'[0-9a-f]{12}:(reminder|review)', spec.business_id)
            or spec.source_field != spec.business_id or spec.source_key != key('steps', user)
            or spec.revision_key != key('source', user)
            or not re.fullmatch(r'[0-9a-f]{40}', spec.source_digest)):
        raise ValueError('invalid companion source binding')
