from __future__ import annotations

import random

from nonebot import on_keyword
from nonebot.matcher import Matcher

FOOD_MENU = [
    "麻辣烫",
    "肯德基",
    "麦当劳",
    "汉堡王",
    "沙县小吃",
    "兰州拉面",
    "黄焖鸡米饭",
    "猪脚饭",
    "螺蛳粉",
    "炒饭",
    "盖浇饭",
    "寿司",
    "烤肉",
    "火锅",
    "饺子",
    "包子",
    "泡面加蛋",
    "自己做",
    "披萨",
    "轻食沙拉",
]

eat_handler = on_keyword({"吃什么", "吃啥"}, priority=50)


@eat_handler.handle()
async def handle_eat_request(matcher: Matcher) -> None:
    choice = random.choice(FOOD_MENU)
    replies = [
        f"今天就吃 {choice} 吧。",
        f"我建议你去吃 {choice}，稳。",
        f"别纠结了，{choice} 安排。",
        f"掐指一算，{choice} 最合适。",
    ]
    await matcher.finish(random.choice(replies))
