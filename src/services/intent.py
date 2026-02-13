from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.services.search import extract_urls


@dataclass
class IntentDecision:
    name: str
    args: Dict[str, str]


def _extract_target_lang(text: str) -> str:
    text_lower = text.lower()
    if "英文" in text or "英语" in text or "english" in text_lower:
        return "EN"
    if "日文" in text or "日语" in text or "japanese" in text_lower:
        return "JA"
    if "韩文" in text or "韩语" in text or "korean" in text_lower:
        return "KO"
    if "中文" in text or "汉语" in text:
        return "ZH"
    return "ZH"


def decide_intents(
    text: str,
    has_image: bool,
    has_audio: bool,
    face_ids: Optional[List[int]] = None,
) -> List[IntentDecision]:
    intents: List[IntentDecision] = []
    clean = text.strip()
    lower = clean.lower()
    urls = extract_urls(clean)
    face_ids = face_ids or []

    if has_image and any(token in clean for token in ["看图", "图里", "这张图", "图片里", "识图"]):
        intents.append(IntentDecision(name="image.describe", args={}))

    if has_image and any(token in clean for token in ["灰度", "黑白", "模糊", "缩放", "resize"]):
        operation = "grayscale" if ("灰度" in clean or "黑白" in clean) else "blur"
        if "缩放" in clean or "resize" in lower:
            operation = "resize"
        value_match = re.search(r"(\d{2,4}[xX\*]\d{2,4}|\d{2,4})", clean)
        intents.append(
            IntentDecision(
                name="image.process",
                args={
                    "operation": operation,
                    "value": value_match.group(1) if value_match else "",
                },
            )
        )

    if any(token in clean for token in ["画图", "生成图片", "来一张图", "画一张", "生成一张图"]):
        prompt = re.sub(r"^(请|帮我|给我)?(画图|生成图片|来一张图|画一张|生成一张图)[:：]?", "", clean).strip()
        intents.append(IntentDecision(name="image.generate", args={"prompt": prompt or clean}))

    if any(token in clean for token in ["翻译", "译成", "翻成"]):
        target_lang = _extract_target_lang(clean)
        source = re.sub(r".*(翻译|译成|翻成)\s*", "", clean).strip() or clean
        intents.append(IntentDecision(name="language.translate", args={"text": source, "target_lang": target_lang}))

    if any(token in clean for token in ["什么语言", "语种", "language detect", "识别语言"]):
        intents.append(IntentDecision(name="language.detect", args={"text": clean}))

    if any(token in clean for token in ["念一下", "读出来", "语音播报", "转语音"]):
        content = re.sub(r".*(念一下|读出来|语音播报|转语音)[:：]?", "", clean).strip() or clean
        intents.append(IntentDecision(name="language.tts", args={"text": content}))

    if has_audio and any(token in clean for token in ["转文字", "语音转文字", "听写"]):
        intents.append(IntentDecision(name="language.stt", args={}))

    if any(token in clean for token in ["好感度", "亲密度"]):
        intents.append(IntentDecision(name="affinity.query", args={}))

    if face_ids and any(token in clean for token in ["表情", "情绪", "啥意思"]):
        intents.append(IntentDecision(name="emoji.analyze", args={}))

    if any(token in clean for token in ["记笔记", "记一下", "帮我记住", "备忘"]) and len(clean) > 4:
        payload = re.sub(r"^(记笔记|记一下|帮我记住|备忘)[:：]?", "", clean).strip()
        title = payload[:16] if payload else "未命名笔记"
        intents.append(IntentDecision(name="note.add", args={"title": title, "content": payload or clean}))

    if any(token in clean for token in ["查笔记", "看笔记", "笔记列表", "我记了什么"]):
        keyword = re.sub(r"^(查笔记|看笔记|笔记列表|我记了什么)[:：]?", "", clean).strip()
        intents.append(IntentDecision(name="note.query", args={"keyword": keyword}))

    if any(token in clean for token in ["删笔记", "删除笔记"]):
        key = re.sub(r"^(删笔记|删除笔记)[:：]?", "", clean).strip()
        intents.append(IntentDecision(name="note.delete", args={"keyword": key}))

    if any(token in clean for token in ["改笔记", "修改笔记", "更新笔记"]):
        payload = re.sub(r"^(改笔记|修改笔记|更新笔记)[:：]?", "", clean).strip()
        if "->" in payload:
            left, right = payload.split("->", 1)
            intents.append(IntentDecision(name="note.update", args={"keyword": left.strip(), "content": right.strip()}))

    if any(token in clean for token in ["地图", "在哪", "周边", "路线", "怎么去", "高德"]):
        intents.append(IntentDecision(name="map.query", args={"text": clean}))

    if any(token in clean for token in ["天气", "气温"]):
        intents.append(IntentDecision(name="weather.query", args={"text": clean}))

    if urls and any(token in clean for token in ["总结", "摘要", "链接内容", "这篇讲了什么"]):
        intents.append(IntentDecision(name="search.summarize_url", args={"url": urls[0]}))
    elif any(token in clean for token in ["搜索", "查一下", "最新", "新闻", "google"]):
        query = re.sub(r"^(搜索|查一下|google|最新|新闻)[:：]?", "", clean).strip() or clean
        intents.append(IntentDecision(name="search.web", args={"query": query}))

    return intents
