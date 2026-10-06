"""Small in-memory images; no network or shared mutable state."""
from io import BytesIO
from PIL import Image


def _make_pil_image(width: int, height: int) -> Image.Image:
    """Return an in-memory RGB PIL image of the requested size without disk I/O."""
    return Image.new("RGB", (width, height))


def _make_jpeg_bytes(width: int = 100, height: int = 80) -> bytes:
    """Return valid JPEG bytes for a simple in-memory image."""
    img = _make_pil_image(width, height)
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png_bytes(width: int = 100, height: int = 80) -> bytes:
    buf = BytesIO()
    _make_pil_image(width, height).save(buf, format="PNG")
    return buf.getvalue()
