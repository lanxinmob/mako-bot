"""Behavioral checks for historical filtering, time and provenance labels."""

from datetime import datetime, timedelta, timezone
import re
import subprocess
import sys

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
    assert "史实背景：" not in text


def test_default_is_stable_after_reroll_and_across_processes():
    first = journey(user_id=2048, now=NOW)
    journey("再来", user_id=2048, now=NOW)
    assert journey(user_id=2048, now=NOW) == first
    script = (
        "from datetime import datetime; "
        "from src.features.discoveries.journeys import journey; "
        "print(journey(user_id=2048, now=datetime(2026,10,6,12)).text)"
    )
    output = subprocess.check_output(
        [sys.executable, "-X", "utf8", "-B", "-c", script], text=True, encoding="utf-8"
    )
    assert output.strip() == first.text


def test_beijing_day_boundary_and_user_specific_selection():
    utc_before = datetime(2026, 10, 5, 15, 59, tzinfo=timezone.utc)
    utc_after = utc_before + timedelta(minutes=1)
    for user_id in (0, 1, 2048):
        assert journey(user_id=user_id, now=utc_before) == journey(
            user_id=user_id, now=datetime(2026, 10, 5, 23, 59)
        )
        assert journey(user_id=user_id, now=utc_after) == journey(
            user_id=user_id, now=datetime(2026, 10, 6, 0)
        )
    assert len({journey(user_id=i, now=NOW).text for i in range(16)}) > 1
    assert any(
        journey(user_id=i, now=utc_before) != journey(user_id=i, now=utc_after)
        for i in range(16)
    )


def test_reroll_does_not_repeat_previous_card():
    previous = journey("中国唐朝", user_id=4096, now=NOW)
    for _ in range(12):
        following = journey("再来", user_id=4096, now=NOW)
        assert following != previous
        previous = following


@pytest.mark.parametrize("query", ["两河流域", "埃及"])
def test_bce_year_is_positive_and_marked_approximate(query):
    text = journey(query, now=NOW).text
    assert re.search(r"故事落点（虚构设定）：约公元前[1-9]\d*年", text)
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
    assert "史实背景：" in reply.text
    assert "原创虚构（人物与情节）：" in reply.text
    assert "来源（仅支持史实背景；核对2026-10-06）：" in reply.text
    assert source in reply.text
    assert len(re.sub(r"https://\S+", "", reply.text)) <= 400
    assert "寿命" not in reply.text and "享年" not in reply.text
