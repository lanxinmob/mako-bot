from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from nonebot.adapters.onebot.v11 import Message


def _pick_url(data: dict) -> str:
    for key in ("url", "file", "path"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _truncate(text: str, max_len: int = 180) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


@dataclass
class NormalizedMessage:
    plain_text: str = ""
    segment_summary: str = ""
    segment_types: List[str] = field(default_factory=list)
    image_urls: List[str] = field(default_factory=list)
    audio_urls: List[str] = field(default_factory=list)
    video_urls: List[str] = field(default_factory=list)
    face_ids: List[int] = field(default_factory=list)
    urls: List[str] = field(default_factory=list)

    @property
    def has_non_text(self) -> bool:
        return any(t != "text" for t in self.segment_types)

    def build_user_text(self) -> str:
        text = self.plain_text.strip()
        summary = self.segment_summary.strip()
        if text and summary:
            return f"{text}\n\n[消息段信息]\n{summary}"
        if text:
            return text
        if summary:
            return f"我发送了非文本消息。\n{summary}"
        return ""


def normalize_message(message: Message) -> NormalizedMessage:
    text_parts: List[str] = []
    summary_lines: List[str] = []

    norm = NormalizedMessage()
    for seg in message:
        seg_type = seg.type
        data = seg.data or {}
        norm.segment_types.append(seg_type)

        if seg_type == "text":
            part = str(data.get("text", ""))
            if part:
                text_parts.append(part)
                for url in re.findall(r"https?://[^\s]+", part):
                    norm.urls.append(url)
            continue

        if seg_type == "image":
            url = _pick_url(data)
            if url:
                norm.image_urls.append(url)
                norm.urls.append(url)
            summary_lines.append(f"- image: {url or '[no-url]'}")
            continue

        if seg_type == "record":
            url = _pick_url(data)
            if url:
                norm.audio_urls.append(url)
                norm.urls.append(url)
            summary_lines.append(f"- record: {url or '[no-url]'}")
            continue

        if seg_type == "video":
            url = _pick_url(data)
            if url:
                norm.video_urls.append(url)
                norm.urls.append(url)
            summary_lines.append(f"- video: {url or '[no-url]'}")
            continue

        if seg_type == "face":
            face_id = data.get("id")
            try:
                if face_id is not None:
                    norm.face_ids.append(int(face_id))
            except ValueError:
                pass
            summary_lines.append(f"- face: id={face_id}")
            continue

        if seg_type == "at":
            qq = data.get("qq", "")
            summary_lines.append(f"- at: {qq}")
            continue

        if seg_type == "reply":
            rid = data.get("id", "")
            summary_lines.append(f"- reply: id={rid}")
            continue

        if seg_type == "file":
            name = data.get("name", "")
            file_id = data.get("file_id", "")
            size = data.get("file_size", "")
            summary_lines.append(f"- file: name={name} id={file_id} size={size}")
            continue

        if seg_type == "location":
            lat = data.get("lat", "")
            lon = data.get("lon", "")
            title = data.get("title", "")
            summary_lines.append(f"- location: {title} ({lat},{lon})")
            continue

        if seg_type in {"json", "xml", "markdown"}:
            payload = data.get("data") or data.get("content") or str(data)
            summary_lines.append(f"- {seg_type}: {_truncate(str(payload))}")
            continue

        if seg_type == "forward":
            summary_lines.append("- forward: merged messages")
            continue

        if seg_type == "contact":
            ctype = data.get("type", "")
            cid = data.get("id", "")
            summary_lines.append(f"- contact: type={ctype} id={cid}")
            continue

        summary_lines.append(f"- {seg_type}: {_truncate(str(data))}")

    norm.plain_text = "".join(text_parts).strip()
    norm.segment_summary = "\n".join(summary_lines).strip()
    return norm


def collect_image_urls(message: Message) -> List[str]:
    return normalize_message(message).image_urls


def collect_audio_urls(message: Message) -> List[str]:
    return normalize_message(message).audio_urls


def collect_face_ids(message: Message) -> List[int]:
    return normalize_message(message).face_ids


def find_city_in_text(text: str) -> Optional[str]:
    match = re.search(r"([^\s，。！？,.!?]{2,10})(?:天气|气温)", text)
    if match:
        return match.group(1)
    match = re.search(r"(?:天气|气温)\s*([^\s，。！？,.!?]{2,10})", text)
    if match:
        return match.group(1)
    return None
