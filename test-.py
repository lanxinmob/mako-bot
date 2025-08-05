from nonebot import get_bot
import random
import requests

def fetch_tianxin(api_name,limit=2):
    try:
        url = f"https://api.tianapi.com/{api_name}/index"
        payload={"key":'96455cb0e4d72f63162dfce7448d67a4',"num":limit}
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
    
game_news = fetch_tianxin(api_name='game',limit=10)
anime_news = fetch_tianxin(api_name='dongman',limit=10)
social_news = fetch_tianxin(api_name='social',limit=10)

from nonebot.adapters.onebot.v11 import Message, MessageSegment
def format_section(title: str, news: list) -> MessageSegment:
        segment = MessageSegment.text(f"\n{title}\n") # 板块标题
        if not news:
            segment += MessageSegment.text("    欸~？这个板块今天居然是空空如也啊…… ( ´･ω･)\n")
        else:
            for item in news:
                # 把标题、点评、URL都作为独立的纯文本段添加
                segment += MessageSegment.text(f"({news.index(item)+1}) 这篇《{item['title']}》看起来很有趣！\n")
                segment += MessageSegment.text(f"    茉子点评：{item['description']}\n")
                # 【最关键】URL自己单独作为一段纯文本，最大程度保证可点击
                segment += MessageSegment.text(f"{item['url']}\n")
        return segment

msg = format_section("📰 最后也稍微关心一下现实世界吧！", social_news)

print(repr(msg))