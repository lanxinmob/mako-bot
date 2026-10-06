"""Bounded, in-memory shuffle bags for successive discovery requests."""
from collections import OrderedDict
from random import SystemRandom
from threading import Lock


class ChoiceCycle:
    def __init__(self, capacity: int = 256):
        self.capacity = capacity
        self._users = OrderedDict()
        self._random = SystemRandom()
        self._lock = Lock()

    def choose(self, user_id: int, identities: tuple[str, ...]) -> str:
        pool = tuple(sorted(set(identities)))
        if not pool:
            raise ValueError("empty discovery pool")
        with self._lock:
            old_pool, remaining, previous = self._users.get(user_id, ((), [], None))
            if old_pool != pool or not remaining:
                remaining = list(pool)
                self._random.shuffle(remaining)
                if len(remaining) > 1 and remaining[-1] == previous:
                    remaining[0], remaining[-1] = remaining[-1], remaining[0]
            selected = remaining.pop()
            self._users[user_id] = (pool, remaining, selected)
            self._users.move_to_end(user_id)
            while len(self._users) > self.capacity:
                self._users.popitem(last=False)
            return selected
