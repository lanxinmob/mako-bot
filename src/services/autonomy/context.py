"""Shared dependencies for autonomous planning and delivery."""
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class AutonomyContext:
    settings: Any
    storage: Any
    governance: Any
    outbound_dedup: Any
    runtime_context: Any
    repository: Any
    policy: Any
    clock: Callable[[], float]
    render_message: Callable[[str], Any]
