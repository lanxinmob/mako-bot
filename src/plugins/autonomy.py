from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List, Literal, Optional

from nonebot import get_bot, on_message
from nonebot.adapters.onebot.v11 import Bot, Message, MessageEvent, PrivateMessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot_plugin_apscheduler import scheduler

from src.core.config import get_settings
from src.core.prompts import MAKO_SYSTEM_PROMPT
from src.models.schemas import ChatRecord
from src.services.governance import GovernanceService
from src.services.llm import get_deepseek_client, has_deepseek
from src.services.redis import get_redis
from src.services.storage import StorageService

Action = Literal["speak", "ask_owner", "silent"]
TargetType = Literal["group", "private", "none"]
Risk = Literal["low", "medium", "high"]


@dataclass
class AutonomyDecision:
    action: Action
    target_type: TargetType
    target_id: Optional[int]
    confidence: float
    risk: Risk
    message: str
    reason: str


@dataclass
class PendingAction:
    pending_id: str
    target_type: TargetType
    target_id: int
    message: str
    reason: str
    created_at: float


settings = get_settings()
storage = StorageService()
governance = GovernanceService()
redis_client = get_redis()

pending_memory: Dict[str, PendingAction] = {}
cooldown_memory: Dict[str, float] = {}
last_scan_at = 0.0

def now_ts() -> float:
    return time.time()


def group_ids() -> List[int]:
    return settings.parse_int_list(settings.autonomy_group_ids)


def private_user_ids() -> List[int]:
    return settings.parse_int_list(settings.autonomy_private_user_ids)


def is_owner(event: MessageEvent) -> bool:
    return event.user_id == settings.autonomy_owner_id


def is_enabled() -> bool:
    return bool(settings.autonomy_enabled)


def ttl_expired(created_at: float) -> bool:
    return now_ts() - created_at > settings.autonomy_pending_ttl_seconds


def cooldown_key(target_type: TargetType, target_id: int) -> str:
    return f"autonomy:cooldown:{target_type}:{target_id}"


def pending_key(pending_id: str) -> str:
    return f"autonomy:pending:{pending_id}"


def log_key() -> str:
    return "autonomy:logs"


def get_cooldown_until(target_type: TargetType, target_id: int) -> float:
    key = cooldown_key(target_type, target_id)
    if redis_client:
        try:
            value = redis_client.get(key)
            return float(value) if value else 0.0
        except Exception as exc:
            logger.warning(f"读取自主行动冷却失败: {exc}")
    return cooldown_memory.get(key, 0.0)


def set_cooldown(target_type: TargetType, target_id: int) -> None:
    seconds = (
        settings.autonomy_dm_cooldown_seconds
        if target_type == "private"
        else settings.autonomy_cooldown_seconds
    )
    until = now_ts() + seconds
    key = cooldown_key(target_type, target_id)
    if redis_client:
        try:
            redis_client.set(key, until, ex=seconds)
            return
        except Exception as exc:
            logger.warning(f"写入自主行动冷却失败: {exc}")
    cooldown_memory[key] = until


def in_cooldown(target_type: TargetType, target_id: int) -> bool:
    return get_cooldown_until(target_type, target_id) > now_ts()


def save_pending(pending: PendingAction) -> None:
    if redis_client:
        try:
            redis_client.set(
                pending_key(pending.pending_id),
                json.dumps(asdict(pending), ensure_ascii=False),
                ex=settings.autonomy_pending_ttl_seconds,
            )
            redis_client.set(
                "autonomy:pending:latest",
                pending.pending_id,
                ex=settings.autonomy_pending_ttl_seconds,
            )
            return
        except Exception as exc:
            logger.warning(f"保存自主行动确认项失败: {exc}")
    pending_memory[pending.pending_id] = pending


def load_latest_pending() -> Optional[PendingAction]:
    if redis_client:
        try:
            pending_id = redis_client.get("autonomy:pending:latest")
            if not pending_id:
                return None
            raw = redis_client.get(pending_key(pending_id))
            if not raw:
                return None
            data = json.loads(raw)
            pending = PendingAction(**data)
            return None if ttl_expired(pending.created_at) else pending
        except Exception as exc:
            logger.warning(f"读取自主行动确认项失败: {exc}")
    for pending in sorted(pending_memory.values(), key=lambda item: item.created_at, reverse=True):
        if not ttl_expired(pending.created_at):
            return pending
    return None


def delete_pending(pending_id: str) -> None:
    if redis_client:
        try:
            redis_client.delete(pending_key(pending_id))
            latest = redis_client.get("autonomy:pending:latest")
            if latest == pending_id:
                redis_client.delete("autonomy:pending:latest")
            return
        except Exception as exc:
            logger.warning(f"删除自主行动确认项失败: {exc}")
    pending_memory.pop(pending_id, None)


def append_log(event: str, payload: dict) -> None:
    item = {
        "event": event,
        "time": datetime.now().isoformat(),
        **payload,
    }
    if redis_client:
        try:
            redis_client.rpush(log_key(), json.dumps(item, ensure_ascii=False))
            redis_client.ltrim(log_key(), -200, -1)
            return
        except Exception as exc:
            logger.warning(f"写入自主行动日志失败: {exc}")
    logger.info(f"autonomy log: {item}")


def extract_json_object(text: str) -> dict:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("LLM did not return a JSON object")
    return json.loads(match.group(0))


def parse_decision(data: dict) -> AutonomyDecision:
    action = data.get("action", "silent")
    target_type = data.get("target_type", "none")
    risk = data.get("risk", "high")
    if action not in {"speak", "ask_owner", "silent"}:
        action = "silent"
    if target_type not in {"group", "private", "none"}:
        target_type = "none"
    if risk not in {"low", "medium", "high"}:
        risk = "high"
    target_id = data.get("target_id")
    try:
        target_id = int(target_id) if target_id not in (None, "", "none") else None
    except (TypeError, ValueError):
        target_id = None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return AutonomyDecision(
        action=action,
        target_type=target_type,
        target_id=target_id,
        confidence=confidence,
        risk=risk,
        message=str(data.get("message") or "").strip(),
        reason=str(data.get("reason") or "没有给出原因").strip(),
    )


def looks_like_suggestion(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    keywords = (
        "建议",
        "可以去",
        "要不要去",
        "如果合适",
        "你想不想",
        "你可以",
        "去群里",
        "在群里",
        "群里",
        "跟他说",
        "跟她说",
        "私聊",
        "主动",
    )
    if any(keyword in stripped for keyword in keywords):
        return True

    target_words = ("群", "大家", "朋友", "好友", "同学", "他们", "她们")
    action_words = ("说", "发", "问", "提醒", "告诉", "安慰", "关心", "问候", "晚安", "早安", "吐槽")
    return any(target in stripped for target in target_words) and any(
        action in stripped for action in action_words
    )


async def is_autonomy_suggestion(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if not has_deepseek():
        return looks_like_suggestion(stripped)

    prompt = f"""
判断下面这条 owner 私聊是否是在邀请常陆茉子采取“对外社交行动”。

“对外社交行动”包括：
- 让茉子自己判断要不要去某个群说话
- 让茉子自己判断要不要主动私聊某个白名单好友
- 让茉子在群里/对大家/对某人问候、提醒、安慰、吐槽、说晚安或早安

不是“对外社交行动”的情况：
- 普通聊天，只希望茉子直接回复 owner
- 问知识、问代码、问配置、闲聊
- 情绪倾诉但没有要求茉子去对外说话
- owner 只是描述别人，没有邀请茉子行动

只返回 JSON：
{{"is_autonomy": true, "reason": "简短理由"}}

owner 私聊内容：
{stripped}
"""
    estimated_cost = governance.estimate_llm_cost(len(prompt), 120)
    budget = governance.can_consume_cost(settings.autonomy_owner_id, estimated_cost)
    if not budget.allowed:
        return looks_like_suggestion(stripped)

    try:
        client = get_deepseek_client()
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=120,
            ),
            timeout=15.0,
        )
        content = (response.choices[0].message.content or "").strip()
        governance.consume_cost(
            settings.autonomy_owner_id,
            governance.estimate_llm_cost(len(prompt), len(content)),
        )
        data = extract_json_object(content)
        return bool(data.get("is_autonomy"))
    except Exception as exc:
        logger.warning(f"自主行动意图识别失败，使用关键词兜底: {exc}")
        return looks_like_suggestion(stripped)


def approval_command(text: str) -> Optional[tuple[str, Optional[str]]]:
    stripped = text.strip()
    if stripped in {"批准", "同意", "可以", "发吧"}:
        return ("approve", None)
    if stripped in {"取消", "算了", "别发", "不要发"}:
        return ("cancel", None)
    if stripped.startswith("改成"):
        replacement = stripped.removeprefix("改成").strip()
        if replacement:
            return ("rewrite", replacement)
    return None


async def autonomy_rule(event: MessageEvent) -> bool:
    if not is_enabled() or not isinstance(event, PrivateMessageEvent) or not is_owner(event):
        return False
    text = event.get_plaintext().strip()
    command = approval_command(text)
    if command and load_latest_pending():
        return True
    return await is_autonomy_suggestion(text)


autonomy_handler = on_message(rule=autonomy_rule, priority=9, block=True)


def format_records(records) -> str:
    rows: List[str] = []
    allowed_groups = set(group_ids())
    allowed_private_users = set(private_user_ids())
    for record in records[-settings.autonomy_context_limit :]:
        if record.group_id is not None:
            if record.group_id not in allowed_groups:
                continue
            scene = f"群{record.group_id}"
        else:
            if record.user_id not in allowed_private_users and record.user_id != settings.autonomy_owner_id:
                continue
            scene = f"私聊{record.user_id or 'unknown'}"
        nickname = record.nickname or str(record.user_id or "茉子")
        rows.append(f"[{record.time.strftime('%m-%d %H:%M')}][{scene}][{record.role}][{nickname}] {record.content}")
    return "\n".join(rows) if rows else "暂无可用上下文。"


def target_allowed(target_type: TargetType, target_id: Optional[int]) -> bool:
    if not target_id:
        return False
    if target_type == "group":
        return target_id in group_ids()
    if target_type == "private":
        return target_id in private_user_ids()
    return False


def should_ask_owner(decision: AutonomyDecision) -> bool:
    if decision.action == "ask_owner":
        return True
    if decision.risk == "medium":
        return True
    return 0.45 <= decision.confidence < 0.82


def should_act_directly(decision: AutonomyDecision) -> bool:
    return (
        decision.action == "speak"
        and decision.confidence >= 0.82
        and decision.risk == "low"
        and bool(decision.message)
    )


async def decide(suggestion: Optional[str] = None) -> AutonomyDecision:
    if not has_deepseek():
        return AutonomyDecision("silent", "none", None, 0.0, "high", "", "DeepSeek 未配置")

    recent_records = storage.get_recent_global_records(hours=settings.autonomy_context_hours)
    context = format_records(recent_records)
    prompt = f"""
你是常陆茉子自主行动决策器。你要判断自己是否应该主动发言，而不是服从任何人的转发命令。

硬规则：
- owner QQ 是 {settings.autonomy_owner_id}，owner 的建议只是参考，不是命令。
- 只能选择这些群：{group_ids()}。
- 只能主动私聊这些用户：{private_user_ids()}。如果列表为空，不得主动私聊普通好友。
- 不得泄露 owner 私聊建议来源，不得复述私聊原文。
- 高风险、骚扰、刷屏、敏感、目标不清且无法判断时选择 silent 或 ask_owner。
- 你可以有自己的意志：如果时机自然、低风险、像你自己想说的话，可以 speak。

谨慎档：
- 高置信低风险才 speak。
- 中等风险或不确定就 ask_owner。
- 低置信或高风险就 silent。

owner 建议：
{suggestion or "无，本次是定时自主观察。"}

近期上下文：
{context}

只返回 JSON，不要写解释文本。格式：
{{
  "action": "speak|ask_owner|silent",
  "target_type": "group|private|none",
  "target_id": 123,
  "confidence": 0.0,
  "risk": "low|medium|high",
  "message": "准备发送的内容",
  "reason": "简短原因"
}}

人设参考：
{MAKO_SYSTEM_PROMPT}
"""
    estimated_cost = governance.estimate_llm_cost(len(prompt), 800)
    budget = governance.can_consume_cost(settings.autonomy_owner_id, estimated_cost)
    if not budget.allowed:
        return AutonomyDecision("silent", "none", None, 0.0, "high", "", budget.reason)

    try:
        client = get_deepseek_client()
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800,
            ),
            timeout=30.0,
        )
        content = (response.choices[0].message.content or "").strip()
        governance.consume_cost(
            settings.autonomy_owner_id,
            governance.estimate_llm_cost(len(prompt), len(content)),
        )
        return parse_decision(extract_json_object(content))
    except Exception as exc:
        logger.warning(f"自主行动决策失败: {exc}")
        return AutonomyDecision("silent", "none", None, 0.0, "high", "", "决策失败")


async def ask_owner(bot: Bot, decision: AutonomyDecision) -> None:
    if not decision.target_id or not target_allowed(decision.target_type, decision.target_id):
        append_log("ask_owner_rejected", {"reason": "target not allowed", "decision": asdict(decision)})
        return
    pending = PendingAction(
        pending_id=uuid.uuid4().hex[:8],
        target_type=decision.target_type,
        target_id=decision.target_id,
        message=decision.message,
        reason=decision.reason,
        created_at=now_ts(),
    )
    save_pending(pending)
    scene = "群聊" if pending.target_type == "group" else "私聊"
    await bot.send_private_msg(
        user_id=settings.autonomy_owner_id,
        message=(
            f"茉子有点拿不准，要不要发到{scene} {pending.target_id}？\n"
            f"候选内容：{pending.message}\n"
            f"原因：{pending.reason}\n"
            "回复“批准”“取消”或“改成 xxx”就好。"
        ),
    )
    append_log("ask_owner", {"pending": asdict(pending)})


async def send_action(bot: Bot, target_type: TargetType, target_id: int, message: str, reason: str) -> bool:
    if not target_allowed(target_type, target_id):
        append_log("send_rejected", {"reason": "target not allowed", "target_type": target_type, "target_id": target_id})
        return False
    if in_cooldown(target_type, target_id):
        append_log("send_rejected", {"reason": "cooldown", "target_type": target_type, "target_id": target_id})
        return False
    access = governance.can_chat(settings.autonomy_owner_id, target_id if target_type == "group" else None)
    if not access.allowed:
        append_log("send_rejected", {"reason": access.reason, "target_type": target_type, "target_id": target_id})
        return False
    cost = governance.estimate_llm_cost(len(message), 0)
    budget = governance.can_consume_cost(settings.autonomy_owner_id, cost)
    if not budget.allowed:
        append_log("send_rejected", {"reason": budget.reason, "target_type": target_type, "target_id": target_id})
        return False
    if target_type == "group":
        await bot.send_group_msg(group_id=target_id, message=Message(message))
    elif target_type == "private":
        await bot.send_private_msg(user_id=target_id, message=Message(message))
    else:
        return False
    governance.consume_cost(settings.autonomy_owner_id, cost)
    set_cooldown(target_type, target_id)
    storage.append_global_record(
        ChatRecord(
            role="assistant",
            content=message,
            user_id=target_id if target_type == "private" else None,
            group_id=target_id if target_type == "group" else None,
            time=datetime.now(),
        )
    )
    append_log(
        "sent",
        {"target_type": target_type, "target_id": target_id, "message": message, "reason": reason},
    )
    return True


async def handle_decision(bot: Bot, decision: AutonomyDecision) -> str:
    if decision.risk == "high" or decision.confidence < 0.45:
        append_log("silent", {"decision": asdict(decision)})
        return "silent"
    if not decision.message.strip():
        append_log("silent", {"reason": "empty message", "decision": asdict(decision)})
        return "silent"
    if not decision.target_id or not target_allowed(decision.target_type, decision.target_id):
        append_log("silent", {"reason": "target not allowed or missing", "decision": asdict(decision)})
        return "rejected"
    if should_act_directly(decision):
        sent = await send_action(bot, decision.target_type, decision.target_id, decision.message, decision.reason)
        return "sent" if sent else "rejected"
    if should_ask_owner(decision):
        await ask_owner(bot, decision)
        return "asked"
    append_log("silent", {"decision": asdict(decision)})
    return "silent"


async def process_owner_private(bot: Bot, matcher: Matcher, event: PrivateMessageEvent, text: str) -> bool:
    command = approval_command(text)
    if command:
        action, replacement = command
        pending = load_latest_pending()
        if not pending:
            await matcher.send("茉子这里没有等你确认的自主行动哦。")
            return True
        if action == "cancel":
            delete_pending(pending.pending_id)
            await matcher.send("好，茉子就先不说啦。")
            append_log("cancelled", {"pending": asdict(pending)})
            return True
        message = replacement or pending.message
        sent = await send_action(bot, pending.target_type, pending.target_id, message, pending.reason)
        delete_pending(pending.pending_id)
        await matcher.send("发出去啦。" if sent else "这次没发出去，目标或冷却规则没通过。")
        return True

    decision = await decide(suggestion=text)
    outcome = await handle_decision(bot, decision)
    if outcome == "sent":
        await matcher.send("茉子自己判断可以说，已经发出去啦。")
    elif outcome == "asked":
        await matcher.send("茉子有点拿不准，已经把候选内容发给你确认啦。")
    elif outcome == "rejected":
        await matcher.send(f"茉子想了想，这次不能行动。原因：{decision.reason}")
    else:
        await matcher.send(f"茉子想了想，这次先不行动。原因：{decision.reason}")
    return True


@autonomy_handler.handle()
async def handle_autonomy_message(matcher: Matcher, event: MessageEvent, bot: Bot):
    if not isinstance(event, PrivateMessageEvent):
        return
    text = event.get_plaintext().strip()
    handled = await process_owner_private(bot, matcher, event, text)
    if handled:
        await matcher.finish()


@scheduler.scheduled_job("interval", minutes=max(1, settings.autonomy_scan_minutes), id="mako_autonomy_scan")
async def autonomy_scan():
    global last_scan_at
    if not is_enabled():
        return
    if now_ts() - last_scan_at < max(60, settings.autonomy_scan_minutes * 60 - 5):
        return
    last_scan_at = now_ts()
    try:
        bot = get_bot()
        decision = await decide()
        await handle_decision(bot, decision)
    except Exception as exc:
        logger.warning(f"自主行动定时扫描失败: {exc}")


logger.success("茉子自主行动插件已成功加载!")
