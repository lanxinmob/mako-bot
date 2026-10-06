"""Generation phase of the chat pipeline.

``ChatEngine`` is transport agnostic: it receives a fully enriched request and
returns a reply plus the history that should be committed after delivery.  The
NoneBot adapter owns sending, so a failed send is never recorded as successful.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Callable, List, Optional

from nonebot.log import logger

from src.core.config import get_settings
from src.models.schemas import ChatRecord
from src.services.chat.policy import ReplyPlan
from src.services.chat.policy import select_reply_plan
from src.services.chat.policy import truncate_reply
from .generation.provider import call_recorded, summarize_costs
from src.services.memory.mako_context import MakoRuntimeContext
from src.services.retrieval.metrics import search_metrics
from src.services.persistence import StorageService


from .models import ChatRequest, ChatReply
from .messages import MessageBuilder, knowledge_visible_to_user
from . import history, facts

class ChatEngine:
    def __init__(
        self,
        *,
        storage: Optional[StorageService] = None,
        knowledge_search: Optional[Callable[[str], List[str]]] = None,
        runtime_context: Optional[MakoRuntimeContext] = None,
    ) -> None:
        self.storage = storage or StorageService()
        self.knowledge_search = knowledge_search or (lambda _query: [])
        self.runtime_context = runtime_context or MakoRuntimeContext(self.storage)
        self.settings = get_settings()


    async def generate(self, request: ChatRequest) -> ChatReply:
        # Profile, Redis and embedding access are synchronous integrations.
        # Keep them off NoneBot's event loop so one cold model load does not
        # stall every matcher in the process.
        plan = request.reply_plan or select_reply_plan(
            request.user_text,
            message_type=request.message_type,
            directed=request.directed,
        )
        outcome = request.search_outcome
        if outcome.required and not outcome.success:
            text = self._search_failure_reply(outcome)
            search_metrics.record_answer(
                factual_mode=False,
                realtime=outcome.realtime,
                cited=False,
                consistent=True,
            )
            return ChatReply(
                text=text,
                history=self._next_history(request, text),
                model="search-fail-closed",
                factual_consistent=True,
                cited=False,
                fail_closed=True,
                cost_status="not_required",
            )
        messages = await asyncio.to_thread(self._build_messages, request, plan)
        max_tokens = max(plan.max_tokens, 1200) if outcome.factual_mode else plan.max_tokens
        cost_reports = []
        text, model = await self._call_llm(messages, max_tokens=max_tokens,
            user_id=request.user_id, phase="reply", cost_reports=cost_reports)
        text = truncate_reply(
            text,
            max(plan.max_chars, 900) if outcome.factual_mode else plan.max_chars,
        )
        consistent = True
        cited = False
        answer_fail_closed = False
        if outcome.factual_mode:
            text = self._ensure_source_links(text, outcome)
            consistent = await self._validate_factual_answer(request.user_text, text, outcome,
                user_id=request.user_id, cost_reports=cost_reports)
            if not consistent:
                text = self._verified_fallback_answer(outcome)
                consistent = bool(text)
            cited = any(source.url in text for source in outcome.sources)
            if not consistent or (outcome.realtime and not cited):
                text = self._search_failure_reply(
                    replace(
                        outcome,
                        success=False,
                        failure_reason="事实回答未通过证据一致性或引用检查",
                    )
                )
                consistent = True
                cited = False
                answer_fail_closed = True
            search_metrics.record_answer(
                factual_mode=True,
                realtime=outcome.realtime,
                cited=cited,
                consistent=consistent,
            )
        if request.message_type == "group" and not request.directed and not outcome.factual_mode:
            limit = min(plan.max_chars, max(1, self.settings.group_reply_max_chars_undirected))
            if len(text) > limit:
                text = truncate_reply(text, limit)
        return ChatReply(
            text=text,
            history=self._next_history(request, text),
            model=model,
            factual_consistent=consistent,
            cited=cited,
            fail_closed=answer_fail_closed,
            cost_status=summarize_costs(cost_reports),
        )


    def commit(self, request: ChatRequest, reply: ChatReply) -> None:
        """Commit state only after the transport has delivered the reply."""

        self.storage.save_history(request.session_id, reply.history)
        self.storage.append_global_record(
            ChatRecord(
                role="assistant",
                content=reply.text,
                user_id=request.user_id,
                group_id=request.group_id,
                time=datetime.now(),
            )
        )


    async def _call_llm(self, messages: List[dict], *, max_tokens: int = 4096,
                        user_id: int, phase: str, cost_reports: list) -> tuple[str, str]:
        try:
            text, model, status = await call_recorded(self.storage, self.settings, messages,
                user_id=user_id, phase=phase, max_tokens=max_tokens)
        except BaseException:
            cost_reports.append("unknown")
            raise
        cost_reports.append(status)
        return text, model


    def _build_messages(self, request: ChatRequest, plan: Optional[ReplyPlan] = None) -> List[dict]:
        builder = MessageBuilder(self.storage, self.knowledge_search, self.runtime_context)
        return builder.build(request, plan)

    async def _validate_factual_answer(self, user_text, answer, outcome, *, user_id, cost_reports):
        async def check(messages, *, max_tokens):
            return await self._call_llm(messages, max_tokens=max_tokens, user_id=user_id,
                                        phase="fact_check", cost_reports=cost_reports)
        return await facts.validate_factual_answer(check, user_text, answer, outcome)

    _next_history = staticmethod(history.next_history)
    _strip_legacy_enrichment = staticmethod(history.strip_legacy_enrichment)
    _history_for_prompt = staticmethod(history.history_for_prompt)
    _search_failure_reply = staticmethod(facts.search_failure_reply)
    _ensure_source_links = staticmethod(facts.ensure_source_links)
    _verified_fallback_answer = staticmethod(facts.verified_fallback_answer)
    _knowledge_visible_to_user = staticmethod(knowledge_visible_to_user)
