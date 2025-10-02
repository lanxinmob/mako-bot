from nonebot import get_bot
import random
import os
import requests
from nonebot_plugin_apscheduler import scheduler
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from dotenv import load_dotenv
load_dotenv()

@scheduler.scheduled_job("cron", hour=7, minute=0)
async def good_morning_mako():
    try:

        bot = get_bot()
        group_id = os.getenv("GROUP_ID")
        message  = [
        "早上好哦，各位~！今天也是元气满满的一天，有没有想念茉子大人呀？(｡>∀<｡)",
        "早上好！今天也是元气满满的一天哦~(｡>∀<｡)",
        "起床啦！别赖床，茉子等你来捣乱~(｀∀´)σ不然茉子要捉弄你了~(￣▽￣)σ",
        "太阳都晒屁股了，快起床和茉子一起学习~(｡>∀<｡)",
        ]
        await bot.send_group_msg(group_id=group_id, message=random.choice(message))
        
        print(f"已成功发送早安问候到群 {group_id}")
        
    except Exception as e:
        print(f"发送早安问候失败: {e}")

def fetch_juejin(limit=2):
    try:
        url = "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"
        payload = {"client_type": 2608, "cursor": "0", "id_type": 2, "limit": 20, "sort_type": 200}
        rep = requests.post(url,json=payload,headers={"User-Agent":"Mozilla/5.0"})
        rep.raise_for_status()
        rep = rep.json()
        data = rep.get("data",[])
        
        articles = []
        for item in data:
            if item.get("item_type") == 2:#内容是文章不是广告
                info = item.get("item_info", {})
                art_info = info.get("article_info", {})
                articles.append({
                    "title": art_info.get('title', 'N/A'),
                    "description": art_info.get('brief_content', '...'),
                    "url": f"https://juejin.cn/post/{art_info.get('article_id', '')}"
                })
                if len(articles) >= limit: break
        return articles

    except Exception as e:
        print(f"获取掘金文章失败：{e}")
        return []


def fetch_tianxin(api_name,limit=2):
    try:
        url = f"https://api.tianapi.com/{api_name}/index"
        payload={"key":os.getenv("tianxin_key"),"num":limit}
        rep = requests.post(url,data=payload)
        rep.raise_for_status()
        
        data = rep.json()
        data = data.get("newslist",[])
        item = random.choice(data)
        articles = []

        articles.append({
            "title":item.get("title","N/A"),
            "description":item.get("description","N/A"),
            "url":item.get("url","#")
        })
        return articles

    except Exception as e:
        print(f"获取天行数据失败 接口：{api_name} {e}")
        return []
   

@scheduler.scheduled_job("cron", hour=7, minute=10)
async def send_daily_digest():
    try:
        bot = get_bot()
        group_id = os.getenv("GROUP_ID")

        tech_news = fetch_juejin(limit=2)
        game_news = fetch_tianxin(api_name='game',limit=10)
        anime_news = fetch_tianxin(api_name='dongman',limit=10)
        social_news = fetch_tianxin(api_name='social',limit=10)

        message = Message()
        message.append("---\nଘ(੭ˊᵕˋ)੭* ੈ✩‧₊˚\n锵锵锵~！今日份的资讯快递到啦！\n")

        def format_section(title: str, news: list) -> MessageSegment:
                segment = MessageSegment.text(f"\n{title}\n")
                if not news:
                    segment += MessageSegment.text("    欸~？这个板块今天居然是空空如也啊…… ( ´･ω･)\n")
                else:
                    for item in news:
                        segment += MessageSegment.text(f"({news.index(item)+1}) 这篇《{item['title']}》看起来很有趣！\n")
                        segment += MessageSegment.text(f"    茉子点评：{item['description']}\n")
                        segment += MessageSegment.text(f"{item['url']}\n")
                return segment

        message.extend(format_section("🚀 首先是技术力超高的科技前沿！", tech_news))
        message.extend(format_section("🎮 GOGO！游戏玩家的专属情报！", game_news))
        message.extend(format_section("🌸 二次元浓度补充！今日新番和趣闻~", anime_news))
        message.extend(format_section("📰 最后也稍微关心一下现实世界吧！", social_news))

        message.append("\n\n好啦，今天的分享就到这里！茉子下线啦，拜拜~ (｡･ω･｡)ﾉ♡")
        message.append("---")

        #message = "\n".join(msg)
        await bot.send_group_msg(group_id=group_id, message=message)

    except Exception as e:
       print(f"未成功发送精选文章：{e}") 

from nonebot import on_command
from nonebot.matcher import Matcher 

daily_news_matcher = on_command("精选文章", aliases={"news","今日新闻", "日报"}, priority=5, block=True)
@daily_news_matcher.handle()
async def _(matcher:Matcher):
    await matcher.send("茉子正在努力搜集最新的资讯，请稍等片刻哦...")
    try:
        tech_news = fetch_juejin(limit=2)
        game_news = fetch_tianxin(api_name='game',limit=10)
        anime_news = fetch_tianxin(api_name='dongman',limit=10)
        social_news = fetch_tianxin(api_name='social',limit=10)

        message = Message()
        message.append("---\nଘ(੭ˊᵕˋ)੭* ੈ✩‧₊˚\n锵锵锵~！今日份的资讯快递到啦！\n")

        def format_section(title: str, news: list) -> MessageSegment:
                segment = MessageSegment.text(f"\n{title}\n")
                if not news:
                    segment += MessageSegment.text("    欸~？这个板块今天居然是空空如也啊…… ( ´･ω･)\n")
                else:
                    for item in news:
                        segment += MessageSegment.text(f"({news.index(item)+1}) 这篇《{item['title']}》看起来很有趣！\n")
                        segment += MessageSegment.text(f"    茉子点评：{item['description']}\n")
                        segment += MessageSegment.text(f"{item['url']}\n")
                return segment

        message.extend(format_section("🚀 首先是技术力超高的科技前沿！", tech_news))
        message.extend(format_section("🎮 GOGO！游戏玩家的专属情报！", game_news))
        message.extend(format_section("🌸 二次元浓度补充！今日新番和趣闻~", anime_news))
        message.extend(format_section("📰 最后也稍微关心一下现实世界吧！", social_news))

        message.append("\n\n好啦，今天的分享就到这里！茉子下线啦，拜拜~ (｡･ω･｡)ﾉ♡")
        message.append("---")

        await matcher.send(message)

    except Exception as e:
       print(f"未成功发送精选文章：{e}") 


from nonebot import on_command
from nonebot.matcher import Matcher

@on_command("bilibili").handle()
async def _(matcher: Matcher):
    url = "https://www.bilibili.com/"
    await matcher.send(f"这是b站：\n{url}")
