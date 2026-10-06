"""NoneBot entrypoint for the ordered chat request pipeline.

Protocol helpers live beside this module; domain and integration work lives in
``src.services``.  This file intentionally reads like a request phase table:
observe -> access -> route -> enrich -> generate -> present -> commit.
"""

from __future__ import annotations



from src.core.config import get_settings
from src.services.delivery.audit import ChatAudit
from src.services.chat.context import ChatContextBuilder
from src.services.chat.engine import ChatEngine
from src.services.chat.rhythm import ChatRhythmService
from src.services.governance.service import GovernanceService
from src.services.memory.relationship import RelationshipService
from src.services.persistence import StorageService
from src.services.tools.executor import ToolExecutor


settings = get_settings()
storage = StorageService()
audit = ChatAudit(storage)
context_builder = ChatContextBuilder()
relationship = RelationshipService(storage=storage)
governance = GovernanceService(storage=storage)
chat_rhythm = ChatRhythmService(storage=storage)


def _search_long_term_memory(query: str) -> list[str]:
    """Lazy-load the embedding stack only when a reply actually needs it."""

    from src.plugins.vector_db import search_db

    # Fetch extra candidates because private note vectors belonging to other
    # users are filtered by ChatEngine before prompt construction.
    return search_db(query, top_k=12)

chat_engine = ChatEngine(storage=storage, knowledge_search=_search_long_term_memory)

from src.services.chat.pipeline.models import ChatServices
from src.services.chat.pipeline.workflow import ChatWorkflow

services = ChatServices(settings, storage, audit, context_builder, relationship, governance, chat_rhythm, chat_engine, ToolExecutor)
workflow = ChatWorkflow(services)

from src.services.delivery.observation import set_group_observer

set_group_observer(workflow.participation.observe_output)
