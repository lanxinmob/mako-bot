from __future__ import annotations

import asyncio
import warnings
from io import BytesIO
from typing import Optional, Tuple

import httpx
from nonebot.log import logger
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from src.core.config import get_settings
from src.core.errors import NotConfiguredError
from src.services.llm import get_openai_client, has_openai

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


async def describe_image_url(image_url: str) -> str:
    settings = get_settings()
    if not has_openai():
        raise NotConfiguredError("OPENAI_API_KEY is not configured.")
    client = get_openai_client()
    response = await client.chat.completions.create(
        model=settings.vision_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请用简洁中文描述这张图片的内容。"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        max_tokens=256,
    )
    return response.choices[0].message.content.strip()


async def generate_image(prompt: str) -> str:
    settings = get_settings()
    if not has_openai():
        raise NotConfiguredError("OPENAI_API_KEY is not configured.")
    client = get_openai_client()
    response = await client.images.generate(
        model=settings.image_model,
        prompt=prompt,
        size=settings.image_size,
    )
    return response.data[0].url


async def download_image_bytes(url: str) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def _parse_resize_value(value: str) -> Tuple[Optional[int], Optional[int]]:
    cleaned = value.strip().lower().replace("*", "x")
    if "x" in cleaned:
        parts = [part for part in cleaned.split("x") if part]
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])
        return None, None
    if cleaned.isdigit():
        return int(cleaned), None
    return None, None


def _process_image_sync(image_bytes: bytes, operation: str, value: Optional[str] = None) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(image_bytes))
            image.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        logger.error(f"Invalid image payload: {exc}")
        return b""
    except Exception as exc:
        logger.error(f"Failed to open image: {exc}")
        return b""

    has_alpha = image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if image.mode == "P" and "transparency" in image.info:
        image = image.convert("RGBA")
        has_alpha = True

    op = operation.lower()
    if op == "grayscale":
        alpha = None
        if has_alpha and image.mode == "RGBA":
            alpha = image.split()[-1]
        gray = ImageOps.grayscale(image.convert("RGB"))
        if alpha is not None:
            image = Image.merge("RGBA", (gray, gray, gray, alpha))
        else:
            image = gray.convert("RGB")
    elif op == "blur":
        image = image.filter(ImageFilter.GaussianBlur(radius=2))
    elif op == "resize" and value:
        width, height = _parse_resize_value(value)
        if width and height:
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
        elif width:
            ratio = width / max(1, image.width)
            new_height = max(1, int(image.height * ratio))
            image = image.resize((width, new_height), Image.Resampling.LANCZOS)
        else:
            logger.warning(f"Resize skipped due to invalid value: {value}")
    else:
        logger.warning(f"Unknown image operation: {operation}")

    buffer = BytesIO()
    if has_alpha:
        image.save(buffer, format="PNG")
    else:
        image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


async def process_image(image_bytes: bytes, operation: str, value: Optional[str] = None) -> bytes:
    return await asyncio.to_thread(_process_image_sync, image_bytes, operation, value)
