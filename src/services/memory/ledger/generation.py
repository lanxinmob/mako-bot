"""Carry the frozen memory view through model admission and SDK entry."""
from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
from .runtime import for_storage

generation_view = ContextVar('mako_memory_generation_view', default=None)


def memory_generation(fn):
    @wraps(fn)
    async def wrapped(self, request):
        from src.services.chat.generation.invocation import GenerationNotAdmitted
        view = request.memory_view or for_storage(self.storage, [request.user_id])
        if not view.current():
            raise GenerationNotAdmitted('memory version changed before generation')
        token = generation_view.set(view)
        try:
            return await fn(self, replace(request, memory_view=view))
        finally:
            generation_view.reset(token)
    return wrapped


async def provider_entry(sender):
    from src.services.chat.generation.invocation import GenerationNotAdmitted
    view = generation_view.get()
    result = await view.send(sender) if view else await sender()
    if result is False:
        raise GenerationNotAdmitted('memory version changed before provider entry')
    return result
