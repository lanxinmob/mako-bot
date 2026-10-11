"""One active event loop owns control commits and actual transport entry."""
import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from weakref import WeakKeyDictionary

from src.services.persistence.ledger import LedgerRepository, LedgerUnavailable

_gates = WeakKeyDictionary()
_epochs = OrderedDict()


@asynccontextmanager
async def critical():
    loop = asyncio.get_running_loop()
    lock = _gates.setdefault(loop, asyncio.Lock())
    async with lock:
        yield


async def confirmed_thread(fn, *args):
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    canceled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            canceled = True
    result = task.result()
    if canceled:
        raise asyncio.CancelledError()
    return result


def repository(storage):
    backend = getattr(storage, 'backend', None)
    if backend is None:
        return None
    from src.services.persistence.backends.redis import StorageBackend
    if not isinstance(backend, StorageBackend):
        return None  # Explicit lightweight dependency doubles have no production backend.
    return LedgerRepository(storage.backend, allow_memory=getattr(storage.backend, 'ledger_test_memory', False))


@dataclass(frozen=True)
class MemoryView:
    repo: object = field(compare=False, repr=False)
    users: tuple = ()
    states: dict = field(default_factory=dict)
    available: bool = True

    @property
    def controlled(self):
        return not self.available or any(s['controlled'] for s in self.states.values())

    @property
    def stamp(self):
        return tuple((u, s['revision']) for u, s in sorted(self.states.items()))

    @property
    def cutoff_ns(self):
        return max((int(s['cutoff_ns']) for s in self.states.values()), default=0)

    def current(self):
        if not self.available:
            return True  # This request received current input only, no personal sources.
        latest = snapshot(self.repo, self.users)
        return latest.available and latest.stamp == self.stamp

    def group_context(self, snapshot_value):
        if not self.available:
            return ''
        if not self.controlled:
            return snapshot_value.render()
        events = tuple(e for e in snapshot_value.events if e.received_ns > self.cutoff_ns)
        return replace(snapshot_value, events=events).render()

    def history(self, bot_id, session_id, ordinary):
        if not self.available:
            return []
        if not self.controlled:
            return ordinary
        key = (bot_id, session_id, self.stamp)
        return list(_epochs.get(key, []))

    def record(self, bot_id, session_id, history):
        if not self.controlled or not self.available or not self.current():
            return
        key = (bot_id, session_id, self.stamp)
        _epochs[key] = list(history[-40:])
        _epochs.move_to_end(key)
        while len(_epochs) > 2048:
            _epochs.popitem(last=False)

    async def send(self, sender):
        async with critical():
            if not self.current():
                return False
        # No await between releasing the common gate and entering sender.
        # Control/background writes can run only after acquiring this same gate.
        return await sender()


def snapshot(repo, users):
    users = tuple(sorted(set(int(u) for u in users if u is not None)))
    if repo is None:
        return MemoryView(None, users)
    try:
        if not users:
            repo.state(0)  # Confirm persistence even for an empty participant set.
        return MemoryView(repo, users, {u: repo.state(u) for u in users})
    except LedgerUnavailable:
        return MemoryView(repo, users, available=False)


def for_storage(storage, users):
    return snapshot(repository(storage), users)


def versioned(storage, versions, users=()):
    view = for_storage(storage, [*users, *(int(u) for u in (versions or {}))])
    if not versions:
        return view if not view.controlled else None
    expected = {int(u): v for u, v in versions.items()}
    if any(u not in expected or expected[u] != s['revision'] for u, s in view.states.items()):
        return None
    return view if view.available else None
