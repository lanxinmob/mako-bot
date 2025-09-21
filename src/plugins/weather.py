import httpx
from nonebot import on_command
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText
from nonebot.exception import FinishedException
from nonebot.params import ArgPlainText, CommandArg
from nonebot.adapters.onebot.v11 import Message,MessageSegment
import os
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
        print(f"API Host: {os.getenv('your_api_host')}") 
        print(f"API Key: {os.getenv('your_api')}")
        
        url = f"https://{os.getenv('your_api_host')}/geo/v2/city/lookup?location={city}&key={os.getenv('your_api')}"
        #headers = {f"Authorization: Bearer {os.getenv("your_token")}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status() 
            data_place = resp.json()

        if data_place["code"]!="200":
            await weather_handler.finish(f"哎呀，茉子找不到叫 '{city}' 的地方... 你是不是写错啦？") 
            return 
        
        location_id = data_place["location"][0]["id"]

        url = f"https://{os.getenv('your_api_host')}/v7/weather/now?location={location_id}&key={os.getenv('your_api')}"
        #headers = {f"Authorization: Bearer {os.getenv("your_token")}"}
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status() 
            data = resp.json()
        
        if data["code"]!="200":
            await weather_handler.finish("呜呜，天气服务器好像罢工了，茉子也查不到啦~")
            return
        
        now = data["now"]
        country = data_place["location"]["country"]
        area = data_place["location"]["name"]
        icon_code = (now['icon'])
        icon_path = os.path.join("/root/mako-bot/WeatherIcon/weather-icon-S1/color-128", f"{icon_code}.png")
        reply_1 = (
            f"哼哼~ 茉子大人掐指一算，{country}{area} 现在的天气是：\n"     
        )
        reply_2 = (
            f"天气状况：{now['text']}\n"
            f"气温：{now['temp']}°C (体感 {now['feelsLike']}°C)\n"
            f"风向：{now['windDir']} 风速：{now['windSpeed']} km/h\n"
            f"湿度：{now['humidity']}%"
        )
        if not os.path.exists(icon_path):
            print(f"Warning: Icon file not found at {icon_path}")
            await weather_handler.finish(Message(MessageSegment.text(reply_1 + reply_2)))
            return
        
        reply = Message(
            MessageSegment.text(reply_1)+
            MessageSegment.image(file=icon_path) +
            MessageSegment.text(reply_2)
        )
        await weather_handler.finish(Message(reply)) 

    except httpx.HTTPStatusError:
        await weather_handler.finish(f"哎呀，茉子找不到叫 '{city}' 的地方... 你是不是写错啦？")
    except FinishedException:
        await weather_handler.finish("(●ˇ∀ˇ●)嘿嘿，查询完毕了~")
    except Exception as e:
        print(f"查询天气时发生错误: {e}")
        await weather_handler.finish("呜呜，天气服务器好像罢工了，茉子也查不到啦~")