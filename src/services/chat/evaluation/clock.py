"""A virtual receive clock, scoped to one offline event loop."""
import asyncio
import heapq
import itertools


class VirtualClock:
    def __init__(self):
        self.now = 1000.0
        self.waiters = []
        self.sequence = itertools.count()
        self.yield_once = asyncio.sleep

    def __call__(self):
        return self.now

    @property
    def ms(self):
        return round((self.now - 1000.0) * 1000)

    async def sleep(self, seconds=0, result=None):
        if seconds <= 0:
            await self.yield_once(0)
            return result
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self.waiters, (self.now + seconds, next(self.sequence), future))
        await future
        return result

    def release(self):
        while self.waiters and self.waiters[0][0] <= self.now + 1e-9:
            _, _, future = heapq.heappop(self.waiters)
            if not future.done():
                future.set_result(None)

    async def settle(self):
        loop = asyncio.get_running_loop()
        for _ in range(512):
            self.release()
            await self.yield_once(0)
            if not loop._ready:
                return
        raise RuntimeError("virtual tasks did not reach a wait or barrier")

    def next_due(self):
        while self.waiters and self.waiters[0][2].done():
            heapq.heappop(self.waiters)
        times = [self.waiters[0][0]] if self.waiters else []
        times.extend(h.when() for h in asyncio.get_running_loop()._scheduled
                     if not h.cancelled())
        return min(times, default=float("inf"))

    async def advance(self, ms, *, inclusive=True):
        limit = 1000.0 + ms / 1000
        for _ in range(2048):
            due = self.next_due()
            if due > limit or (not inclusive and due >= limit):
                self.now = limit
                return
            self.now = max(self.now, due)
            await self.settle()
        raise RuntimeError("virtual timer failed to make progress")
