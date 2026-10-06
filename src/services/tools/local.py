"""Notes, affinity, emoji and map/weather tool handling."""
from __future__ import annotations

from typing import Awaitable, Callable, List

from src.services.memory.affinity import AffinityService
from src.services.tools.intent import IntentDecision
from src.services.memory.notes import NoteService

from .dependencies import ToolDependencies
from .models import ToolExecutionResult


async def handle(
    decision: IntentDecision, result: ToolExecutionResult, user_id: int, text: str,
    face_ids: List[int], *, note_service: NoteService, affinity_service: AffinityService,
    handle_map_query: Callable[[ToolExecutionResult, str], Awaitable[None]],
    handle_weather_query: Callable[[ToolExecutionResult, str], Awaitable[None]],
    dependencies: ToolDependencies,
) -> bool:
    name = decision.name
    args = decision.args

    if name == "affinity.query":
        score = affinity_service.get_score(user_id)
        level = affinity_service.level(score)
        result.fact_lines.append(f"当前好感度: {score} ({level})")
        return True

    if name == "emoji.analyze":
        analysis = dependencies.analyze_emoji(face_ids, text)
        score = affinity_service.adjust(user_id, analysis.affinity_delta)
        labels = "、".join(analysis.labels) if analysis.labels else "无明显特征"
        result.fact_lines.append(f"表情识别: {labels}，情绪={analysis.sentiment}，好感度={score}")
        return True

    if name == "note.add":
        note = note_service.add_note(
            user_id=user_id,
            title=args.get("title", "未命名笔记"),
            content=args.get("content", text),
        )
        result.fact_lines.append(f"笔记已记录: {note.note_id}《{note.title}》")
        return True

    if name == "note.query":
        keyword = args.get("keyword", "")
        notes = (
            note_service.search_notes(user_id, keyword) if keyword else note_service.list_notes(user_id)
        )
        if not notes:
            result.fact_lines.append("笔记查询: 没有匹配内容。")
            return True
        top = notes[:5]
        formatted = "\n".join([f"- {n.note_id} | {n.title} | {n.content[:50]}" for n in top])
        result.fact_lines.append(f"笔记查询结果:\n{formatted}")
        return True

    if name == "note.delete":
        ok = note_service.delete_note(user_id, args.get("keyword", ""))
        result.fact_lines.append("笔记删除成功。" if ok else "笔记删除失败: 未找到目标。")
        return True

    if name == "note.update":
        updated = note_service.update_note(user_id, args.get("keyword", ""), args.get("content", ""))
        if updated:
            result.fact_lines.append(f"笔记更新成功: {updated.note_id}《{updated.title}》")
        else:
            result.fact_lines.append("笔记更新失败: 未找到目标。")
        return True

    if name == "map.query":
        await handle_map_query(result, args.get("text", text))
        return True

    if name == "weather.query":
        await handle_weather_query(result, args.get("text", text))
        return True

    return False


async def handle_map_query(result: ToolExecutionResult, text: str, *, dependencies: ToolDependencies) -> None:
    import re

    route_match = re.search(r"从(.+?)到(.+?)(怎么去|路线|路程|$)", text)
    if route_match:
        start = route_match.group(1).strip()
        end = route_match.group(2).strip()
        origin = await dependencies.geocode(start)
        destination = await dependencies.geocode(end)
        if not origin or not destination:
            result.fact_lines.append("地图查询: 起点或终点解析失败。")
            return
        route = await dependencies.plan_route(origin["location"], destination["location"], mode="walking")
        if not route:
            result.fact_lines.append("地图查询: 未获取到路线。")
            return
        result.fact_lines.append(
            f"路线规划: {start} -> {end}，距离 {route.get('distance')} 米，耗时 {route.get('duration')} 秒。"
        )
        return

    nearby_match = re.search(r"(.+?)附近(有什么|哪里有|有啥|)$", text)
    if nearby_match:
        keyword = nearby_match.group(1).strip() or "餐厅"
        pois = await dependencies.search_poi(keyword=keyword, limit=5)
        if not pois:
            result.fact_lines.append("地图查询: 未找到周边结果。")
            return
        lines = [f"- {p['name']} | {p['address']}" for p in pois]
        result.fact_lines.append("周边查询:\n" + "\n".join(lines))
        return

    target = text.replace("地图", "").replace("高德", "").replace("在哪", "").strip()
    if not target:
        return
    place = await dependencies.geocode(target)
    if not place:
        result.fact_lines.append("地图查询: 地址解析失败。")
        return
    result.fact_lines.append(
        f"地点信息: {place.get('formatted_address')}，坐标 {place.get('location')}。"
    )


async def handle_weather_query(result: ToolExecutionResult, text: str, *, dependencies: ToolDependencies) -> None:
    import re

    city_match = re.search(r"([^\s，。！？,.!?]{2,10})(?:天气|气温)", text)
    city = city_match.group(1) if city_match else "北京"
    weather = await dependencies.get_weather(city)
    if not weather:
        result.fact_lines.append(f"天气查询: 未找到 {city} 的天气。")
        return
    result.fact_lines.append(
        f"天气: {weather['country']}{weather['city']} {weather['text']}，"
        f"{weather['temp']}C，体感 {weather['feels_like']}C，湿度 {weather['humidity']}%。"
    )
