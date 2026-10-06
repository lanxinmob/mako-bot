"""Stable business identity, frozen payload and explicit delivery outcomes."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


class DeliveryUnavailable(RuntimeError):
    """Persistent outcome unavailable: no memory fallback or transport retry."""


@dataclass(frozen=True)
class DeliverySpec:
    kind: str
    bot_id: str
    target_type: str
    target_id: str
    business_id: str
    revision: str
    payload: str
    valid_until_ms: int
    source_key: str = ""
    source_field: str = ""
    source_digest: str = ""
    revision_key: str = ""

    def __post_init__(self):
        for value in (self.kind, self.bot_id, self.target_id, self.business_id, self.revision):
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise ValueError("invalid delivery identity")
        if self.target_type not in ("group", "private"):
            raise ValueError("invalid target type")
        if not isinstance(self.payload, str) or not self.payload.strip() or len(self.payload) > 32768:
            raise ValueError("invalid delivery payload")
        if type(self.valid_until_ms) is not int or not 0 < self.valid_until_ms < 2**53:
            raise ValueError("invalid delivery deadline")
        source = (self.source_key, self.source_field, self.source_digest, self.revision_key)
        if any(source) and not all(isinstance(value, str) and value for value in source):
            raise ValueError("incomplete delivery source binding")

    @property
    def action_id(self):
        identity = [self.kind, self.bot_id, self.target_type, self.target_id,
                    self.business_id, self.revision]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()

    def encode(self):
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @property
    def digest(self):
        return hashlib.sha256(self.encode().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DeliveryState:
    ok: bool
    code: str
    state: str
    token: str
    lease_until_ms: int
    spec: DeliverySpec | None
