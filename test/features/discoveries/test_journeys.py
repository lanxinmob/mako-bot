"""Behavioral checks for historical filtering, time and provenance labels."""

from datetime import datetime
import re

import pytest

from src.features.discoveries.journeys import journey
from src.features.discoveries.models import DiscoveryReply

NOW = datetime(2026, 10, 6, 12)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("中国唐朝", "长安（今西安）"),
        ("中国，北宋", "汴京（今开封）"),
        ("日本 江户时代", "日本 · 江户"),
        ("英国 十九世纪", "伦敦海德公园"),
        ("非洲", "代尔麦地那"),
    ],
)
def test_region_and_era_filter(query, expected):
    assert expected in journey(query, now=NOW).text


@pytest.mark.parametrize("query", ["火星", "中国 火星", "中国 北宋 日本", "不存在的地点"])
def test_unknown_or_conflicting_filter_offers_existing_options(query):
    text = journey(query, now=NOW).text
    assert text.startswith("还没有符合这些关键词的故事。")
    assert "唐代长安" in text and "北宋汴京" in text
    assert "历史背景：" not in text


def test_default_cycles_through_all_stories_without_adjacent_repeats():
    replies = [journey(user_id=2048, now=NOW) for _ in range(24)]
    for start in range(0, 24, 8):
        assert len(set(r.text for r in replies[start:start + 8])) == 8
    assert all(a != b for a, b in zip(replies, replies[1:]))


def test_filtered_pool_also_rotates_and_other_users_do_not_consume_it():
    first = journey("中国", user_id=2049, now=NOW)
    journey("中国", user_id=2050, now=NOW)
    second = journey("中国", user_id=2049, now=NOW)
    assert first != second
    assert "中国" in first.text and "中国" in second.text


def test_reroll_does_not_repeat_previous_card():
    previous = journey("中国唐朝", user_id=4096, now=NOW)
    for _ in range(12):
        following = journey("再来", user_id=4096, now=NOW)
        assert following != previous
        previous = following


@pytest.mark.parametrize("query", ["两河流域", "埃及"])
def test_bce_year_is_positive_and_marked_approximate(query):
    text = journey(query, now=NOW).text
    assert re.search(r"约公元前[1-9]\d*年", text)
    assert "公元前-" not in text


@pytest.mark.parametrize(
    ("query", "source"),
    [
        ("两河流域", "peabody.yale.edu"),
        ("埃及", "metmuseum.org"),
        ("庞贝", "pompeiisites.org"),
        ("唐代", "whc.unesco.org"),
        ("北宋", "dpm.org.cn"),
        ("江户", "metmuseum.org"),
        ("伦敦", "vam.ac.uk"),
        ("犹他", "nps.gov"),
    ],
)
def test_short_cards_separate_facts_from_original_fiction(query, source):
    reply = journey(query, now=NOW)
    assert isinstance(reply, DiscoveryReply)
    assert reply.image_url is None
    assert "历史背景：" in reply.text
    assert "小故事（虚构）：" in reply.text
    assert "背景出处（核对2026-10-06）：" in reply.text
    assert source in reply.text
    assert len(re.sub(r"https://\S+", "", reply.text)) <= 400
    assert "寿命" not in reply.text and "享年" not in reply.text
