import random
from nonebot import on_keyword
from nonebot.matcher import Matcher

FOOD_MENU = [
    "麻辣烫", "肯德基", "麦当劳", "汉堡王", "沙县小吃", "兰州拉面",
    "黄焖鸡米饭", "猪脚饭", "螺蛳粉", "炒饭", "盖浇饭", "寿司",
    "烤肉", "火锅", "饺子", "包子", "泡面加个蛋", "自己做！",
    "披萨", "轻食沙拉", "麻辣香锅", "烧烤", "串串香", "铁板烧"
]

eat_handler = on_keyword({"吃什么", "吃啥"}, priority=50)

@eat_handler.handle()
async def handle_eat_request(matcher: Matcher):

    choice = random.choice(FOOD_MENU)
    
    reply_messages = [
        f"哼，这点小事都要问我~ 那就勉为其难地告诉你，去吃【{choice}】吧！",
        f"茉子大人觉得，今天的运势很适合吃【{choice}】哦~ (´∀｀*)",
        f"别想了别想了！就决定是你了，【{choice}】！快去吃！",
        f"我看看...（掐指）...今天适合用【{choice}】来填饱你的肚子~！"
    ]
    
    await matcher.finish(random.choice(reply_messages))