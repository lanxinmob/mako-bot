"""Small transport-free response and safe rendering of external metadata."""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class DiscoveryReply:
    text: str
    image_url: str | None = None


def clean(value: object, limit: int = 180) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).replace("[CQ:", "［CQ:").replace("\x00", "")[:limit].strip()


def image_url(value: object) -> str | None:
    """Only provider-owned HTTPS media hosts, passed as an image segment."""
    if not isinstance(value, str) or len(value) > 2000 or any(c.isspace() for c in value):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or parts.username or parts.password
                or parts.port not in (None, 443) or parts.fragment
                or parts.hostname not in {"static.inaturalist.org",
                    "inaturalist-open-data.s3.amazonaws.com", "upload.wikimedia.org",
                    "thumb.wikimedia.org"} or "[CQ:" in value
                or any(ord(c) < 32 for c in value)):
            return None
    except ValueError:
        return None
    return value
