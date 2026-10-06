"""Deterministic history writes use only the leased frozen plan and ACK time."""
from datetime import datetime, timedelta, timezone

from src.models.schemas import ChatRecord
from src.services.persistence.effects import EffectNeedsReview, EffectWriter
from src.services.persistence.history_commit.plans import timestamp_ms
from src.services.persistence.history_commit.session import SessionHistoryWriter
from src.services.persistence.history_commit.tasks import HistoryLease


class HistoryTargets:
    def __init__(self, redis_client):
        self.sessions = SessionHistoryWriter(redis_client)
        self.global_history = EffectWriter(redis_client)

    def apply(self, lease: HistoryLease) -> str:
        if not isinstance(lease, HistoryLease) or lease.task.state != "leased":
            raise EffectNeedsReview("history target requires a lease")
        data = lease.plan.data()
        effect_id = lease.plan.effect_id(lease.task.kind)
        if lease.task.kind == "session":
            return self.sessions.apply(effect_id, lease.plan.snapshot(), data["history"],
                                       max_history_turns=data["max_history_turns"])
        timestamp_ms(lease.delivered_at_ms)
        instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=lease.delivered_at_ms)
        offset = timezone(timedelta(seconds=data["utc_offset_seconds"]))
        record = ChatRecord(role="assistant", content=data["text"],
                            user_id=data["user_id"], group_id=data["group_id"],
                            time=instant.astimezone(offset).replace(tzinfo=None))
        return self.global_history.append_global_record(effect_id, record,
                                                        max_records=data["global_max_records"])
