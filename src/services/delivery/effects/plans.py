"""Build immutable, bounded plans from the exact transport specification."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from src.services.persistence.effects.source import source_effect_id, source_payload, validate_source_spec
from ..dedup import canonical_intent, normalize_outbound_text


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def effect_identity(action_id, kind):
    return hashlib.sha256(canonical([action_id, kind, 0]).encode()).hexdigest()


def _count(value, minimum):
    if type(value) is not int or not minimum <= value <= 2**31 - 1:
        raise ValueError("invalid effect retention")
    return value


@dataclass(frozen=True)
class EffectPlan:
    raw: str

    @property
    def digest(self):
        return hashlib.sha256(self.raw.encode()).hexdigest()

    @property
    def checksum(self):
        return hashlib.sha1(self.raw.encode()).hexdigest()

    def validate(self, spec):
        if not isinstance(self.raw, str) or len(self.raw.encode()) > 131072:
            raise ValueError("invalid effect plan size")
        value = json.loads(self.raw)
        if (not isinstance(value, dict) or value.get("version") != 1
                or value.get("action_id") != spec.action_id or value.get("spec_digest") != spec.digest):
            raise ValueError("effect plan identity mismatch")
        tasks = value.get("tasks")
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 3:
            raise ValueError("invalid effect task count")
        # Rebuild using only explicit frozen retention/offset inputs. This
        # rejects arbitrary payloads, missing tasks, extra fields and versions.
        parameters = {}
        for task in tasks:
            if not isinstance(task, dict) or not isinstance(task.get("payload_json"), str):
                raise ValueError("invalid effect task")
            data = json.loads(task["payload_json"])
            if not isinstance(data, dict):
                raise ValueError("invalid effect payload")
            if task.get("kind") == "outbound_dedup":
                parameters.update(outbound_max_records=data.get("max_records"),
                                  outbound_ttl=data.get("ttl"), utc_offset_seconds=data.get("utc_offset_seconds"))
            elif task.get("kind") == "global_history":
                parameters["history_max_records"] = data.get("max_records")
        expected = build_plan(spec, **parameters)
        if self.raw != expected.raw:
            raise ValueError("effect plan does not match frozen delivery")
        return self


def build_plan(spec, *, outbound_max_records=None, outbound_ttl=None,
               history_max_records=None, utc_offset_seconds=None):
    tasks = []

    def task(kind, data, *, timed=False):
        raw = canonical(data)
        tasks.append({"effect_id": effect_identity(spec.action_id, kind), "kind": kind,
                      "codec_version": 1, "payload_json": raw,
                      "payload_digest": hashlib.sha1(raw.encode()).hexdigest(),
                      "time_basis": "transport_recorded" if timed else "none"})

    if spec.kind not in {"followup", "reminder", "periodic"}:
        raise ValueError("unsupported delivery plan")
    if spec.kind in {"followup", "reminder"}:
        validate_source_spec(spec)
        # Source payload binds the entire spec, not just a mutable business ID.
        kind = spec.kind + "_complete"
        task(kind, json.loads(source_payload(spec)))
        assert tasks[-1]["effect_id"] == source_effect_id(spec)
    if spec.kind == "reminder":
        if spec.target_type != "group" or not spec.source_digest:
            raise ValueError("invalid reminder source")
    else:
        if type(utc_offset_seconds) is not int or not -86399 <= utc_offset_seconds <= 86399:
            raise ValueError("explicit frozen timezone offset required")
        if spec.kind == "periodic":
            body = json.loads(spec.payload)
            if (not isinstance(body, dict) or spec.target_type != "group"
                    or set(body) != {"text", "intent", "fingerprints"}
                    or not isinstance(body["text"], str) or not body["text"].strip()
                    or not isinstance(body["intent"], str) or not isinstance(body["fingerprints"], list)
                    or any(not isinstance(fp, str) or not fp for fp in body["fingerprints"])):
                raise ValueError("invalid frozen periodic payload")
            content, intent, source = body["text"], body["intent"], spec.business_id
        else:
            if spec.target_type != "private" or not spec.source_digest:
                raise ValueError("invalid followup source")
            content, intent, source = spec.payload, "reminder", "relationship.followup"
        identifier = effect_identity(spec.action_id, "outbound_dedup")
        task("outbound_dedup", {"record": {
            "message_id": identifier, "target_type": spec.target_type, "target_id": int(spec.target_id),
            "intent": canonical_intent(intent, content), "content": content,
            "normalized_content": normalize_outbound_text(content), "source": source,
        }, "max_records": _count(outbound_max_records, 20), "ttl": _count(outbound_ttl, 86400),
            "utc_offset_seconds": utc_offset_seconds, "sent_at_ms": None}, timed=True)
        if spec.kind == "periodic":
            task("global_history", {"record": {"role": "assistant", "content": content,
                "nickname": None, "user_id": None, "group_id": int(spec.target_id)},
                "max_records": _count(history_max_records, 1000),
                "utc_offset_seconds": utc_offset_seconds, "sent_at_ms": None}, timed=True)
            if body["fingerprints"]:
                task("news_fingerprints", {"fingerprints": sorted(set(body["fingerprints"])),
                                          "sent_at_ms": None}, timed=True)
    plan = EffectPlan(canonical({"version": 1, "action_id": spec.action_id,
                                 "spec_digest": spec.digest, "tasks": tasks}))
    if len(plan.raw.encode()) > 131072:
        raise ValueError("effect plan too large")
    return plan
