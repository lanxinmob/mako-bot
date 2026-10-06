"""Read-only, bounded generation evidence views without prompts or tokens."""
from dataclasses import dataclass
import re

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.services.delivery.state.pagination import parse_cursor
from ..effects import EffectNeedsReview, EffectUnavailable
from .models import decode_attempt
from .costs import decode_cost
from .store import GenerationStore


@dataclass(frozen=True)
class GenerationEntry:
    attempt_id: str
    state: str
    cost_state: str = ""
    phase: str = ""
    cost_day: str = ""
    amount: float | None = None


@dataclass(frozen=True)
class GenerationPage:
    entries: tuple[GenerationEntry, ...]
    next_cursor: str | None


def inspect_generation(client, attempt_id):
    key = GenerationStore.key(attempt_id)
    if client is None:
        raise EffectUnavailable("generation evidence requires Redis")
    try:
        raw = client.get(key)
        if raw is None:
            return GenerationEntry(attempt_id, "missing")
        raw = raw.decode() if isinstance(raw, bytes) else raw
        item, spec = decode_attempt(raw, attempt_id)
        state = item.get("state")
        if state == "completed":
            cost = decode_cost(raw, attempt_id)
            return GenerationEntry(attempt_id, state, cost.state, spec.phase, spec.cost_day, cost.amount)
        return GenerationEntry(attempt_id, state, item["cost_state"], spec.phase, spec.cost_day)
    except (RedisConnectionError, RedisTimeoutError, ConnectionError, TimeoutError) as exc:
        raise EffectUnavailable("generation evidence unavailable") from exc
    except Exception as exc:
        raise EffectNeedsReview("generation evidence requires review") from exc


def list_generations(client, cursor="0:0"):
    scan_cursor, offset = parse_cursor(cursor, 10)
    if client is None:
        raise EffectUnavailable("generation listing requires Redis")
    try:
        following, keys = client.scan(cursor=scan_cursor, match="mako:generation:v1:*", count=10)
        keys = sorted(key.decode() if isinstance(key, bytes) else key for key in keys)
        following = int(following)
    except Exception as exc:
        raise EffectUnavailable("generation listing unavailable") from exc
    end, entries = min(len(keys), offset + 10), []
    for key in keys[offset:end]:
        match = re.fullmatch(r"mako:generation:v1:([0-9a-f]{64})", key)
        if match is None:
            continue
        try:
            entries.append(inspect_generation(client, match[1]))
        except EffectNeedsReview:
            entries.append(GenerationEntry(match[1], "invalid"))
    next_cursor = (f"{scan_cursor}:{end}" if end < len(keys)
                   else f"{following}:0" if following else None)
    return GenerationPage(tuple(entries), next_cursor)
