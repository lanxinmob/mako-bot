"""Deterministic version-one codecs; no current settings, UUID or time defaults."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

from src.models.schemas import ChatRecord, OutboundMessageRecord
from src.services.persistence.effects import EffectNeedsReview, EffectWriter
from src.services.persistence.effects.source import SourceEffectWriter, source_payload


class EffectTargets:
    def __init__(self, redis_client):
        self.writer = EffectWriter(redis_client)
        self.sources = SourceEffectWriter(redis_client)

    @staticmethod
    def _time(payload, *, local=False):
        value = payload["sent_at_ms"]
        if type(value) is not int or not 0 < value < 2**53:
            raise EffectNeedsReview("actual effect time unavailable")
        instant = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        if not local:
            return instant
        offset = payload["utc_offset_seconds"]
        if type(offset) is not int or not -86399 <= offset <= 86399:
            raise EffectNeedsReview("invalid frozen time offset")
        # Existing history/outbound readers use naive local datetimes. Freeze
        # their serialized value using the plan's offset, never worker localtime.
        return instant.astimezone(timezone(timedelta(seconds=offset))).replace(tzinfo=None)

    def apply(self, lease):
        task = lease.task
        if (task.codec_version != 1 or task.state != "leased"
                or hashlib.sha1(task.payload_json.encode()).hexdigest() != task.payload_digest):
            raise EffectNeedsReview("invalid leased effect payload")
        payload = json.loads(task.payload_json)
        if task.kind in {"followup_complete", "reminder_complete"}:
            if task.kind != lease.spec.kind + "_complete" or task.payload_json != source_payload(lease.spec):
                raise EffectNeedsReview("source effect binding mismatch")
            return self.sources.complete_effect(task.effect_id, lease.spec)
        if task.time_basis != "transport_recorded":
            raise EffectNeedsReview("effect time requires review")
        if task.kind == "global_history":
            record = ChatRecord(**payload["record"], time=self._time(payload, local=True))
            return self.writer.append_global_record(task.effect_id, record, max_records=payload["max_records"])
        if task.kind == "outbound_dedup":
            record = OutboundMessageRecord(**payload["record"], created_at=self._time(payload, local=True))
            return self.writer.record_outbound(task.effect_id, record,
                max_records=payload["max_records"], ttl=payload["ttl"])
        if task.kind == "news_fingerprints":
            return self.writer.record_news(task.effect_id, payload["fingerprints"], sent_at=self._time(payload))
        raise EffectNeedsReview("unsupported effect codec")
