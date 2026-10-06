from __future__ import annotations

import json
import re
from typing import Literal, Optional

from src.services.delivery.dedup import canonical_intent
from .models import AutonomyDecision, TargetHint, WhitelistCommand

QQ_ID_PATTERN = re.compile(r"(?<!\d)([1-9]\d{4,11})(?!\d)")


def extract_json_object(text: str) -> dict:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("LLM did not return a JSON object")
    return json.loads(match.group(0))

def parse_decision(data: dict) -> AutonomyDecision:
    action = data.get("action", "silent")
    target_type = data.get("target_type", "none")
    risk = data.get("risk", "high")
    if action not in {"speak", "ask_owner", "silent"}:
        action = "silent"
    if target_type not in {"group", "private", "none"}:
        target_type = "none"
    if risk not in {"low", "medium", "high"}:
        risk = "high"
    target_id = data.get("target_id")
    try:
        target_id = int(target_id) if target_id not in (None, "", "none") else None
    except (TypeError, ValueError):
        target_id = None
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return AutonomyDecision(
        action=action,
        target_type=target_type,
        target_id=target_id,
        confidence=confidence,
        risk=risk,
        message=str(data.get("message") or "").strip(),
        reason=str(data.get("reason") or "没有给出原因").strip(),
        intent=canonical_intent(str(data.get("intent") or "other"), str(data.get("message") or "")),
    )

def extract_target_hint(text: str) -> TargetHint:
    matches = list(QQ_ID_PATTERN.finditer(text))
    if not matches:
        return TargetHint("none", None, False, "没有显式 QQ 号")
    if len(matches) > 1:
        ids = ", ".join(match.group(1) for match in matches)
        return TargetHint("none", None, True, f"检测到多个 QQ 号: {ids}")

    match = matches[0]
    target_id = int(match.group(1))
    before = text[max(0, match.start() - 8) : match.start()]
    after = text[match.end() : min(len(text), match.end() + 8)]
    window = before + match.group(1) + after
    private_words = ("和", "跟", "对", "给", "向", "找", "私聊", "说", "问候", "晚安", "早安")
    group_words = ("群", "群号", "群聊")

    if any(word in window for word in group_words) and not any(word in before[-4:] for word in private_words):
        return TargetHint("group", target_id, False, f"显式群号 {target_id}")
    return TargetHint("private", target_id, False, f"显式私聊对象 {target_id}")

def sanitize_message_text(message: str) -> str:
    message = message.strip()
    message = re.sub(r"\*\*(.*?)\*\*", r"\1", message)
    message = re.sub(r"^\s*[-*]\s+", "", message, flags=re.M)
    return message.strip()

def message_needs_polish(message: str) -> bool:
    compact = re.sub(r"\s+", "", message)
    return len(compact) < 24 or "**" in message or message.count("\n") > 4

def parse_whitelist_command(text: str) -> Optional[WhitelistCommand]:
    stripped = text.strip()
    if "白名单" not in stripped:
        return None

    private_markers = ("私聊", "好友", "用户", "QQ")
    group_markers = ("群白名单", "群聊白名单", "群组白名单", "群号", "群聊")

    target_type: Literal["group", "private"] = "private"
    if any(marker in stripped for marker in group_markers) or (
        "群" in stripped and not any(marker in stripped for marker in private_markers)
    ):
        target_type = "group"
    elif any(marker in stripped for marker in private_markers):
        target_type = "private"

    ids = [int(match.group(1)) for match in QQ_ID_PATTERN.finditer(stripped)]
    if any(word in stripped for word in ("查看", "列出", "看看", "显示", "有哪些")):
        return WhitelistCommand("list", target_type, [])
    if any(word in stripped for word in ("加入", "添加", "允许", "授权", "设为", "设定", "加进", "放进")):
        return WhitelistCommand("add", target_type, ids) if ids else None
    if any(word in stripped for word in ("移除", "删除", "取消", "去掉", "踢出", "拿掉")):
        return WhitelistCommand("remove", target_type, ids) if ids else None
    return None

def looks_like_suggestion(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    keywords = (
        "建议",
        "可以去",
        "要不要去",
        "如果合适",
        "你想不想",
        "你可以",
        "去群里",
        "在群里",
        "群里",
        "跟他说",
        "跟她说",
        "私聊",
        "主动",
    )
    if any(keyword in stripped for keyword in keywords):
        return True

    target_words = ("群", "大家", "朋友", "好友", "同学", "他们", "她们")
    action_words = ("说", "发", "问", "提醒", "告诉", "安慰", "关心", "问候", "晚安", "早安", "吐槽")
    return any(target in stripped for target in target_words) and any(
        action in stripped for action in action_words
    )

def approval_command(text: str) -> Optional[tuple[str, Optional[str]]]:
    stripped = text.strip()
    if stripped in {"批准", "同意", "可以", "发吧"}:
        return ("approve", None)
    if stripped in {"取消", "算了", "别发", "不要发"}:
        return ("cancel", None)
    if stripped.startswith("改成"):
        replacement = stripped.removeprefix("改成").strip()
        if replacement:
            return ("rewrite", replacement)
    return None


def reconciliation_command(text: str) -> Optional[tuple[str, str]]:
    match = re.fullmatch(r"行动状态\s+([A-Za-z0-9_-]{1,64})", text.strip())
    if match:
        return "inspect", match[1]
    match = re.fullmatch(r"行动核对\s+([A-Za-z0-9_-]{1,64})\s+(已送达|放弃)", text.strip())
    if match:
        return ("sent" if match[2] == "已送达" else "cancelled"), match[1]
    return None
