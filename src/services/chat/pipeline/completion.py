"""Account for an acknowledged primary reply without retrying its delivery."""
import asyncio

from nonebot.log import logger


async def complete_sent_reply(services, incoming, transport, tools, request, reply, cost_status, delay,
                              *, history_receipt):
    status = {"history": "pending", "cost": cost_status, "attachments_sent": 0,
              "attachments_failed": 0, "attachments_total": len(tools.extra_messages)}
    try:
        try:
            if getattr(incoming, "work_kind", "chat") != "tool":
                services.chat_rhythm.mark_sent(incoming.address.session_id, sender_id=incoming.address.user_id)
        except Exception as exc:
            logger.warning("回复已发送，节奏状态更新失败: {}", exc)
        # Persist the primary reply before any optional attachment can fail.
        # Generation has already accounted for cost, including unsent replies.
        status["history"] = "unknown"
        try:
            effects = await services.history_delivery.consume(history_receipt)
        except Exception as exc:
            logger.warning("回复已发送，历史补记未确认: {}", exc)
        else:
            status.update(effects)
            complete = (set(effects) == {"history_session", "history_global"}
                        and all(value == "complete" for value in effects.values()))
            status["history"] = "confirmed" if complete else "pending"
        status["history_action_id"] = history_receipt.action_id
        for payload in tools.extra_messages:
            try:
                acknowledged = await transport.extra(payload)
            except Exception as exc:
                logger.warning("主回复已发送，附件未确认送达: {}", exc)
                acknowledged = False
            status["attachments_sent" if acknowledged is True else "attachments_failed"] += 1
    finally:
        # Cancellation does not undo a started effect thread. Preserve unknown.
        try:
            services.audit.progress("reply_sent", "主回复已发送；历史、费用与附件状态分别记录。", {
                "user_id": incoming.address.user_id, "group_id": incoming.address.group_id,
                "reply_preview": reply.text[:160], "reply_mode": request.reply_plan.mode,
                "delay_seconds": round(delay, 3), **status,
            })
        except Exception as exc:
            logger.warning("主回复已发送，审计记录失败: {}", exc)
