from __future__ import annotations

from typing import Dict, List, Optional

from src.core.config import get_settings
from src.core.errors import NotConfiguredError
from src.services.http import fetch_json


def _ensure_key() -> str:
    key = get_settings().amap_key
    if not key:
        raise NotConfiguredError("AMAP_KEY is not configured.")
    return key


async def geocode(address: str, city: Optional[str] = None) -> Dict[str, str]:
    key = _ensure_key()
    data = await fetch_json(
        "https://restapi.amap.com/v3/geocode/geo",
        params={"key": key, "address": address, "city": city or ""},
    )
    geocodes = data.get("geocodes", [])
    if not geocodes:
        return {}
    item = geocodes[0]
    return {
        "formatted_address": item.get("formatted_address", ""),
        "location": item.get("location", ""),
        "province": item.get("province", ""),
        "city": item.get("city", ""),
        "district": item.get("district", ""),
    }


async def search_poi(keyword: str, city: Optional[str] = None, limit: int = 5) -> List[dict]:
    key = _ensure_key()
    data = await fetch_json(
        "https://restapi.amap.com/v3/place/text",
        params={"key": key, "keywords": keyword, "city": city or "", "offset": limit, "page": 1},
    )
    pois = data.get("pois", [])
    result: List[dict] = []
    for item in pois[:limit]:
        result.append(
            {
                "name": item.get("name", ""),
                "address": item.get("address", ""),
                "location": item.get("location", ""),
                "type": item.get("type", ""),
            }
        )
    return result


async def plan_route(origin: str, destination: str, mode: str = "walking") -> Dict[str, str]:
    key = _ensure_key()
    path = {
        "walking": "https://restapi.amap.com/v3/direction/walking",
        "driving": "https://restapi.amap.com/v3/direction/driving",
        "transit": "https://restapi.amap.com/v3/direction/transit/integrated",
    }.get(mode, "https://restapi.amap.com/v3/direction/walking")

    data = await fetch_json(
        path,
        params={"key": key, "origin": origin, "destination": destination, "city": ""},
    )

    route = data.get("route", {})
    paths = route.get("paths", [])
    if not paths:
        transits = route.get("transits", [])
        if transits:
            first = transits[0]
            return {
                "distance": first.get("distance", ""),
                "duration": first.get("duration", ""),
                "detail": "公交换乘方案已生成",
            }
        return {}
    first = paths[0]
    return {
        "distance": first.get("distance", ""),
        "duration": first.get("duration", ""),
        "detail": first.get("strategy", "路线规划完成"),
    }
