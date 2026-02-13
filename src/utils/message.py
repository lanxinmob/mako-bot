from __future__ import annotations

import re
from typing import List, Optional

from nonebot.adapters.onebot.v11 import Message


def collect_image_urls(message: Message) -> List[str]:
    urls: List[str] = []
    for seg in message:
        if seg.type == "image":
            url = seg.data.get("url") or seg.data.get("file")
            if url:
                urls.append(url)
    return urls


def collect_audio_urls(message: Message) -> List[str]:
    urls: List[str] = []
    for seg in message:
        if seg.type == "record":
            url = seg.data.get("url") or seg.data.get("file")
            if url:
                urls.append(url)
    return urls


def collect_face_ids(message: Message) -> List[int]:
    ids: List[int] = []
    for seg in message:
        if seg.type == "face":
            face_id = seg.data.get("id")
            if face_id is None:
                continue
            try:
                ids.append(int(face_id))
            except ValueError:
                continue
    return ids


def find_city_in_text(text: str) -> Optional[str]:
    match = re.search(r"([^\s，。！？,.!?]{2,10})(?:天气|气温)", text)
    if match:
        return match.group(1)
    match = re.search(r"(?:天气|气温)\s*([^\s，。！？,.!?]{2,10})", text)
    if match:
        return match.group(1)
    return None
