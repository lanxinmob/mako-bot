import httpx
from nonebot import on_command
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText

from nonebot.params import ArgPlainText, CommandArg
from nonebot.adapters.onebot.v11 import Message

weather_handler = on_command("天气", aliases={"weather"},priority=10,block=True)

@weather_handler.handle()
async def handle_first_receive(matcher: Matcher, args: Message = CommandArg()):
    plain_text = args.extract_plain_text()
    if plain_text:
        matcher.set_arg("city", args)

@weather_handler.got("city", prompt="茉子要查哪个城市的天气呀~？")
async def handle_get_weather(city: str = ArgPlainText()):
    city = city.strip()
    if not city:
        await weather_handler.reject("呜...城市名称不能为空哦，请重新告诉我吧！")

    try:
        url = f"https://wttr.in/{city}?format=j1"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status() #
            data = resp.json()

        current = data['current_condition'][0]
        area = data['nearest_area'][0]['areaName'][0]['value']
        country = data['nearest_area'][0]['country'][0]['value']
        
        reply = (
            f"哼哼~ 茉子大人掐指一算，{area}, {country} 今天的天气是：\n"
            f"天气状况：{current['weatherDesc'][0]['value']}\n"
            f"气温：{current['temp_C']}°C (体感 {current['FeelsLikeC']}°C)\n"
            f"风向：{current['winddir16Point']} 风速：{current['windspeedKmph']} km/h\n"
            f"湿度：{current['humidity']}%"
        )
        await weather_handler.finish(Message(reply)) 

    except httpx.HTTPStatusError:
        await weather_handler.finish(f"哎呀，茉子找不到叫 '{city}' 的地方... 你是不是写错啦？")
    except FinishedException:
        await weather_handler.finish("ヽ(✿ﾟ▽ﾟ)ノ好耶，查询完毕了~")
    except Exception as e:
        print(f"查询天气时发生错误: {e}")
        await weather_handler.finish("呜呜，天气服务器好像罢工了，茉子也查不到啦~")