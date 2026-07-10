"""Best-effort audit boundary for the chat pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from nonebot.log import logger

from src.services.storage import StorageService


class ChatAudit:
    def __init__(self, storage: Optional[StorageService] = None) -> None:
        self.storage = storage or StorageService()

    def progress(self, event_type: str, summary: str, payload: Dict[str, Any]) -> None:
        self._append(
            "append_progress_event",
            {
                "type": "AutonomyProgressEvent",
                "source": "chat",
                "event_type": event_type,
                "summary": summary,
                "payload": payload,
                "created_at": datetime.now().isoformat(),
            },
        )

    def thought(self, trace_type: str, summary: str, payload: Dict[str, Any]) -> None:
        self._append(
            "append_thought_trace",
            {
                "type": "ThoughtTrace",
                "source": "chat",
                "trace_type": trace_type,
                "summary": summary,
                "payload": payload,
                "created_at": datetime.now().isoformat(),
            },
        )

    def _append(self, method_name: str, payload: Dict[str, Any]) -> None:
        method = getattr(self.storage, method_name, None)
        if not callable(method):
            logger.warning(f"StorageService.{method_name} is unavailable; audit event skipped.")
            return
        try:
            method(payload)
        except Exception as exc:
            logger.warning(f"聊天审计写入失败({method_name}): {exc}")
