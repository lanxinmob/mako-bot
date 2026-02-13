from __future__ import annotations

from src.services.storage import StorageService


class AffinityService:
    def __init__(self) -> None:
        self.storage = StorageService()

    def get_score(self, user_id: int) -> int:
        return self.storage.get_affinity(user_id)

    def adjust(self, user_id: int, delta: int) -> int:
        return self.storage.adjust_affinity(user_id, delta)

    def level(self, score: int) -> str:
        if score >= 85:
            return "亲密"
        if score >= 65:
            return "友好"
        if score >= 45:
            return "普通"
        if score >= 20:
            return "冷淡"
        return "警惕"

    def style_hint(self, score: int) -> str:
        lvl = self.level(score)
        if lvl == "亲密":
            return "语气更亲昵，主动关心，偶尔给专属称呼。"
        if lvl == "友好":
            return "语气温和活泼，愿意深入交流。"
        if lvl == "普通":
            return "保持自然礼貌与轻松互动。"
        if lvl == "冷淡":
            return "语气克制简洁，减少主动展开。"
        return "语气谨慎，避免深入私人话题。"
