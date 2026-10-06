from __future__ import annotations

from dataclasses import dataclass
from typing import List


FACE_EMOTION_MAP = {
    14: ("微笑", "positive", 1),
    66: ("爱心", "positive", 2),
    74: ("太阳", "positive", 1),
    1: ("撇嘴", "negative", -1),
    2: ("色", "positive", 1),
    4: ("得意", "positive", 1),
    6: ("害羞", "neutral", 0),
    9: ("流泪", "negative", -2),
    11: ("尴尬", "negative", -1),
    21: ("可爱", "positive", 1),
    32: ("惊讶", "neutral", 0),
    39: ("骂人", "negative", -3),
    50: ("大笑", "positive", 2),
    75: ("衰", "negative", -1),
}

TEXT_EMOTION_MAP = {
    "哈哈": ("开心", "positive", 1),
    "嘻嘻": ("开心", "positive", 1),
    "呜呜": ("难过", "negative", -1),
    "生气": ("愤怒", "negative", -2),
    "谢谢": ("感谢", "positive", 1),
    "爱你": ("亲密", "positive", 2),
}


@dataclass
class EmojiAnalysis:
    labels: List[str]
    sentiment: str
    affinity_delta: int


def analyze_emoji(face_ids: List[int], text: str) -> EmojiAnalysis:
    labels: List[str] = []
    score = 0

    for face_id in face_ids:
        if face_id in FACE_EMOTION_MAP:
            label, _, delta = FACE_EMOTION_MAP[face_id]
            labels.append(label)
            score += delta

    lower = text.lower()
    for token, (label, _, delta) in TEXT_EMOTION_MAP.items():
        if token in lower:
            labels.append(label)
            score += delta

    if score > 0:
        sentiment = "positive"
    elif score < 0:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return EmojiAnalysis(labels=labels, sentiment=sentiment, affinity_delta=score)
