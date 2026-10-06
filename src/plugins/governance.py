from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from src.services.governance.service import GovernanceService
from src.services.persistence import StorageService
from src.services.delivery.dispatcher import finish_to_event

admin_cmd = on_command("mako-admin", aliases={"茉子管理"}, priority=8, block=True)

governance = GovernanceService()
storage = StorageService()


@admin_cmd.handle()
async def handle_admin(matcher: Matcher, event: MessageEvent) -> None:
    user_id = event.user_id
    if not governance.is_admin_user(user_id):
        await finish_to_event(matcher, event, "权限不足。")

    text = event.get_plaintext().strip()
    payload = text[len("mako-admin") :].strip() if text.startswith("mako-admin") else text
    parts = payload.split()
    if not parts:
        await finish_to_event(matcher, event, "用法: mako-admin block <uid> | unblock <uid> | cost")

    action = parts[0].lower()
    if action == "block" and len(parts) >= 2:
        try:
            target = int(parts[1])
        except ValueError:
            await finish_to_event(matcher, event, "uid 格式错误。")
        storage.add_user_blacklist(target, reason="manual_admin_block")
        await finish_to_event(matcher, event, f"已加入黑名单: {target}")

    if action == "unblock" and len(parts) >= 2:
        try:
            target = int(parts[1])
        except ValueError:
            await finish_to_event(matcher, event, "uid 格式错误。")
        storage.remove_user_blacklist(target)
        await finish_to_event(matcher, event, f"已解除黑名单: {target}")

    if action == "cost":
        global_cost = storage.get_daily_cost()
        user_cost = storage.get_daily_cost(user_id)
        await finish_to_event(matcher, event, f"今日成本: global={global_cost:.4f}, you={user_cost:.4f}")

    await finish_to_event(matcher, event, "未知子命令。")
