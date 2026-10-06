"""Bird identity, licensing, failure and successive selections without application env."""
import asyncio
from copy import deepcopy
from datetime import datetime

import httpx
import pytest

from src.features.discoveries.bird_catalog import DAILY_BIRDS
from src.features.discoveries.birds import TAXA_URL, bird
from src.features.discoveries.models import DiscoveryReply
from src.features.discoveries.network import LookupUnavailable, PublicAPI


NOW = datetime(2026, 10, 6, 12)
FETCHED = "2026-10-05"
SPARROW, ROBIN = DAILY_BIRDS


def taxon(name="Turdus merula", taxon_id=12716, common="欧乌鸫", **changes):
    return {"id": taxon_id, "name": name, "rank": "species", "iconic_taxon_name": "Aves",
            "preferred_common_name": common, "default_photo": None, **changes}


def photo(code="cc-by", **changes):
    return {"id": 123, "license_code": code, "attribution_name": "Example author",
            "medium_url": "https://inaturalist-open-data.s3.amazonaws.com/photos/123/medium.jpg",
            **changes}


class StubAPI:
    def __init__(self, results=None, *, error=False, payload=None, fetched=FETCHED):
        self.payload = {"results": results or []} if payload is None else payload
        self.error, self.fetched = error, fetched
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        if self.error:
            raise LookupUnavailable("controlled public-source failure")
        return deepcopy(self.payload), self.fetched


@pytest.mark.asyncio
async def test_real_public_api_contract_and_verified_sparrow_nc_fallback():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"results": [taxon(
            SPARROW.name, SPARROW.taxon_id, SPARROW.chinese_name,
            default_photo=photo("cc-by-nc"), taxon_photos=[],
            wikipedia_url="http://en.wikipedia.org/wiki/Eurasian_tree_sparrow",
        )]})

    reply = await bird(PublicAPI(transport=httpx.MockTransport(respond), spacing=0),
                       "麻雀", now=NOW)
    assert isinstance(reply, DiscoveryReply)
    assert reply.image_url == SPARROW.photo.url
    assert "xulescu_g" in reply.text and "CC BY-SA 2.0" in reply.text
    assert SPARROW.photo.license_url in reply.text and SPARROW.photo.source in reply.text
    assert "https://en.wikipedia.org/wiki/Eurasian_tree_sparrow" in reply.text
    assert len(requests) == 1 and str(requests[0].url).startswith(TAXA_URL)
    assert dict(requests[0].url.params) == {
        "q": SPARROW.name, "rank": "species", "iconic_taxa": "Aves",
        "locale": "zh-CN", "per_page": "20",
    }


@pytest.mark.asyncio
async def test_robin_unknown_license_uses_only_its_verified_photo():
    api = StubAPI([taxon(ROBIN.name, ROBIN.taxon_id, ROBIN.chinese_name,
                         default_photo=photo(None))])
    reply = await bird(api, "欧亚鸲", now=NOW)
    assert reply.image_url == ROBIN.photo.url
    assert "C-M" in reply.text and "CC BY-SA 4.0" in reply.text
    assert ROBIN.source in reply.text and "栗色头顶" not in reply.text


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["cc0", "cc-by", "cc-by-sa"])
async def test_allowed_inaturalist_license_has_author_photo_and_license_links(code):
    reply = await bird(StubAPI([taxon(default_photo=photo(code))]), "Turdus merula", now=NOW)
    assert reply.image_url == photo()["medium_url"]
    assert "Example author" in reply.text
    assert "https://www.inaturalist.org/photos/123" in reply.text
    assert "https://creativecommons.org/" in reply.text
    assert f"资料获取日期：{FETCHED}" in reply.text
    assert "辨认线索" not in reply.text  # No invented field notes for unknown species.


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [None, "", "cc-by-nc", "cc-by-nc-sa", "cc-by-nc-nd",
                                  "cc-by-nd", "all-rights-reserved", "cc-by-sa-2.0", []])
async def test_unusable_licenses_leave_species_information_without_replacing_photo(code):
    reply = await bird(StubAPI([taxon(default_photo=photo(code))]), "Turdus merula", now=NOW)
    assert reply.image_url is None
    assert "Turdus merula" in reply.text and "https://www.inaturalist.org/taxa/12716" in reply.text
    assert "未找到同种且许可可核对" in reply.text
    assert "Passer montanus" not in reply.text and "Erithacus rubecula" not in reply.text


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"taxon_id": 999}, {"taxon": {"id": 999}},
    {"taxon": {"id": 12716, "name": "Passer montanus"}},
    {"id": True}, {"id": "123"}, {"attribution_name": ""},
    {"flags": [{"flag": "copyright infringement"}]},
    {"medium_url": "http://static.inaturalist.org/photos/123/medium.jpg"},
    {"medium_url": "https://static.inaturalist.org.evil.test/photos/123/medium.jpg"},
    {"medium_url": "https://user@static.inaturalist.org/photos/123/medium.jpg"},
    {"medium_url": "https://static.inaturalist.org:444/photos/123/medium.jpg"},
    {"medium_url": "https://static.inaturalist.org/photos/456/medium.jpg"},
    {"medium_url": "https://thumb.wikimedia.org/photos/123/medium.jpg"},
    {"medium_url": "https://static.inaturalist.org/photos/123/medium.jpg#fragment"},
    {"license_url": "https://creativecommons.org/licenses/by-nc/4.0/"},
])
async def test_invalid_image_metadata_is_rejected(changes):
    reply = await bird(StubAPI([taxon(default_photo=photo(**changes))]), "Turdus merula", now=NOW)
    assert reply.image_url is None


@pytest.mark.asyncio
async def test_taxon_photos_outer_and_inner_ownership_and_license_are_checked():
    entries = [
        {"taxon_id": 999, "photo": photo()},
        {"taxon_id": 12716, "photo": photo(taxon_id=999)},
        {"taxon_id": 12716, "photo": photo("cc-by-nc")},
        {"taxon_id": 12716, "photo": photo("cc-by-sa")},
    ]
    reply = await bird(StubAPI([taxon(taxon_photos=entries)]), "Turdus merula", now=NOW)
    assert reply.image_url == photo()["medium_url"]
    assert "CC BY-SA 4.0" in reply.text


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"rank": "genus"}, {"iconic_taxon_name": "Plantae"}, {"id": True},
    {"id": "12716"}, {"id": 0}, {"name": "[CQ:image,file=bad]"},
    {"is_active": False}, {"iconic_taxon_name": None},
    {"name": SPARROW.name, "id": 999},
    {"name": "Turdus merula", "id": SPARROW.taxon_id},
])
async def test_invalid_species_identity_cannot_lend_a_picture(changes):
    reply = await bird(StubAPI([taxon(default_photo=photo(), **changes)]), "Turdus merula", now=NOW)
    assert reply.image_url is None
    assert "没有找到可核对" in reply.text


@pytest.mark.asyncio
async def test_ambiguous_chinese_name_lists_candidates_and_explicit_scientific_name_resolves():
    candidates = [taxon("Oriolus chinensis", 1, "黄鹂", default_photo=photo()),
                  taxon("Oriolus oriolus", 2, "黄鹂", default_photo=photo())]
    api = StubAPI(candidates)
    reply = await bird(api, "黄鹂", now=NOW)
    assert reply.image_url is None and "不能唯一确定" in reply.text
    assert all(t["name"] in reply.text for t in candidates)
    exact = await bird(api, "Oriolus chinensis", now=NOW)
    assert exact.image_url == photo()["medium_url"] and "Oriolus oriolus" not in exact.text


@pytest.mark.asyncio
async def test_fuzzy_single_hit_and_incomplete_common_name_page_are_not_assumed_exact():
    api = StubAPI([taxon("Oriolus chinensis", 1, "黑枕黄鹂")])
    reply = await bird(api, "黄鹂", now=NOW)
    assert "不能唯一确定" in reply.text and reply.image_url is None
    api.payload["results"][0]["preferred_common_name"] = "黄鹂"
    api.payload["total_results"] = 40
    reply = await bird(api, "黄鹂", now=NOW)
    assert "仅列部分候选" in reply.text and reply.image_url is None


@pytest.mark.asyncio
async def test_duplicate_scientific_name_ids_and_conflicting_id_payloads_are_not_guessed():
    api = StubAPI([taxon("Oriolus chinensis", 1), taxon("Oriolus chinensis", 2)])
    reply = await bird(api, "Oriolus chinensis", now=NOW)
    assert "不能唯一确定" in reply.text and reply.image_url is None
    api.payload = {"results": [taxon(), taxon(default_photo=photo())]}
    reply = await bird(api, "Turdus merula", now=NOW)
    assert "来源暂不可用" in reply.text and reply.image_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["不存在的鸟", "Turdus merula", "麻雀"])
async def test_named_network_failure_and_no_results_never_substitute_a_daily_bird(query):
    for api in (StubAPI(error=True), StubAPI()):
        reply = await bird(api, query, now=NOW)
        assert reply.image_url is None
        assert "今日小鸟" not in reply.text and "离线" not in reply.text


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,fetched", [
    ({"results": None}, FETCHED), ({"results": "not a list"}, FETCHED),
    ({"unexpected": []}, FETCHED), ({"results": []}, "bad date"),
    ({"results": []}, "20261006"), ({"results": []}, None),
])
async def test_malformed_data_preserves_daily_offline_image_and_named_failure(payload, fetched):
    api = StubAPI(payload=payload, fetched=fetched)
    daily = await bird(api, user_id=7, now=NOW)
    assert daily.image_url in {item.photo.url for item in DAILY_BIRDS}
    assert "已核对的离线鸟册" in daily.text and "离线核对日期：2026-10-06" in daily.text
    assert (await bird(api, "Turdus merula", now=NOW)).image_url is None


@pytest.mark.asyncio
async def test_offline_birds_alternate_with_matching_species_photos():
    api = StubAPI(error=True)
    replies = [await bird(api, user_id=706, now=NOW) for _ in range(6)]
    for reply in replies:
        item = next(item for item in DAILY_BIRDS if item.name in reply.text)
        assert reply.image_url == item.photo.url
    assert all(a.image_url != b.image_url for a, b in zip(replies, replies[1:]))


@pytest.mark.asyncio
async def test_online_pool_cycles_without_repeats_at_the_same_time():
    records = [taxon(name, i + 100, default_photo=photo(id=i + 200,
               medium_url=f"https://static.inaturalist.org/photos/{i + 200}/medium.jpg"))
               for i, name in enumerate(("Turdus merula", "Oriolus oriolus", "Pica pica"))]
    api = StubAPI(records + [taxon("Invalid bird", 999, default_photo=photo("cc-by-nc"))])
    replies = [await bird(api, user_id=707, now=NOW) for _ in range(9)]
    for start in range(0, 9, 3):
        assert len({r.image_url for r in replies[start:start + 3]}) == 3
    assert all(a.image_url != b.image_url for a, b in zip(replies, replies[1:]))
    for reply in replies:
        selected = next(t for t in records if t["name"] in reply.text)
        assert reply.image_url == selected["default_photo"]["medium_url"]
    assert all(call[1]["taxon_id"] == 3 and call[1]["per_page"] == 100 for call in api.calls)
    assert "Invalid bird" not in "".join(r.text for r in replies)


@pytest.mark.asyncio
async def test_named_queries_remain_exact_and_do_not_draw_random_species():
    api = StubAPI([taxon(default_photo=photo())])
    first = await bird(api, "Turdus merula", user_id=708, now=NOW)
    assert await bird(api, "Turdus merula", user_id=708, now=NOW) == first
    assert api.calls[0][1]["q"] == "Turdus merula"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://evil.test/wiki/Bird", "https://en.wikipedia.org.evil.test/wiki/Bird",
    "http://user@en.wikipedia.org/wiki/Bird", "http://en.wikipedia.org:80/wiki/Bird",
    "http://en.wikipedia.org/w/api.php", "https://en.wikipedia.org/wiki/Bird?q=bad",
])
async def test_wikipedia_link_is_only_normalized_for_known_hosts_and_is_never_requested(url):
    api = StubAPI([taxon(wikipedia_url=url)])
    reply = await bird(api, "Turdus merula", now=NOW)
    assert "百科来源" not in reply.text
    assert len(api.calls) == 1 and api.calls[0][0] == TAXA_URL


@pytest.mark.asyncio
async def test_cancellation_is_not_turned_into_an_offline_success():
    class CancelledAPI:
        async def get(self, *args, **kwargs):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await bird(CancelledAPI(), now=NOW)
