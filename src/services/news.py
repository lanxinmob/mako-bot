from __future__ import annotations

import random
from typing import List

import httpx

from src.core.config import get_settings


async def fetch_juejin(limit: int = 2) -> List[dict]:
    url = "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"
    payload = {"client_type": 2608, "cursor": "0", "id_type": 2, "limit": 20, "sort_type": 200}
    async with httpx.AsyncClient(timeout=20.0) as client:
        rep = await client.post(url, json=payload, headers={"User-Agent": "Mozilla/5.0"})
        rep.raise_for_status()
        data = rep.json().get("data", [])
    articles: List[dict] = []
    for item in data:
        if item.get("item_type") == 2:
            info = item.get("item_info", {}).get("article_info", {})
            articles.append(
                {
                    "title": info.get("title", "N/A"),
                    "description": info.get("brief_content", "..."),
                    "url": f"https://juejin.cn/post/{info.get('article_id', '')}",
                }
            )
            if len(articles) >= limit:
                break
    return articles


async def fetch_tianxin(api_name: str, limit: int = 2) -> List[dict]:
    key = get_settings().tianxin_key
    if not key:
        return []
    url = f"https://api.tianapi.com/{api_name}/index"
    async with httpx.AsyncClient(timeout=20.0) as client:
        rep = await client.post(url, data={"key": key, "num": max(limit, 5)})
        rep.raise_for_status()
        data = rep.json().get("newslist", [])
    if not data:
        return []
    picks = random.sample(data, k=min(limit, len(data)))
    return [
        {
            "title": item.get("title", "N/A"),
            "description": item.get("description", "N/A"),
            "url": item.get("url", "#"),
        }
        for item in picks
    ]
