"""Bounded discovery and single-evidence repair, without granting a lease."""
from ..effects import EffectNeedsReview, EffectUnavailable
from .costs import GenerationCosts, decode_cost
from .index_scripts import COST_DUE_KEY, DUE, REPAIR, SNAPSHOT, REMOVE_WRONG_TYPE
from .models import valid_id


class GenerationCostIndex:
    def __init__(self, redis_client):
        self.redis = redis_client

    def repair_current(self, attempt_id: str | bytes) -> str:
        """Read binary evidence, then fence repair against a changed source."""
        if not isinstance(attempt_id, (str, bytes)):
            raise ValueError("invalid index member")
        prefix = b"mako:generation:v1:" if isinstance(attempt_id, bytes) else "mako:generation:v1:"
        key = prefix + attempt_id

        def run():
            snapshot = self.redis.execute_command("EVAL", SNAPSHOT, 1, key, NEVER_DECODE=True)
            kind = snapshot[0].decode() if isinstance(snapshot[0], bytes) else snapshot[0]
            if kind in {"none", "string"}:
                return self.repair(attempt_id, snapshot[1] if kind == "string" else None)
            result = self.redis.eval(REMOVE_WRONG_TYPE, 2, key, COST_DUE_KEY, attempt_id, kind)
            result = result.decode() if isinstance(result, bytes) else result
            if result not in {"changed", "removed_invalid"}:
                raise EffectNeedsReview("invalid index quarantine response")
            return result

        return GenerationCosts(self.redis)._read(run)

    def due_ids(self, limit: int = 3) -> list[str | bytes]:
        """Read at most 10 members using Redis time; callers must still claim.

        Invalid members are returned unchanged for explicit cleanup by the next
        module, never silently filtered into a misleading empty page.
        """
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("cost discovery limit must be between 1 and 10")

        def read():
            # Keep corrupt UTF-8 members inspectable even on decoding clients.
            members = self.redis.execute_command(
                "EVAL", DUE, 1, COST_DUE_KEY, limit, NEVER_DECODE=True)
            if not isinstance(members, list) or len(members) > limit:
                raise ValueError("invalid cost discovery response")
            decoded = []
            for member in members:
                if not isinstance(member, (str, bytes)):
                    raise ValueError("invalid cost discovery member")
                if isinstance(member, bytes):
                    try:
                        member = member.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
                decoded.append(member)
            return decoded

        return GenerationCosts(self.redis)._read(read)

    def repair(self, attempt_id: str | bytes, expected_raw: str | bytes | None) -> str:
        """CAS one observed record: repaired/changed; failures raise.

        Pass the exact GET bytes (None for observed absence), not reserialized
        JSON. Malformed evidence is preserved; only its discovery is removed.
        Valid calling evidence older than five minutes becomes unknown, keeping
        its original authorization token for a late completion, never a retry.
        Returns repaired, removed_missing, removed_invalid, or changed. No SCAN,
        model call, target write, generation deletion, or receipt access occurs.
        """
        if not isinstance(attempt_id, (str, bytes)):
            raise ValueError("invalid index member")
        if expected_raw is not None and not isinstance(expected_raw, (str, bytes)):
            raise ValueError("expected exact GET bytes or None")
        prefix = b"mako:generation:v1:" if isinstance(attempt_id, bytes) else "mako:generation:v1:"
        key = prefix + attempt_id

        def run():
            result_kind = "removed_missing" if expected_raw is None else "repaired"
            if expected_raw is not None:
                try:
                    raw = expected_raw.decode() if isinstance(expected_raw, bytes) else expected_raw
                    identity = attempt_id.decode() if isinstance(attempt_id, bytes) else attempt_id
                    if not valid_id(identity):
                        raise ValueError("invalid index identity")
                    decode_cost(raw, identity)
                except (ValueError, TypeError, KeyError, OverflowError):
                    result_kind = "removed_invalid"
            result = self.redis.eval(REPAIR, 2, key, COST_DUE_KEY,
                                     "missing" if expected_raw is None else "present",
                                     expected_raw or "", attempt_id, result_kind)
            result = result.decode() if isinstance(result, bytes) else result
            if result == "index_unconfirmed":
                raise EffectUnavailable("generation index update unconfirmed")
            if result not in {"repaired", "changed", "removed_missing", "removed_invalid"}:
                raise EffectNeedsReview("generation index repair requires review")
            return result

        return GenerationCosts(self.redis)._read(run)
