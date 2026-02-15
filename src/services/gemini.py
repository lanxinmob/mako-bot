from __future__ import annotations

import base64

import httpx

from src.core.config import get_settings
from src.core.errors import ExternalServiceError, NotConfiguredError


def has_gemini() -> bool:
    return bool(get_settings().gemini_api_key)


async def describe_image_with_gemini(
    image_bytes: bytes,
    mime_type: str,
    prompt: str = "请用简洁中文描述这张图片的内容。",
) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise NotConfiguredError("GEMINI_API_KEY is not configured.")

    model = settings.gemini_vision_model
    endpoint = f"{settings.gemini_base_url}/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64.b64encode(image_bytes).decode("utf-8"),
                        }
                    },
                ]
            }
        ]
    }
    async with httpx.AsyncClient(timeout=40.0) as client:
        resp = await client.post(endpoint, params={"key": settings.gemini_api_key}, json=payload)
        resp.raise_for_status()
        data = resp.json()

    candidates = data.get("candidates", [])
    if not candidates:
        raise ExternalServiceError(f"Gemini returned empty candidates: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise ExternalServiceError(f"Gemini returned empty text: {data}")
    return text
