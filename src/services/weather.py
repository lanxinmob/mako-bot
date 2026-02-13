from __future__ import annotations

from typing import Dict

from src.core.config import get_settings
from src.core.errors import NotConfiguredError
from src.services.http import fetch_json


async def lookup_city(city: str) -> Dict[str, str]:
    settings = get_settings()
    if not settings.qweather_host or not settings.qweather_key:
        raise NotConfiguredError("QWEATHER_HOST / QWEATHER_KEY is not configured.")
    data = await fetch_json(
        f"https://{settings.qweather_host}/geo/v2/city/lookup",
        params={"location": city, "key": settings.qweather_key},
    )
    if data.get("code") != "200" or not data.get("location"):
        return {}
    item = data["location"][0]
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "country": item.get("country", ""),
    }


async def get_weather(city: str) -> Dict[str, str]:
    settings = get_settings()
    location = await lookup_city(city)
    if not location:
        return {}
    data = await fetch_json(
        f"https://{settings.qweather_host}/v7/weather/now",
        params={"location": location["id"], "key": settings.qweather_key},
    )
    if data.get("code") != "200":
        return {}
    now = data.get("now", {})
    return {
        "city": location["name"],
        "country": location["country"],
        "text": now.get("text", ""),
        "temp": now.get("temp", ""),
        "feels_like": now.get("feelsLike", ""),
        "wind_dir": now.get("windDir", ""),
        "wind_speed": now.get("windSpeed", ""),
        "humidity": now.get("humidity", ""),
        "icon": now.get("icon", ""),
    }
