from nonebot import get_bot
import random
import os
import requests
from nonebot.log import logger
import asyncio
import json
import redis
from nonebot_plugin_apscheduler import scheduler
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from datetime import datetime,timedelta
import vector_db
import chat

@scheduler.scheduled_job("cron", hour=22, minute=0)
async def precipitate_knowledge():

    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    all_logs = redis_client.lrange("all_memory",0,-1)

    logs = []
    past_time = datetime.now()-timedelta(days=1)
    for log in all_logs:
        log = json.loads(log)
        log_time = datetime.fromisoformat(log["time"])
        if log_time>=past_time:
            logs.append(log)

    try:
        messages_for_api = [
            {"role": "system", "content": """
             你是一个信息分析专家。请从以下的聊天记录中，提取出所有客观事实、关键事件、用户偏好和重要结论。
            请遵循以下规则：
            - 忽略日常闲聊和无意义的对话。
            - 将每一条提炼出的知识点写成一个独立、完整的句子。
            - 如果是针对某个用户的，请明确指出。
            - 以无序列表的格式输出。

            聊天记录如下：
            """}]
        for log in logs:
            if log["role"] =="user":
               message= f"【{log["nickname"]}_{log["user_id"]}】：{log["content"]}"
               messages_for_api.append({"role":"user","content":message})
            messages_for_api.append({"role":"assistant","content":log["content"]})

        response = await asyncio.wait_for(
            chat.client.chat.completions.create(
                model="deepseek-chat", 
                messages=messages_for_api,
                temperature=0.5,
                max_tokens=2048
            ),
            timeout=30.0 
        )
        reply_text = response.choices[0].message.content.strip()
        
        knowledge_points:list[str] = []
        for line in reply_text.split("\n"):
            line = line.strip(".- ").strip()
            if line:
                knowledge_points.append(line)
        if not knowledge_points:
           print("没有提炼出知识点。")
           return  
        
        vector_db.create_db()
        for point in knowledge_points: 
            vector_db.add_to_db(point)
        logger.success(f"成功沉淀{len(knowledge_points)}条知识加入存储队列")


        PROFILE_PREFIX = "user_profile:"

        user_id = {log["user_id"] for log in logs if log["role"]=="user"}
        for uid in user_id:
            user_log = [log for log in logs if log["user_id"]==uid]
            nickname = user_log[0]["nickname"]
            chat_log = [log["content"] for log in user_log ]
            key = f"{PROFILE_PREFIX}{uid}"
            old_profile = redis_client.get(key)
            if old_profile:
                old_profile = json.loads(old_profile)
                prompt_user = f"""
                以下是你对用户 {nickname}({uid}) 的历史画像：
                {old_profile}

                以下是该用户在最近一天的发言记录：
                {chat_log}

                请基于历史画像 + 新的发言，更新用户画像，保持相同格式并合理融合：
                【核心特质】
                【行为模式】
                【关系定位】
                【茉子认知画像】
                """ 
            else:    
                prompt_user = f"""
                请根据用户 {nickname} ({uid}) 最近24小时的发言,  
                从你的视角总结这个用户的画像，按照以下模板输出：
                【核心特质】
                【行为模式】
                【关系定位】
                【茉子认知画像】
                以下是该用户在最近一天的发言记录：
                {chat_log}
                """
            response = await asyncio.wait_for(
                chat.client.chat.completions.create(
                    model="deepseek-chat", 
                    messages=[
                        {"role": "system", "content": "你是千恋万花中的常陆茉子，一个有点小恶魔性格、喜欢捉弄人但内心善良的女生"},
                        {"role": "user", "content": prompt_user}],
                    temperature=0.5,
                    max_tokens=2048
                ),
                timeout=30.0 
            )
            profile_text = response.choices[0].message.content.strip()
            user_profile = {
                "user_id": id,
                "nickname": nickname,
                "profile_text": profile_text,
                "last_updated": datetime.now().isoformat(),
            }
            redis_client.set(key,json.dumps(user_profile))

    except asyncio.TimeoutError:
        print("知识沉淀任务超时。")
        return
    except Exception as e:
        print(f"调用LLM出错: {e}")
        return

