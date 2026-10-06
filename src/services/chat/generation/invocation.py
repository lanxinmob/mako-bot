"""Admit a single model call only after durable attempt creation is confirmed."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import secrets

from src.services.persistence.generation.models import GenerationSpec, nonnegative
from src.services.persistence.generation.store import GenerationStore

logger = logging.getLogger(__name__)


class GenerationNotAdmitted(RuntimeError):
    """Do not invoke a provider when the attempt was not durably admitted."""


@dataclass(frozen=True)
class GenerationResult:
    text: str
    attempt_id: str
    cost_status: str


class RecordedInvocation:
    def __init__(self, store: GenerationStore, *, input_rate, output_rate, clock=datetime.now):
        self.store = store
        self.input_rate = nonnegative(input_rate)
        self.output_rate = nonnegative(output_rate)
        self.clock = clock

    async def _unknown(self, spec, token):
        try:
            await asyncio.to_thread(self.store.mark_unknown, spec, token)
        except Exception:
            # Failure leaves the persisted calling record; it cannot be reclaimed.
            logger.warning("Model attempt outcome remains unresolved")

    async def call(self, provider, messages, *, user_id, phase, model, max_output_chars):
        """Provider returns raw text and must itself disable automatic retries."""
        if type(max_output_chars) is not int or max_output_chars < 0:
            raise ValueError("invalid output estimate")
        # Copy before awaiting admission: caller mutation cannot alter this attempt.
        encoded = json.dumps(messages, ensure_ascii=False, sort_keys=True, allow_nan=False)
        frozen_messages = json.loads(encoded)
        if not isinstance(frozen_messages, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("content"), str)
            for item in frozen_messages
        ):
            raise ValueError("generation messages must contain text content")
        input_chars = sum(len(item["content"]) for item in frozen_messages)
        spec = GenerationSpec(
            secrets.token_hex(32), user_id, phase, model,
            hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            self.clock().strftime("%Y%m%d"), self.input_rate, self.output_rate,
            input_chars / 1000 * self.input_rate + max_output_chars / 1000 * self.output_rate,
        )
        try:
            token = await asyncio.to_thread(self.store.start, spec)
        except Exception as exc:
            raise GenerationNotAdmitted("generation persistence not confirmed") from exc
        if token is None:
            raise GenerationNotAdmitted("generation attempt already exists")
        try:
            text = await provider(frozen_messages)
            if not isinstance(text, str):
                raise TypeError("model returned non-text result")
        except asyncio.CancelledError:
            await self._unknown(spec, token)
            raise
        except Exception:
            await self._unknown(spec, token)
            raise
        # Count raw output before truncation, citation repair or fallback replacement.
        amount = input_chars / 1000 * spec.input_rate + len(text) / 1000 * spec.output_rate
        status = "unknown"
        try:
            result = await asyncio.to_thread(self.store.complete, spec, token, amount)
            if result == "completed":
                status = "recorded"
        except Exception:
            logger.warning("Model finished; cost evidence completion not confirmed")
        return GenerationResult(text, spec.attempt_id, status)
