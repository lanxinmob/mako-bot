"""NoneBot command adapter for the weather service."""

from __future__ import annotations

from nonebot import on_command
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText, CommandArg
from nonebot.adapters.onebot.v11 import Message

from src.core.errors import NotConfiguredError
from src.services.weather import get_weather


weather_handler = on_command("天气", aliases={"weather"}, priority=10, block=True)


@weather_handler.handle()
async def handle_first_receive(matcher: Matcher, args: Message = CommandArg()) -> None:
    if args.extract_plain_text():
        matcher.set_arg("city", args)


@weather_handler.got("city", prompt="茉子要查哪个城市的天气呀~？")
async def handle_get_weather(city: str = ArgPlainText()) -> None:
    city = city.strip()
    if not city:
        await weather_handler.reject("城市名称不能为空，请重新告诉茉子吧！")
        return
    try:
        weather = await get_weather(city)
    except NotConfiguredError:
        await weather_handler.finish("天气服务还没有配置 QWEATHER_HOST 和 QWEATHER_KEY。")
        return
    except Exception:
        logger.exception("天气查询失败 city={}", city)
        await weather_handler.finish("天气服务暂时不可用，请稍后再试。")
        return
    if not weather:
        await weather_handler.finish(f"没有找到“{city}”的天气信息，请检查城市名称。")
        return
    reply = (
        f"{weather['country']}{weather['city']} 当前天气：{weather['text']}\n"
        f"气温：{weather['temp']}°C（体感 {weather['feels_like']}°C）\n"
        f"风向：{weather['wind_dir']}，风速：{weather['wind_speed']} km/h\n"
        f"湿度：{weather['humidity']}%"
    )
    await weather_handler.finish(Message(reply))
