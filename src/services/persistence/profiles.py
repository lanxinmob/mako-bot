from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from src.models.schemas import BotProfile


from src.services.persistence.backends import Repository


class ProfilesRepository(Repository):
    def get_profile(self, user_id: int) -> Optional[dict]:
        key = f"user_profile:{user_id}"
        if self.redis:
            raw = self.redis.get(key)
            return self._parse_profile_payload(raw, key=key) if raw else None
        raw = self.backend.memory.profiles.get(key)
        return self._parse_profile_payload(raw, key=key) if raw else None

    def set_profile(self, user_id: int, nickname: str, profile_text: str) -> None:
        key = f"user_profile:{user_id}"
        value = {
            "user_id": user_id,
            "nickname": nickname,
            "profile_text": profile_text,
            "last_updated": datetime.now().isoformat(),
        }
        raw = json.dumps(value, ensure_ascii=False)
        if self.redis:
            self.redis.set(key, raw)
            return
        self.backend.memory.profiles[key] = raw

    def list_profiles(self) -> List[dict]:
        if self.redis:
            keys = self.redis.keys("user_profile:*")
            rows = [(str(key), self.redis.get(key)) for key in keys]
        else:
            rows = list(self.backend.memory.profiles.items())
        profiles: List[dict] = []
        for key, raw in rows:
            if not raw:
                continue
            profile = self._parse_profile_payload(raw, key=key)
            if profile:
                profiles.append(profile)
        profiles.sort(key=lambda x: x.get("last_updated", ""), reverse=True)
        return profiles

    @staticmethod
    def _parse_profile_payload(raw: str, *, key: str = "") -> Optional[dict]:
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"profile_text": raw}
        if not isinstance(parsed, dict):
            parsed = {"profile_text": str(parsed)}
        if "user_id" not in parsed and key.startswith("user_profile:"):
            try:
                parsed["user_id"] = int(key.split(":", 1)[1])
            except (IndexError, ValueError):
                pass
        parsed.setdefault("nickname", f"用户 {parsed.get('user_id', '')}".strip())
        parsed.setdefault("profile_text", "")
        parsed.setdefault("last_updated", "")
        return parsed

    def save_bot_profile(self, profile: BotProfile) -> BotProfile:
        profile.updated_at = datetime.now()
        payload = json.dumps(profile.model_dump(mode="json"), ensure_ascii=False)
        if self.redis:
            self.redis.hset("bot_profiles", profile.profile_id, payload)
            self.redis.set(f"bot_profile:{profile.profile_id}", payload)
            return profile
        self.backend.memory.bot_profiles[profile.profile_id] = profile.model_dump(mode="json")
        return profile

    def add_bot_profile(
        self,
        name: str,
        *,
        summary: str = "",
        persona: str = "",
        capabilities: Optional[List[str]] = None,
        limitations: Optional[List[str]] = None,
        status: str = "active",
    ) -> BotProfile:
        profile = BotProfile(
            profile_id=uuid.uuid4().hex[:12],
            name=name,
            summary=summary,
            persona=persona,
            capabilities=capabilities or [],
            limitations=limitations or [],
            status=status,  # type: ignore[arg-type]
        )
        return self.save_bot_profile(profile)

    def get_bot_profile(self, profile_id: str) -> Optional[BotProfile]:
        if self.redis:
            raw = self.redis.get(f"bot_profile:{profile_id}") or self.redis.hget("bot_profiles", profile_id)
            if not raw:
                return None
            try:
                return BotProfile.model_validate_json(raw)
            except Exception:
                return None
        data = self.backend.memory.bot_profiles.get(profile_id)
        return BotProfile.model_validate(data) if data else None

    def list_bot_profiles(self, *, status: Optional[str] = None, limit: int = 50) -> List[BotProfile]:
        rows: List[str]
        if self.redis:
            rows = self.redis.hvals("bot_profiles")
            for key in self.redis.keys("bot_profile:*"):
                item = self.redis.get(key)
                if item:
                    rows.append(item)
        else:
            rows = [json.dumps(item, ensure_ascii=False) for item in self.backend.memory.bot_profiles.values()]
        profiles: List[BotProfile] = []
        seen: set[str] = set()
        for row in rows:
            try:
                profile = BotProfile.model_validate_json(row)
            except Exception:
                continue
            if profile.profile_id in seen:
                continue
            seen.add(profile.profile_id)
            if status and profile.status != status:
                continue
            profiles.append(profile)
        profiles.sort(key=lambda x: x.updated_at, reverse=True)
        return profiles[:limit]

    def get_affinity(self, user_id: int) -> int:
        initial = self.settings.affinity_initial
        key = f"affinity:{user_id}"
        if self.redis:
            value = self.redis.get(key)
            return int(value) if value is not None else initial
        return self.backend.memory.affinity.get(user_id, initial)

    def adjust_affinity(self, user_id: int, delta: int) -> int:
        min_score = self.settings.affinity_min
        max_score = self.settings.affinity_max
        daily_cap = self.settings.affinity_daily_cap
        day_key = f"{user_id}:{datetime.now().strftime('%Y%m%d')}"

        if self.redis:
            consumed = int(self.redis.get(f"affinity:daily:{day_key}") or 0)
            remain = max(0, daily_cap - consumed)
            effective = max(-remain, min(remain, delta))
            score = self.get_affinity(user_id)
            new_score = max(min_score, min(max_score, score + effective))
            self.redis.set(f"affinity:{user_id}", new_score)
            self.redis.set(f"affinity:daily:{day_key}", consumed + abs(effective), ex=172800)
            return new_score

        consumed = self.backend.memory.affinity_daily.get(day_key, 0)
        remain = max(0, daily_cap - consumed)
        effective = max(-remain, min(remain, delta))
        score = self.get_affinity(user_id)
        new_score = max(min_score, min(max_score, score + effective))
        self.backend.memory.affinity[user_id] = new_score
        self.backend.memory.affinity_daily[day_key] = consumed + abs(effective)
        return new_score
