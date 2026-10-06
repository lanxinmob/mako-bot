from __future__ import annotations

from datetime import datetime
from typing import Optional


from src.services.persistence.backends import Repository


class GovernanceRepository(Repository):
    def is_user_blacklisted(self, user_id: int) -> bool:
        if self.redis:
            return bool(self.redis.sismember("blacklist:users", user_id))
        return user_id in self.backend.memory.blacklisted_users

    def is_group_blacklisted(self, group_id: int) -> bool:
        if self.redis:
            return bool(self.redis.sismember("blacklist:groups", group_id))
        return group_id in self.backend.memory.blacklisted_groups

    def add_user_blacklist(self, user_id: int, reason: str = "") -> None:
        if self.redis:
            self.redis.sadd("blacklist:users", user_id)
            if reason:
                self.redis.hset("blacklist:user:reason", user_id, reason)
            return
        self.backend.memory.blacklisted_users[user_id] = reason

    def remove_user_blacklist(self, user_id: int) -> None:
        if self.redis:
            self.redis.srem("blacklist:users", user_id)
            self.redis.hdel("blacklist:user:reason", user_id)
            return
        self.backend.memory.blacklisted_users.pop(user_id, None)

    def add_group_blacklist(self, group_id: int, reason: str = "") -> None:
        if self.redis:
            self.redis.sadd("blacklist:groups", group_id)
            if reason:
                self.redis.hset("blacklist:group:reason", group_id, reason)
            return
        self.backend.memory.blacklisted_groups[group_id] = reason

    def remove_group_blacklist(self, group_id: int) -> None:
        if self.redis:
            self.redis.srem("blacklist:groups", group_id)
            self.redis.hdel("blacklist:group:reason", group_id)
            return
        self.backend.memory.blacklisted_groups.pop(group_id, None)

    def consume_cost(self, user_id: int, amount: float, *, at: Optional[datetime] = None) -> None:
        if amount <= 0:
            return
        at = at or datetime.now()
        day = at.strftime("%Y%m%d")
        g_key = f"cost:global:{day}"
        u_key = f"cost:user:{user_id}:{day}"
        if self.redis:
            self.redis.incrbyfloat(g_key, amount)
            self.redis.incrbyfloat(u_key, amount)
            self.redis.expire(g_key, 172800)
            self.redis.expire(u_key, 172800)
            return
        self.backend.memory.daily_costs[g_key] = self.backend.memory.daily_costs.get(g_key, 0.0) + amount
        self.backend.memory.daily_costs[u_key] = self.backend.memory.daily_costs.get(u_key, 0.0) + amount

    def get_daily_cost(self, user_id: Optional[int] = None, *, at: Optional[datetime] = None) -> float:
        at = at or datetime.now()
        day = at.strftime("%Y%m%d")
        key = f"cost:global:{day}" if user_id is None else f"cost:user:{user_id}:{day}"
        if self.redis:
            value = self.redis.get(key)
            return float(value) if value is not None else 0.0
        return float(self.backend.memory.daily_costs.get(key, 0.0))
