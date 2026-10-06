"""Capture existing retention settings before send; consume only confirmed sent."""
from __future__ import annotations

from datetime import datetime
import logging

from src.core.config import get_settings
from .plans import build_plan
from .worker import EffectWorker

logger = logging.getLogger(__name__)


def production_plan(spec):
    if spec.kind == "reminder":
        return build_plan(spec)
    settings = get_settings()
    retention = max(settings.outbound_dedup_hours, settings.outbound_greeting_cooldown_hours)
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        raise ValueError("local timezone offset unavailable")
    return build_plan(spec, outbound_max_records=max(20, settings.outbound_dedup_max_records),
                      outbound_ttl=max(86400, retention * 7200),
                      history_max_records=max(1000, settings.global_memory_max_records),
                      utc_offset_seconds=int(offset.total_seconds()))


async def settle_confirmed(attempt):
    """Optional immediate pass uses the same leases as background discovery."""
    if not attempt.state_confirmed:
        return
    try:
        await EffectWorker(attempt.store.redis).run_action(attempt.spec.action_id)
    except Exception:
        logger.warning("Delivered action bookkeeping deferred to durable effect recovery")
