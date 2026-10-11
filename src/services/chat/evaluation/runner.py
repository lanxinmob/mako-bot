"""Drive the real participation/workflow/OneBot adapter with frozen annotations."""
import asyncio
from dataclasses import asdict
from types import SimpleNamespace as NS

from .clock import VirtualClock
from .dependencies import Dependencies, TARGET
from .isolation import environment
from .schema import eligible


class Replay:
    def __init__(self, case, clock, settings):
        from src.services.chat.pipeline.workflow import ChatWorkflow
        from src.services.chat.group.service import GroupConversationService
        self.case, self.clock = case, clock
        self.deps = Dependencies(clock, case, settings)
        self.workflow = ChatWorkflow(self.deps.services)
        self.decisions, self.candidates, self.tasks, self.errors = [], [], {}, []
        self.deps.candidates = self.candidates
        self.groups = {"g1": 1001, "g2": 1002}
        self.users = {"A": 101, "B": 102, "C": 103, "bot": 9001}
        self.bot_id = "9001"
        service = GroupConversationService(bot_user_id=self.bot_id, clock=clock)
        self.workflow.participation._bots[self.bot_id] = service
        self.service = service
        select, begin, refresh = service.select_decision, service.begin_candidate, service.revalidate_candidate
        def selected(snapshot):
            decision = select(snapshot)
            row = asdict(decision)
            row.update(at_ms=clock.ms, group=self.alias(decision.group_id))
            self.decisions.append(row)
            return decision
        def claimed(decision):
            candidate = begin(decision)
            if candidate:
                self.candidates.append(candidate)
            return candidate
        def refreshed(candidate, decision):
            result = refresh(candidate, decision)
            if result is not None:
                for index, old in enumerate(self.candidates):
                    if old is candidate:
                        self.candidates[index] = result
            return result
        service.select_decision, service.begin_candidate = selected, claimed
        service.revalidate_candidate = refreshed
        if case.get("rhythm_cooldown"):
            from src.services.chat.rhythm import RhythmState
            self.deps.rhythm._memory["group_1001"] = RhythmState(
                last_reply_at=clock(), last_sender_id=101, cooldown_until=clock() + 90)

    def alias(self, group_id):
        return next(k for k, v in self.groups.items() if str(v) == str(group_id))

    def ids(self, event):
        return self.groups[event["group"]], self.users[event.get("user", "A")]

    async def event(self, event):
        from src.services.chat.group.models import GroupEvent
        from src.services.chat.pipeline.models import ChatInput
        from src.services.chat.policy import ChatAddress
        from src.utils.message import NormalizedMessage
        op = event["op"]
        group = event.get("group", "g1")
        target = event.get("target_message_id", event.get("message_id"))
        key = group + "/" + target
        if op == "release_generation":
            self.deps.barriers.setdefault(key, asyncio.Event()).set()
            return
        if op == "cancel_task":
            if key in self.tasks:
                self.tasks[key].cancel()
            return
        numeric_group, user = self.ids(event)
        incoming_event = GroupEvent(
            str(numeric_group), event["message_id"], str(user), event["text"],
            timestamp=clock_timestamp(event["at_ms"]), is_bot=event.get("is_bot", False),
            direct_call=event.get("direct_call", False),
            mentions=tuple(str(self.users[x]) for x in event.get("mentions", [])),
            reply_to_message_id=event.get("reply_to_message_id"),
            reply_to_user_id=str(self.users[event["reply_to_user"]]) if event.get("reply_to_user") else None,
            kind=event.get("kind", "chat"))
        if op == "outbound_confirmed":
            lease = str(self.users[event["reply_to_user"]]) if event.get("reply_to_user") else None
            self.service.observe_outbound(incoming_event, lease_user_id=lease)
            return
        media = NormalizedMessage(plain_text=event["text"])
        self.workflow.participation.observe(self.bot_id, incoming_event, media)
        # Metadata-only observation by a higher-priority plugin must stay observation-only.
        if event.get("observe_only"):
            return
        incoming = ChatInput(ChatAddress("group", user, numeric_group), "synthetic",
            event["text"], media, event.get("direct_call", False) or "bot" in event.get("mentions", []),
            False, self.clock(), self.bot_id, event["message_id"], group_memory_observed=True)
        transport = self.deps.transport(group, event["message_id"], numeric_group, user, self.bot_id)
        async def run():
            token = TARGET.set(key)
            try:
                await self.workflow.handle(incoming, transport)
            finally:
                TARGET.reset(token)
        # A duplicate may be handled, but must not replace the original task handle.
        task = asyncio.create_task(run())
        self.tasks.setdefault(key, task)

    def checkpoint(self, point):
        group = point["group"]
        rows = [d for d in self.decisions if d["group"] == group]
        actual = rows[-1] if rows else {}
        problems = []
        for field in ("action", "target_message_id"):
            if actual.get(field) != point.get(field):
                problems.append(f"{field}: expected {point.get(field)!r}, got {actual.get(field)!r}")
        if point.get("action") == "wait":
            ms = actual.get("wait_seconds", 0) * 1000
            lo, hi = point["wait_range_ms"]
            if not lo - .001 <= ms <= hi + .001:
                problems.append(f"wait_ms: {ms:.3f} outside [{lo}, {hi}]")
        sends = self.deps.sends
        if "send_count" in point and len(sends) != point["send_count"]:
            problems.append(f"send_count: expected {point['send_count']}, got {len(sends)}")
        if "allowed_targets" in point:
            if any(row["target"].split("/")[1] not in point["allowed_targets"] for row in sends):
                problems.append("unexpected send target")
        if "send_category" in point and any(r["category"] != point["send_category"] for r in sends):
            problems.append("unexpected send category")
        key = group + "/" + str(point.get("target_message_id"))
        sent = [row for row in sends if row["target"] == key]
        state = sent[-1]["send_state"] if sent else "not_started"
        if "send_state" in point and state != point["send_state"]:
            problems.append(f"send_state: expected {point['send_state']}, got {state}")
        if "candidate_current" in point:
            candidates = [c for c in self.candidates if self.alias(c.group_id) == group
                          and c.target_message_id == point["target_message_id"]]
            current = bool(candidates and self.service.candidate_is_current(candidates[-1]))
            if current != point["candidate_current"]:
                problems.append(f"candidate_current: {current}")
        self.errors.extend(f"seq {point['seq']}: {p}" for p in problems)

    def metrics(self):
        counts = {kind: {"numerator": 0, "denominator": 0} for kind in
                  ("forbid_reply", "require_reply", "invalidated_candidate")}
        for op in self.case["opportunities"]:
            if not eligible(op):
                continue
            counter = counts[op["kind"]]
            counter["denominator"] += 1
            key = op["group"] + "/" + op["target_message_id"]
            sends = [r for r in self.deps.sends if r["category"] == "chat"]
            if op["kind"] == "forbid_reply":
                bad = any(r["target"].split("/")[0] == op["group"]
                          and op["start_ms"] <= r["at_ms"] <= op["end_ms"] for r in sends)
            elif op["kind"] == "require_reply":
                bad = not any(r["target"] == key and r["confirmed_at_ms"] is not None
                              and op["start_ms"] <= r["confirmed_at_ms"] <= op["end_ms"] for r in sends)
            else:
                ref = op["candidate_of"]
                rows = [c for c in self.candidates if self.alias(c.group_id) == ref["group"]
                        and c.target_message_id == ref["message_id"]]
                if len(rows) < ref["ordinal"]:
                    self.errors.append(f"{op['id']}: expected candidate was not created")
                bad = any(r["target"] == key and r.get("candidate_ordinal") == ref["ordinal"]
                          and op["start_ms"] <= r["at_ms"] <= op["end_ms"]
                          for r in sends)
            counter["numerator"] += int(bad)
        return counts

    async def run(self):
        before = asyncio.all_tasks()
        checkpoints = self.case["checkpoints"]
        times = sorted({r["at_ms"] for r in self.case["events"] + checkpoints}
                       | {self.case["end_at_ms"]})
        incomplete = []
        try:
            if self.case.get("queue_until_ms"):
                from src.services.delivery.dispatcher import dispatch
                async def occupying_send():
                    await self.clock.sleep(self.case["queue_until_ms"] / 1000)
                    return True
                asyncio.create_task(dispatch("group", 1001, occupying_send, category="command"))
                await self.clock.settle()
            for ms in times:
                await self.clock.advance(ms, inclusive=False)
                for event in sorted((e for e in self.case["events"] if e["at_ms"] == ms),
                                    key=lambda e: e["seq"]):
                    await self.event(event)
                await self.clock.settle()
                await self.clock.advance(ms)
                await self.clock.settle()
                for point in sorted((p for p in checkpoints if p["at_ms"] == ms),
                                    key=lambda p: p["seq"]):
                    self.checkpoint(point)
            for key, task in self.tasks.items():
                if not task.done():
                    incomplete.append(key)
                elif not task.cancelled() and task.exception():
                    incomplete.append(key + ": " + type(task.exception()).__name__)
            if incomplete:
                self.errors.append("unfinished: " + ", ".join(incomplete))
            metrics = self.metrics()
            chat_targets = [r["target"] for r in self.deps.sends if r["category"] == "chat"]
            duplicate = sum(max(0, chat_targets.count(k) - 1) for k in set(chat_targets))
            return dict(case_id=self.case["case_id"], split=self.case["split"],
                hard=self.case["hard"], category=self.case["category"], completed=not incomplete,
                passed=not self.errors, errors=self.errors, metrics=metrics, duplicate_sends=duplicate,
                decisions=self.decisions, sends=self.deps.sends, generations=self.deps.generations,
                notices=self.deps.notices, source="replay")
        finally:
            remaining = asyncio.all_tasks() - before
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)


def clock_timestamp(ms):
    return 1_800_000_000 + ms / 1000


async def replay(case):
    clock = VirtualClock()
    with environment(clock) as settings:
        return await Replay(case, clock, settings).run()
