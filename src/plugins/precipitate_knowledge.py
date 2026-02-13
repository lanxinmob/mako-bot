from __future__ import annotations

from collections import defaultdict

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText, CommandArg
from nonebot_plugin_apscheduler import scheduler

from src.services.llm import get_deepseek_client, get_openai_client, has_deepseek, has_openai
from src.services.storage import StorageService
from src.services.vector_store import VectorStore

storage = StorageService()
vector_store = VectorStore()
vector_store.ensure_index()


async def _summarize(prompt: str) -> str:
    if has_deepseek():
        client = get_deepseek_client()
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1200,
        )
        return response.choices[0].message.content.strip()
    if has_openai():
        client = get_openai_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1200,
        )
        return response.choices[0].message.content.strip()
    return ""


@scheduler.scheduled_job("cron", hour=22, minute=0)
async def precipitate_knowledge() -> None:
    records = storage.get_recent_global_records(hours=24)
    if not records:
        return

    lines = []
    user_logs = defaultdict(list)
    for record in records:
        if record.role == "user":
            lines.append(f"[{record.nickname}_{record.user_id}] {record.content}")
            user_logs[record.user_id].append((record.nickname or str(record.user_id), record.content))
        else:
            lines.append(f"[mako] {record.content}")
    corpus = "\n".join(lines)

    knowledge_prompt = (
        "请从以下聊天记录提炼 8 条以内长期有价值的记忆点，"
        "每条一行，中文简洁，不要废话：\n" + corpus
    )
    summary = await _summarize(knowledge_prompt)
    if summary:
        for line in summary.splitlines():
            point = line.strip("- ").strip()
            if point:
                vector_store.add(point)

    for user_id, msgs in user_logs.items():
        nickname = msgs[0][0]
        chat_text = "\n".join(item[1] for item in msgs[-50:])
        old_profile = storage.get_profile(user_id)
        old_text = old_profile["profile_text"] if old_profile else "暂无历史画像"
        profile_prompt = (
            f"请基于历史画像与最新发言，更新用户画像。\n"
            f"用户: {nickname}({user_id})\n"
            f"历史画像:\n{old_text}\n"
            f"最近发言:\n{chat_text}\n"
            f"输出格式:\n"
            f"【核心特质】\n【行为模式】\n【关系定位】\n【茉子认知画像】"
        )
        profile = await _summarize(profile_prompt)
        if profile:
            storage.set_profile(user_id, nickname, profile)
    logger.success("knowledge precipitation done.")


memory_handler = on_command("可塑性记忆", aliases={"memory"}, priority=10, block=True)


@memory_handler.handle()
async def handle_first_receive(matcher: Matcher, args: Message = CommandArg()) -> None:
    plain_text = args.extract_plain_text().strip()
    if plain_text:
        matcher.set_arg("target_id", args)


@memory_handler.got("target_id", prompt="要查看谁的画像？请输入用户ID")
async def handle_get_memory(target_id: str = ArgPlainText()) -> None:
    target_id = target_id.strip()
    if not target_id.isdigit():
        await memory_handler.finish("用户ID格式不正确。")
        return
    profile = storage.get_profile(int(target_id))
    if not profile:
        await memory_handler.finish("暂无该用户画像。")
        return
    await memory_handler.finish(
        f"对 {profile.get('nickname')}({target_id}) 的画像：\n\n{profile.get('profile_text', '')}"
    )
