"""Synthetic generation/storage doubles around the real workflow and adapter."""
import asyncio
import contextvars
import importlib.util
import hashlib
from pathlib import Path
from types import SimpleNamespace as NS

TARGET = contextvars.ContextVar("replay_target")


class Dependencies:
    def __init__(self, clock, case, settings):
        from src.services.chat.rhythm import ChatRhythmService
        self.clock, self.case, self.settings = clock, case, settings
        self.generations, self.sends, self.notices = [], [], []
        self.barriers = {}
        self.storage = NS(redis=None, get_plugin_history=lambda *_: [])
        self.rhythm = ChatRhythmService(self.storage, clock=clock, settings=settings)
        self.services = NS(
            settings=settings, storage=self.storage,
            audit=NS(progress=lambda *_: None, thought=lambda *_: None),
            governance=NS(can_chat=lambda *_: NS(allowed=not case.get("deny_access", False), reason="synthetic"),
                          estimate_llm_cost=lambda *_: 0, can_consume_cost=lambda *_: NS(allowed=True)),
            relationship=NS(absorb_user_message=lambda *_: None),
            chat_rhythm=self.rhythm, chat_engine=NS(generate=self.generate),
            context_builder=NS(build=self.context), make_tools=self.tools,
            history_delivery=NS(read=self.read, send=self.history_send, consume=self.consume),
        )

    async def generate(self, request):
        from src.services.chat.models import ChatReply
        key = TARGET.get()
        self.generations.append({"target": key, "at_ms": self.clock.ms, "context": request.llm_text})
        config = self.case.get("generation", {}).get(key, {})
        if config.get("blocked"):
            await self.barriers.setdefault(key, asyncio.Event()).wait()
        await self.clock.sleep(config.get("delay_ms", 10) / 1000)
        return ChatReply("合成回复", [], "synthetic", cost_status="simulated")

    async def context(self, **kw):
        from src.services.retrieval.models import SearchOutcome
        return NS(llm_text=kw["user_text"], search_outcome=SearchOutcome(),
                  image_context="", search_context="", image_inputs=[])

    def tools(self):
        from src.services.tools.models import ToolExecutionResult
        async def run(decisions, *_args, **_kwargs):
            return ToolExecutionResult(fact_lines=["合成工具结果"] if decisions else [])
        return NS(run=run, cleanup_temp_files=lambda: None)

    async def read(self, session):
        from src.services.persistence.history_commit.snapshot import HistorySnapshot
        return HistorySnapshot(session, "missing", None)

    async def history_send(self, incoming, transport, request, reply):
        from src.services.chat.history_delivery.runtime import HistoryReceipt
        ack = False
        async def before_send():
            return True  # Synthetic persisted plan admission; adapter still checks its real guard.
        def on_ack():
            nonlocal ack
            ack = True
        await transport.reply_recorded(reply.text, before_send=before_send, on_ack=on_ack)
        return HistoryReceipt("a" * 64, ack, ack)

    async def consume(self, _):
        return {"history_session": "complete", "history_global": "complete"}

    def transport(self, group, message, numeric_group, user, bot_id):
        from nonebot.adapters.onebot.v11 import GroupMessageEvent
        path = Path(__file__).resolve().parents[3] / "plugins/chat/delivery.py"
        spec = importlib.util.spec_from_file_location("replay_onebot_delivery", path)
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        # Plugin history is an isolated persistence dependency, not a delivery guard.
        adapter.observe_plugin_output = lambda *_: None
        key = group + "/" + message
        owner = self
        event = GroupMessageEvent.model_validate(dict(
            time=0, self_id=int(bot_id), post_type="message", sub_type="normal",
            message_type="group", message_id=int(hashlib.sha256(message.encode()).hexdigest()[:8], 16),
            user_id=user, group_id=numeric_group, message=[], raw_message="", font=0,
            sender=dict(user_id=user, nickname="synthetic", role="member")))
        class Transport:
            guard = None
            category = "chat"
            on_sent = None
            cancel_candidate = staticmethod(lambda: None)

            async def reply(self, text):
                return await self.reply_recorded(text, before_send=None, on_ack=None)

            async def reply_recorded(self, text, *, before_send, on_ack):
                async def send(_payload):
                    from src.services.chat.group.models import ChatCandidate
                    # Read the exact token captured by the real guard, including
                    # refreshed ownership. This is observation, not a new guard.
                    token = next((cell.cell_contents for cell in getattr(self.guard, '__closure__', ()) or ()
                                  if isinstance(cell.cell_contents, ChatCandidate)), None)
                    candidates = [c for c in owner.candidates if token is not None
                                  and c.group_id == token.group_id and c.target_message_id == token.target_message_id]
                    ordinal = next((i + 1 for i, c in enumerate(candidates) if c is token), None)
                    row = {"target": key, "category": self.category, "at_ms": owner.clock.ms,
                           "send_state": "in_flight", "confirmed_at_ms": None, "candidate_ordinal": ordinal}
                    owner.sends.append(row)
                    config = owner.case.get("transport", {}).get(key, {})
                    await owner.clock.sleep(config.get("delay_ms", 10) / 1000)
                    mode = config.get("result", "ack")
                    row["send_state"] = "confirmed" if mode == "ack" else (
                        "failed" if mode == "explicit_failure" else "unknown")
                    if mode == "ack":
                        row["confirmed_at_ms"] = owner.clock.ms
                        return {"message_id": "synthetic-" + str(len(owner.sends))}
                    return False
                return await adapter.send_reply(NS(send=send), event,
                    NS(self_id=int(bot_id), get_group_member_list=owner.members),
                    text, guard=self.guard, category=self.category, on_sent=self.on_sent,
                    before_send=before_send, on_ack=on_ack)

            async def notice(self, _text):
                owner.notices.append({"target": key, "at_ms": owner.clock.ms})
                return False

            async def reminder(self, *_):
                return False

            async def extra(self, *_):
                return False
        return Transport()

    async def members(self, **_):
        return []
