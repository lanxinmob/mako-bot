from datetime import date, datetime

import pytest

from src.features.discoveries.journal_catalog import SEEDS
from src.features.discoveries.journals import _article, _two_years_before, journal, suggest, valid_issn
from src.features.discoveries.network import LookupUnavailable

NOW = datetime(2026, 10, 6, 12)


def record(title="PLOS One", issn="1932-6203"):
    return {"title": title, "ISSN": [issn], "publisher": "Public Library of Science"}


def work(title="Robot learning evidence", container="Example Journal", issn="1932-6203",
         doi="10.1234/paper?one", parts=None):
    return {"title": [title], "container-title": [container], "ISSN": [issn],
            "publisher": "Example publisher", "DOI": doi, "type": "journal-article",
            "published": {"date-parts": [parts or [2025, 9, 24]]}}


class API:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def get(self, url, params=None):
        self.calls.append((url, params or {}))
        message = self.response(url, params or {})
        if isinstance(message, Exception):
            raise message
        return {"status": "ok", "message": message}, "2026-10-06"


def test_issn_checksum_and_format():
    assert valid_issn("19326203") == "1932-6203"
    assert valid_issn("1546-170x") == "1546-170X"
    assert valid_issn("9999-9999") is None
    assert valid_issn("1932-6200") is None
    assert valid_issn(["1932-6203"]) is None


def test_two_year_window_preserves_month_end_and_handles_leap_day():
    assert _two_years_before(date(2026, 10, 31)) == date(2024, 10, 31)
    assert _two_years_before(date(2024, 2, 29)) == date(2022, 2, 28)


@pytest.mark.asyncio
async def test_invalid_issn_does_not_fetch():
    api = API(lambda *a: pytest.fail("invalid ISSN must not fetch"))
    with pytest.raises(ValueError, match="校验位"):
        await journal(api, "1932-6200", now=NOW)


@pytest.mark.asyncio
async def test_journal_keeps_identity_when_paper_source_fails():
    api = API(lambda url, p: LookupUnavailable() if url.endswith("/works") else record())
    reply = await journal(api, "ISSN:1932-6203", now=NOW)
    assert "PLOS One" in reply.text and "Public Library of Science" in reply.text
    assert "近期论文来源暂不可用" in reply.text
    assert "投稿说明：https://journals.plos.org/plosone" in reply.text
    assert "分区、影响因子、版面费：本功能未核验" in reply.text


@pytest.mark.asyncio
async def test_nature_links_author_guidance_and_labels_article_precision():
    api = API(lambda url, p: {"items": [work(title="Science news", issn="1476-4687")]} if
              url.endswith("/works") else record("Nature", "1476-4687"))
    reply = await journal(api, "Nature", now=NOW)
    assert "nature/for-authors/initial-submission" in reply.text
    assert "近期文章例证" in reply.text and "不区分研究与新闻" in reply.text


@pytest.mark.asyncio
async def test_name_search_checks_later_exact_match_and_issn():
    def response(url, params):
        if url.endswith("/works"):
            return {"items": [work(container="Nature Medicine", issn="1546-170X")]}
        return {"items": [record("NatureJobs")] * 8 + [record("Nature Medicine", "1546-170X")]}

    api = API(response)
    reply = await journal(api, "Nature Medicine", now=NOW)
    assert "期刊｜Nature Medicine" in reply.text
    assert "NatureJobs" not in reply.text
    assert "https://doi.org/10.1234/paper%3Fone" in reply.text
    assert api.calls[0][1]["rows"] >= 10
    assert "until-pub-date:2026-10-06" in api.calls[1][1]["filter"]


@pytest.mark.asyncio
async def test_ambiguous_names_are_candidates_and_bad_rows_are_skipped():
    api = API(lambda *a: {"items": [None, record("NatureJobs", "9999-9999"),
                                    record("Nature Chemistry"), record("Nature Physics")]})
    reply = await journal(api, "Nature Something", now=NOW)
    assert "候选" in reply.text and "期刊 1932-6203" in reply.text
    assert "NatureJobs" not in reply.text and len(api.calls) == 1


@pytest.mark.asyncio
async def test_no_results_and_wrong_identity_are_distinct():
    api = API(lambda *a: {"items": []})
    assert "没找到可核对" in (await journal(api, "Unknown title", now=NOW)).text
    api = API(lambda *a: record("Unrelated Journal", "2045-2322"))
    with pytest.raises(LookupUnavailable):
        await journal(api, "1932-6203", now=NOW)


@pytest.mark.parametrize("parts", [[2023], [2026, 11], [2027], [2025, 13], [2025, 2, 30], [True]])
def test_articles_reject_old_future_and_invalid_dates(parts):
    assert _article(work(parts=parts), date(2024, 10, 6), date(2026, 10, 6)) is None


@pytest.mark.asyncio
async def test_topic_discovery_groups_real_article_evidence():
    api = API(lambda *a: {"items": [work(title="Front Cover"), work(parts=[2027]),
                                    work(title="First paper"), work(title="Second paper"),
                                    work(container="Another Journal", issn="2045-2322"),
                                    work(container="Invalid ISSN", issn="9999-9999")]})
    reply = await suggest(api, "机器人学习", now=NOW)
    assert api.calls[0][1]["query.bibliographic"] == "robot learning"
    assert "Example Journal" in reply.text and "Another Journal" in reply.text
    assert "Front Cover" not in reply.text and "Second paper" not in reply.text
    assert "Invalid ISSN" not in reply.text
    assert "期刊 2045-2322" in reply.text and "不代表质量排名或录用概率" in reply.text
    assert reply.image_url is None


@pytest.mark.asyncio
async def test_daily_discovery_is_stable_and_uses_verified_pool():
    def response(url, params):
        if url.endswith("/works"):
            return {"items": []}
        seed = next(s for s in SEEDS if url.endswith(s.issn))
        return record(seed.title, seed.issn)

    api = API(response)
    assert await suggest(api, user_id=7, now=NOW) == await suggest(api, user_id=7, now=NOW)
    assert len({(await suggest(api, user_id=i, now=NOW)).text for i in range(20)}) > 1


@pytest.mark.asyncio
async def test_source_text_cannot_insert_cq_commands():
    api = API(lambda *a: {"items": [record("Test [CQ:at,qq=all]")]})
    reply = await journal(api, "Test", now=NOW)
    assert "[CQ:" not in reply.text and "［CQ:" in reply.text
