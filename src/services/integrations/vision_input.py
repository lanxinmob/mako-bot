"""Safe inline images for the selected chat model."""
import asyncio
import base64
import warnings
from io import BytesIO

from PIL import Image

from .image import download_image_data, _validate_pil_dimensions


def native_vision_enabled(settings):
    if getattr(settings, "deepseek_api_key", None):
        return "vision" in getattr(settings, "deepseek_model", "").lower()
    return bool(getattr(settings, "openai_api_key", None))


def inline_image(content):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as image:
            _validate_pil_dimensions(image)
            mime = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif",
                    "WEBP": "image/webp"}.get(image.format)
            if mime is None:
                raise ValueError("unsupported image format")
            image.verify()
    return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")


async def prepare_native_image(url):
    # Existing URL validation, byte limits and timeout precede image decoding.
    content, _ = await download_image_data(url)
    return await asyncio.to_thread(inline_image, content)
