"""Production provider selection with durable per-invocation accounting."""
import asyncio

from src.services.integrations.llm import (
    get_deepseek_client, get_deepseek_model, get_openai_client, has_deepseek, has_openai,
)
from src.services.persistence.generation.store import GenerationStore
from src.services.persistence.generation.costs import GenerationCosts
from .invocation import GenerationNotAdmitted, RecordedInvocation
from .cost_worker import GenerationCostWorker


def summarize_costs(statuses):
    if not statuses:
        return "unknown"
    for value in ("unknown", "needs_review", "pending"):
        if value in statuses:
            return value
    return "complete" if all(value in {"complete", "not_required"} for value in statuses) else "unknown"


async def call_recorded(storage, settings, messages, *, user_id, phase, max_tokens):
    if has_deepseek():
        model, factory = get_deepseek_model(), get_deepseek_client
    elif has_openai():
        model, factory = "gpt-4o-mini", get_openai_client
    else:
        return "茉子大人现在有点迷糊，先把 API 配好再来聊天吧。", "fallback", "not_required"
    try:
        client = await asyncio.to_thread(lambda: storage.redis)
    except Exception as exc:
        raise GenerationNotAdmitted("generation storage unavailable") from exc
    invocation = RecordedInvocation(GenerationStore(client),
        input_rate=settings.llm_cost_per_1k_chars_input,
        output_rate=settings.llm_cost_per_1k_chars_output)

    async def provider(frozen_messages):
        # SDK-level retries would repeat an unconfirmed billable request.
        api = factory().with_options(max_retries=0)
        response = await asyncio.wait_for(api.chat.completions.create(
            model=model, messages=frozen_messages, temperature=0.1, max_tokens=max_tokens), timeout=40.0)
        return response.choices[0].message.content or ""

    result = await invocation.call(provider, messages, user_id=user_id, phase=phase,
                                   model=model, max_output_chars=max_tokens * 4)
    status = "unknown"
    if result.cost_status == "recorded":
        try:
            outcome = await GenerationCostWorker(client).run(result.attempt_id)
            status = ("complete" if outcome in {"applied", "already_applied"} else
                      "needs_review" if outcome in {"conflict", "needs_review"} else "pending")
            if outcome == "not_claimed":
                snapshot = await asyncio.to_thread(GenerationCosts(client).inspect, result.attempt_id)
                if snapshot is not None and snapshot.state in {"complete", "needs_review"}:
                    status = snapshot.state
        except Exception:
            status = "pending"
    return result.text.strip(), model, status
