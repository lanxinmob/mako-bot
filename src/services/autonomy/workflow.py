from __future__ import annotations
from dataclasses import asdict
from typing import Any
from .models import AutonomyDecision

from .execution import ask_owner, ask_owner_clarification, send_action

async def handle_decision(ctx, bot: Any, decision: AutonomyDecision) -> str:
    if decision.risk == "high" or decision.confidence < 0.45:
        ctx.repository.append_log("silent", {"decision": asdict(decision)})
        ctx.repository.append_progress_event("decision_silent", "自主行动选择静默。", {"decision": asdict(decision)})
        return "silent"
    if decision.action == "silent":
        ctx.repository.append_log("silent", {"decision": asdict(decision)})
        ctx.repository.append_progress_event("decision_silent", "自主行动选择静默。", {"decision": asdict(decision)})
        return "silent"
    if not decision.target_id:
        acknowledged = await ask_owner_clarification(ctx,
            bot,
            "茉子有点分不清要对谁说呢。你直接告诉茉子目标 QQ 或目标群号吧，茉子再自己判断怎么开口~",
            decision,
        )
        return "asked" if acknowledged else "notification_failed"
    if not ctx.policy.target_allowed(decision.target_type, decision.target_id):
        if decision.target_type == "private":
            acknowledged = await ask_owner_clarification(ctx,
                bot,
                (
                    f"茉子认出你想让我私聊 {decision.target_id}，但这个 QQ 还不在 "
                    "AUTONOMY_PRIVATE_USER_IDS 白名单里。茉子不能擅自去打扰人家，"
                    f"你可以对茉子说“把 {decision.target_id} 加入私聊白名单”，"
                    "茉子记下后再自己判断要不要说~"
                ),
                decision,
            )
        else:
            acknowledged = await ask_owner_clarification(ctx,
                bot,
                (
                    f"茉子认出目标是群 {decision.target_id}，但它不在 AUTONOMY_GROUP_IDS 白名单里。"
                    "茉子先不乱跑啦。"
                ),
                decision,
            )
        return "asked" if acknowledged else "notification_failed"
    if not decision.message.strip():
        ctx.repository.append_log("silent", {"reason": "empty message", "decision": asdict(decision)})
        return "silent"
    if ctx.policy.should_act_directly(decision):
        sent = await send_action(ctx,
            bot,
            decision.target_type,
            decision.target_id,
            decision.message,
            decision.reason,
            intent=decision.intent,
        )
        return "sent" if sent else "rejected"
    if ctx.policy.should_ask_owner(decision):
        acknowledged = await ask_owner(ctx, bot, decision)
        return "asked" if acknowledged else "notification_failed"
    ctx.repository.append_log("silent", {"decision": asdict(decision)})
    ctx.repository.append_progress_event("decision_silent", "自主行动选择静默。", {"decision": asdict(decision)})
    return "silent"
