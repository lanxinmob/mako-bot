"""Server smoke checks: public sources only, no bot, secrets or chat storage.

Run from a checkout: python scripts/smoke_discoveries.py [--live] [--media]
The media check reads only the first response chunk and never saves an image.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.features.discoveries.bird_catalog import DAILY_BIRDS
from src.features.discoveries.models import image_url
from src.features.discoveries.service import DiscoveriesService, parse_command


async def media_check(url):
    if image_url(url) != url:
        return {"ok": False, "reason": "invalid_media_endpoint"}
    try:
        async with httpx.AsyncClient(timeout=12, trust_env=False, follow_redirects=False,
                                     headers={"User-Agent": "MakoDiscoveries/1.0"}) as client:
            async with client.stream("GET", url, headers={"Range": "bytes=0-4095"}) as response:
                status = response.status_code
                content_type = response.headers.get("content-type", "").split(";")[0]
                if status not in (200, 206) or content_type not in ("image/jpeg", "image/png"):
                    return {"ok": False, "status": status, "type": content_type}
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    signature = chunk.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"))
                    return {"ok": signature, "status": status, "type": content_type,
                            "sample_bytes": len(chunk)}
                return {"ok": False, "reason": "empty_media"}
    except (httpx.HTTPError, OSError) as exc:
        return {"ok": False, "reason": type(exc).__name__}


async def run(options):
    service = DiscoveriesService()
    result = {"offline": {}, "live": {}, "media": []}
    failed = False
    for text in ("发现帮助", "传送 唐朝", "传送 再来"):
        reply = await service.run(parse_command(text), user_id=0)
        ok = ("小鸟" in reply.text if text == "发现帮助" else "虚构" in reply.text)
        result["offline"][text] = {"ok": ok, "preview": reply.text[:160]}
        failed |= not ok
    media_urls = set()
    if options.live:
        cases = (("小鸟 麻雀", "Passer montanus"), ("小鸟 欧亚鸲", "Erithacus rubecula"),
                 ("期刊 1932-6203", "10."), ("期刊 Nature", "Nature"),
                 ("投稿 machine learning", "10."), ("发表", "ISSN"))
        for text, expected in cases:
            reply = await service.run(parse_command(text), user_id=0)
            ok = expected in reply.text
            result["live"][text] = {"ok": ok, "preview": reply.text[:240],
                                    "has_image": bool(reply.image_url),
                                    "source_unavailable": "暂时" in reply.text or "内置" in reply.text}
            failed |= not ok
            if reply.image_url:
                media_urls.add(reply.image_url)
    if options.media:
        for record in DAILY_BIRDS:
            media_urls.add(record.photo.url)
        for url in sorted(media_urls):
            check = await media_check(url)
            result["media"].append({"host": urlsplit(url).hostname, "url": url, **check})
            failed |= not check["ok"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(failed)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="query public bird/journal metadata")
    parser.add_argument("--media", action="store_true", help="check public image headers/signature")
    raise SystemExit(asyncio.run(run(parser.parse_args())))
