"""Bird discovery with explicit species matching and reusable image provenance."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from .bird_catalog import BirdPhoto, BirdRecord, DAILY_BIRDS, VERIFIED_DAY
from .models import DiscoveryReply, clean, image_url
from .network import LookupUnavailable, PublicAPI


TAXA_URL = "https://api.inaturalist.org/v1/taxa"
BEIJING = timezone(timedelta(hours=8))
LICENSES = {
    "cc0": ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "cc-by": ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "cc-by-sa": ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
}
SCIENTIFIC_NAME = re.compile(r"[A-Z][a-z]+ [a-z][a-z-]+")


def _daily_record(user_id: int, now: datetime | None) -> tuple[BirdRecord, str]:
    current = now if now is not None else datetime.now(BEIJING)
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING)
    day = current.astimezone(BEIJING).date().isoformat()
    seed = hashlib.sha256(f"birds:{day}:{user_id}".encode("utf-8")).digest()
    return DAILY_BIRDS[int.from_bytes(seed[:8], "big") % len(DAILY_BIRDS)], day


def _record(name: str) -> BirdRecord | None:
    return next((item for item in DAILY_BIRDS if item.name == name), None)


def _positive_id(value) -> bool:
    return type(value) is int and 0 < value < 10**10


def _valid_taxon(taxon) -> bool:
    if not isinstance(taxon, dict):
        return False
    name = taxon.get("name")
    if (taxon.get("rank") != "species" or taxon.get("iconic_taxon_name") != "Aves"
            or not _positive_id(taxon.get("id")) or not isinstance(name, str)
            or not SCIENTIFIC_NAME.fullmatch(name) or taxon.get("is_active") is False):
        return False
    # The verified offline identity must not lend a photo to a different taxon.
    for item in DAILY_BIRDS:
        if name == item.name or taxon["id"] == item.taxon_id:
            return name == item.name and taxon["id"] == item.taxon_id
    return True


def _candidates(payload) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise LookupUnavailable("物种来源返回了无法核对的资料")
    candidates, seen = [], {}
    for taxon in payload["results"][:20]:
        if not _valid_taxon(taxon):
            continue
        previous = seen.get(taxon["id"])
        if previous is not None:
            if previous != taxon:
                raise LookupUnavailable("同一物种 ID 返回了冲突资料")
            continue
        seen[taxon["id"]] = taxon
        candidates.append(taxon)
    return candidates


def _chinese_name(taxon: dict) -> str:
    known = _record(taxon["name"])
    if known is not None:
        return known.chinese_name
    value = clean(taxon.get("preferred_common_name"), 80)
    return value if re.search(r"[\u3400-\u9fff]", value) else ""


def _matching(taxon: dict, query: str) -> bool:
    if taxon["name"].casefold() == query.casefold():
        return True
    if not re.search(r"[\u3400-\u9fff]", query):
        return False
    names = [taxon.get("preferred_common_name"), taxon.get("matched_term")]
    extra = taxon.get("names")
    if isinstance(extra, list):
        names.extend(item.get("name") for item in extra[:20]
                     if isinstance(item, dict) and item.get("is_valid") is not False)
    return query in names


def _wiki_source(value) -> str | None:
    if (not isinstance(value, str) or len(value) > 1000 or "[CQ:" in value
            or any(c.isspace() or ord(c) < 32 for c in value)):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ("https", "http") or parts.username or parts.password
                or parts.port is not None or parts.query or parts.fragment
                or parts.hostname not in {"en.wikipedia.org", "zh.wikipedia.org"}
                or not parts.path.startswith("/wiki/") or len(parts.path) <= 6):
            return None
        return urlunsplit(("https", parts.hostname, parts.path, "", ""))
    except ValueError:
        return None


def _same_species(metadata: dict, taxon: dict) -> bool:
    if "taxon_id" in metadata:
        if not _positive_id(metadata["taxon_id"]) or metadata["taxon_id"] != taxon["id"]:
            return False
    if "taxon" in metadata:
        linked = metadata["taxon"]
        if (not isinstance(linked, dict) or not _positive_id(linked.get("id"))
                or linked["id"] != taxon["id"]):
            return False
        if "name" in linked and linked["name"] != taxon["name"]:
            return False
    return True


def _reusable_photo(photo, taxon: dict) -> BirdPhoto | None:
    if not isinstance(photo, dict) or not _same_species(photo, taxon):
        return None
    code = photo.get("license_code")
    if not isinstance(code, str) or code not in LICENSES:
        return None
    license_name, license_url = LICENSES[code]
    if "license_url" in photo and photo["license_url"] != license_url:
        return None
    author = clean(photo.get("attribution_name"), 150)
    photo_id = photo.get("id")
    if not author or not _positive_id(photo_id) or photo.get("flags"):
        return None
    for field in ("medium_url", "url", "square_url"):
        url = image_url(photo.get(field))
        if url is None:
            continue
        parts = urlsplit(url)
        if (parts.hostname not in {"static.inaturalist.org",
                                   "inaturalist-open-data.s3.amazonaws.com"}
                or not re.fullmatch(rf"/photos/{photo_id}/(?:medium|square|small|large)"
                                    r"\.(?:jpe?g|png)", parts.path)
                or parts.query):
            continue
        return BirdPhoto(url, author, license_name, license_url,
                         f"https://www.inaturalist.org/photos/{photo_id}")
    return None


def _photo(taxon: dict) -> BirdPhoto | None:
    entries = taxon.get("taxon_photos")
    if isinstance(entries, list):
        for entry in entries[:20]:
            if isinstance(entry, dict) and _same_species(entry, taxon):
                photo = _reusable_photo(entry.get("photo"), taxon)
                if photo is not None:
                    return photo
    photo = _reusable_photo(taxon.get("default_photo"), taxon)
    if photo is not None:
        return photo
    known = _record(taxon["name"])
    if known is not None and known.taxon_id == taxon["id"]:
        return known.photo
    return None


def _render(taxon: dict, fetched_day: str, *, title: str, offline=False) -> DiscoveryReply:
    chinese = _chinese_name(taxon)
    lines = [title, f"{chinese or '中文名：来源未提供'} · {taxon['name']}",
             "分类：鸟纲 Aves · 种 species"]
    known = _record(taxon["name"])
    if known is not None:
        lines.extend((known.note, f"科普来源（核对 {VERIFIED_DAY}）：{known.source}"))
    else:
        lines.append("来源未提供经核对的辨认说明，更多资料请查看下方物种来源。")
    lines.append(f"物种来源：https://www.inaturalist.org/taxa/{taxon['id']}")
    wiki = _wiki_source(taxon.get("wikipedia_url"))
    if wiki is not None:
        lines.append(f"百科来源（iNaturalist 提供的链接）：{wiki}")
    lines.append(f"{'离线核对日期' if offline else '资料获取日期'}：{fetched_day}")
    photo = _photo(taxon)
    if photo is None:
        lines.append("未找到同种且许可可核对的可复用图片，保留资料链接。")
        return DiscoveryReply("\n".join(lines))
    url = image_url(photo.url)
    if url is None:
        lines.append("图片地址未通过检查，保留资料链接。")
        return DiscoveryReply("\n".join(lines))
    lines.extend((f"图片作者：{photo.author}；许可：{photo.license_name}",
                  f"许可链接：{photo.license_url}", f"图片来源：{photo.source}",
                  "使用来源缩略图，未另行裁剪或改绘。"))
    return DiscoveryReply("\n".join(lines), url)


def _offline(record: BirdRecord, day: str) -> DiscoveryReply:
    taxon = {"id": record.taxon_id, "name": record.name,
             "rank": "species", "iconic_taxon_name": "Aves"}
    return _render(taxon, VERIFIED_DAY,
                   title=f"今日小鸟 · {day}\n网络资料暂不可核对，使用同种已核对的离线资料。",
                   offline=True)


def _candidate_reply(candidates: list[dict], fetched_day: str, *, more=False) -> DiscoveryReply:
    lines = ["查询尚不能唯一确定鸟种，请用下面的完整学名再查："]
    for taxon in candidates[:6]:
        name = _chinese_name(taxon)
        lines.append(f"- {name + ' · ' if name else ''}{taxon['name']} "
                     f"https://www.inaturalist.org/taxa/{taxon['id']}")
    if len(candidates) > 6 or more:
        lines.append("以上仅列部分候选，请补充完整学名以缩小范围。")
    lines.append(f"资料获取日期：{fetched_day}")
    return DiscoveryReply("\n".join(lines))


async def bird(api: PublicAPI, query: str = "", *, user_id: int = 0,
               now: datetime | None = None) -> DiscoveryReply:
    """Resolve an explicit bird name, or a stable daily bird with a verified image."""
    if not isinstance(query, str) or len(query) > 100:
        return DiscoveryReply("请提供不超过 100 字的中文鸟名或完整学名。")
    query = " ".join(query.split())
    daily, day = _daily_record(user_id, now)
    known = next((item for item in DAILY_BIRDS if query == item.chinese_name), None)
    search = daily.name if not query else known.name if known is not None else query
    try:
        payload, fetched_day = await api.get(TAXA_URL, {
            "q": search, "rank": "species", "iconic_taxa": "Aves",
            "locale": "zh-CN", "per_page": 20,
        })
        if not isinstance(fetched_day, str) or date.fromisoformat(fetched_day).isoformat() != fetched_day:
            raise LookupUnavailable("资料获取日期无法核对")
        candidates = _candidates(payload)
    except (LookupUnavailable, ValueError):
        if not query:
            return _offline(daily, day)
        return DiscoveryReply("鸟种资料来源暂不可用，未能核对这次查询。请稍后用原鸟名或完整学名再查。")
    exact = [taxon for taxon in candidates if _matching(taxon, search)]
    # Scientific names may have unrelated fuzzy hits; common-name ambiguity stays explicit.
    scientific = bool(re.fullmatch(r"[A-Za-z]+ [A-Za-z][A-Za-z-]+", search))
    total = payload.get("total_results")
    more = type(total) is int and total > len(payload["results"])
    if len(exact) == 1 and (scientific or (len(candidates) == 1 and not more)):
        title = f"今日小鸟 · {day}" if not query else "小鸟查询"
        return _render(exact[0], fetched_day, title=title)
    if not query:
        return _offline(daily, day)
    if candidates:
        return _candidate_reply(candidates, fetched_day, more=more)
    return DiscoveryReply("没有找到可核对的鸟纲种级物种，请检查中文名或完整学名；本次未替换成其他鸟。")
