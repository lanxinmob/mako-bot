from __future__ import annotations

import hashlib
import random
import tempfile
from pathlib import Path
from typing import Optional

from src.core.config import get_settings
from src.core.errors import ExternalServiceError, NotConfiguredError
from src.services.http import fetch_json
from src.services.llm import get_openai_client, has_openai


def detect_language(text: str) -> str:
    if not text.strip():
        return "unknown"
    zh = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    en = sum(1 for ch in text if "a" <= ch.lower() <= "z")
    ja = sum(1 for ch in text if "\u3040" <= ch <= "\u30ff")
    ko = sum(1 for ch in text if "\uac00" <= ch <= "\ud7af")
    stats = {"zh": zh, "en": en, "ja": ja, "ko": ko}
    return max(stats, key=stats.get) if max(stats.values()) > 0 else "unknown"


async def translate_text(text: str, target_lang: str = "ZH") -> str:
    settings = get_settings()
    if settings.deepl_key:
        data = await fetch_json(
            "https://api-free.deepl.com/v2/translate",
            method="POST",
            data={"auth_key": settings.deepl_key, "text": text, "target_lang": target_lang.upper()},
        )
        translations = data.get("translations", [])
        if translations:
            return translations[0].get("text", "")
        raise ExternalServiceError("DeepL returned empty result.")

    if settings.baidu_translate_appid and settings.baidu_translate_key:
        salt = str(random.randint(10000, 99999))
        sign_raw = f"{settings.baidu_translate_appid}{text}{salt}{settings.baidu_translate_key}"
        sign = hashlib.md5(sign_raw.encode("utf-8")).hexdigest()
        data = await fetch_json(
            "https://fanyi-api.baidu.com/api/trans/vip/translate",
            method="GET",
            params={
                "q": text,
                "from": "auto",
                "to": target_lang.lower(),
                "appid": settings.baidu_translate_appid,
                "salt": salt,
                "sign": sign,
            },
        )
        results = data.get("trans_result", [])
        if results:
            return "\n".join(item.get("dst", "") for item in results)
        raise ExternalServiceError("Baidu translate returned empty result.")

    if has_openai():
        client = get_openai_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a translator. Return only translated text.",
                },
                {
                    "role": "user",
                    "content": f"Translate to {target_lang}: {text}",
                },
            ],
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()

    raise NotConfiguredError("No translation provider configured.")


async def speech_to_text(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    if not has_openai():
        raise NotConfiguredError("OPENAI_API_KEY is not configured.")
    client = get_openai_client()
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix or ".wav") as f:
        f.write(audio_bytes)
        temp_path = Path(f.name)
    try:
        with temp_path.open("rb") as audio_file:
            result = await client.audio.transcriptions.create(
                model=get_settings().stt_model,
                file=audio_file,
            )
        return result.text
    finally:
        temp_path.unlink(missing_ok=True)


async def text_to_speech(text: str) -> bytes:
    if not has_openai():
        raise NotConfiguredError("OPENAI_API_KEY is not configured.")
    settings = get_settings()
    client = get_openai_client()
    response = await client.audio.speech.create(
        model=settings.tts_model,
        voice=settings.tts_voice,
        input=text,
    )
    return response.read()
