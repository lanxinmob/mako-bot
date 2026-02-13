from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional

from nonebot.log import logger

from src.core.config import get_settings
from src.core.prompts import MAKO_SYSTEM_PROMPT
from src.models.schemas import ChatRecord
from src.services.affinity import AffinityService
from src.services.llm import get_deepseek_client, get_openai_client, has_deepseek, has_openai
from src.services.storage import StorageService
from src.services.vector_store import VectorStore


class ChatEngine:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = StorageService()
        self.vector_store = VectorStore()
        self.affinity = AffinityService()

    @staticmethod
    def session_key(message_type: str, user_id: int, group_id: Optional[int] = None) -> str:
        if message_type == "group" and group_id:
            return f"group_{group_id}"
        return f"private_{user_id}"

    def load_profile_text(self, user_id: int) -> str:
        profile = self.storage.get_profile(user_id)
        if not profile:
            return "暂未建立画像。"
        return profile.get("profile_text", "暂未建立画像。")

    async def generate_reply(
        self,
        session_id: str,
        user_id: int,
        nickname: str,
        user_text: str,
        tool_context: Optional[str] = None,
    ) -> str:
        history = self.storage.get_history(session_id)
        profile_text = self.load_profile_text(user_id)
        affinity_score = self.affinity.get_score(user_id)
        affinity_style = self.affinity.style_hint(affinity_score)
        related_knowledge = self.vector_store.search(user_text)
        related_text = "\n".join(related_knowledge) if related_knowledge else "暂无相关长期记忆。"
        tool_context = tool_context or "无"

        system_prompt = (
            f"{MAKO_SYSTEM_PROMPT}\n\n"
            f"当前用户画像：\n{profile_text}\n\n"
            f"当前好感度：{affinity_score}（{self.affinity.level(affinity_score)}）\n"
            f"互动风格建议：{affinity_style}\n\n"
            f"相关沉淀记忆：\n{related_text}\n\n"
            f"工具结果上下文：\n{tool_context}\n"
        )

        messages: List[dict] = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": f"【{nickname}_{user_id}】：{user_text}"})

        reply = await self._call_llm(messages)

        new_history = history + [
            {"role": "user", "content": f"【{nickname}_{user_id}】：{user_text}", "time": datetime.now().isoformat()},
            {"role": "assistant", "content": reply, "time": datetime.now().isoformat()},
        ]
        self.storage.save_history(session_id, new_history)

        self.storage.append_global_record(
            ChatRecord(
                role="user",
                content=user_text,
                nickname=nickname,
                user_id=user_id,
                time=datetime.now(),
            )
        )
        self.storage.append_global_record(
            ChatRecord(
                role="assistant",
                content=reply,
                user_id=user_id,
                time=datetime.now(),
            )
        )
        return reply

    async def _call_llm(self, messages: List[dict]) -> str:
        if has_deepseek():
            client = get_deepseek_client()
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2048,
                ),
                timeout=40.0,
            )
            return response.choices[0].message.content.strip()

        if has_openai():
            client = get_openai_client()
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.3,
                    max_tokens=2048,
                ),
                timeout=40.0,
            )
            return response.choices[0].message.content.strip()

        logger.warning("No LLM provider configured, fallback to canned reply.")
        return "茉子大人现在有点迷糊，先把 API 配置好再来聊天吧。"
