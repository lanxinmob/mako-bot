"""Private configuration and network are unavailable in replay subprocesses."""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch


def install_read_guards():
    import sys
    from pathlib import Path

    def guard(event, args):
        if event == "open" and isinstance(args[0], (str, bytes)):
            name = Path(str(args[0])).name
            if name == ".env" or name.startswith(".env."):
                raise RuntimeError("replay cannot read private environment files")
        if event in {"socket.connect", "socket.getaddrinfo"}:
            raise RuntimeError("replay network access denied")
    sys.addaudithook(guard)


@contextmanager
def environment(clock):
    import asyncio
    from src.core.config import Settings

    settings = Settings.model_construct(llm_required=False)
    async def inline_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch("src.core.config.get_settings", return_value=settings))
        # Import only after replacing configuration lookup.
        from src.services.chat import policy
        from src.services.chat.pipeline import workflow, execution, admission
        from src.services.delivery import dispatcher
        stack.enter_context(patch.object(policy, "get_settings", return_value=settings))
        stack.enter_context(patch.object(policy, "random", return_value=0.5))
        stack.enter_context(patch("asyncio.sleep", clock.sleep))
        stack.enter_context(patch("asyncio.to_thread", inline_thread))
        stack.enter_context(patch("time.monotonic", clock))
        stack.enter_context(patch("time.perf_counter", clock))
        stack.enter_context(patch("time.time", clock))
        stack.enter_context(patch.object(dispatcher, "outbound", dispatcher.OutboundDispatcher()))
        stack.enter_context(patch.object(dispatcher, "_configured", True))
        yield settings
