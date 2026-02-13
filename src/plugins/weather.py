from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText, CommandArg

from src.services.weather import get_weather

weather_handler = on_command("天气", aliases={"weather"}, priority=10, block=True)


@weather_handler.handle()
async def handle_first_receive(matcher: Matcher, args: Message = CommandArg()) -> None:
    plain_text = args.extract_plain_text().strip()
    if plain_text:
        matcher.set_arg("city", args)


@weather_handler.got("city", prompt="你想查哪个城市的天气？")
async def handle_get_weather(city: str = ArgPlainText()) -> None:
    city = city.strip()
    if not city:
        await weather_handler.reject("城市名不能为空。")
        return
    data = await get_weather(city)
    if not data:
        await weather_handler.finish(f"没有查到 {city} 的天气。")
        return
    msg = (
        f"{data['country']}{data['city']} 当前天气：{data['text']}\n"
        f"气温：{data['temp']}C（体感 {data['feels_like']}C）\n"
        f"风向：{data['wind_dir']}，风速：{data['wind_speed']} km/h\n"
        f"湿度：{data['humidity']}%"
    )
    await weather_handler.finish(msg)
