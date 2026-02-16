from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher

from src.services.governance import GovernanceService
from src.services.storage import StorageService

admin_cmd = on_command("mako-admin", aliases={"茉子管理"}, priority=8, block=True)

governance = GovernanceService()
storage = StorageService()


@admin_cmd.handle()
async def handle_admin(matcher: Matcher, event: MessageEvent) -> None:
    user_id = event.user_id
    if not governance.is_admin_user(user_id):
        await matcher.finish("权限不足。")

    text = event.get_plaintext().strip()
    payload = text[len("mako-admin") :].strip() if text.startswith("mako-admin") else text
    parts = payload.split()
    if not parts:
        await matcher.finish("用法: mako-admin block <uid> | unblock <uid> | cost")

    action = parts[0].lower()
    if action == "block" and len(parts) >= 2:
        try:
            target = int(parts[1])
        except ValueError:
            await matcher.finish("uid 格式错误。")
        storage.add_user_blacklist(target, reason="manual_admin_block")
        await matcher.finish(f"已加入黑名单: {target}")

    if action == "unblock" and len(parts) >= 2:
        try:
            target = int(parts[1])
        except ValueError:
            await matcher.finish("uid 格式错误。")
        storage.remove_user_blacklist(target)
        await matcher.finish(f"已解除黑名单: {target}")

    if action == "cost":
        global_cost = storage.get_daily_cost()
        user_cost = storage.get_daily_cost(user_id)
        await matcher.finish(f"今日成本: global={global_cost:.4f}, you={user_cost:.4f}")

    await matcher.finish("未知子命令。")
