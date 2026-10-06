from __future__ import annotations

import nonebot
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

from src.core.config import Settings
from src.services.autonomy.models import AutonomyDecision, PendingAction
from src.services.autonomy.parsing import (
    approval_command, extract_target_hint, parse_whitelist_command,
)
from src.services.autonomy.policy import AutonomyPolicy
from src.services.autonomy.repository import AutonomyRepository


def test_autonomy_plugin_loads_and_parses_intent() -> None:
    nonebot.init()
    nonebot.get_driver().register_adapter(OneBotV11Adapter)
    plugin = nonebot.load_plugin("src.plugins.autonomy")
    assert plugin is not None

    from src.plugins.autonomy import parse_decision

    decision = parse_decision(
        {
            "action": "speak",
            "target_type": "group",
            "target_id": 12345,
            "confidence": 0.9,
            "risk": "low",
            "intent": "daily_greeting",
            "message": "大家早上好",
            "reason": "自然问候",
        }
    )
    assert decision.intent == "greeting"


@pytest.fixture
def runtime():
    settings = Settings(_env_file=None, AUTONOMY_ENABLED=False, AUTONOMY_OWNER_ID=99999,
                        AUTONOMY_GROUP_IDS="12345", AUTONOMY_PRIVATE_USER_IDS="23456",
                        AUTONOMY_PENDING_TTL_SECONDS=300, AUTONOMY_COOLDOWN_SECONDS=600,
                        AUTONOMY_DM_COOLDOWN_SECONDS=900)
    clock = SimpleNamespace(value=1000.0)
    storage, logger = Mock(), Mock()
    repo = AutonomyRepository(settings, None, storage, clock=lambda: clock.value,
                              datetime=datetime, logger=logger)
    policy = AutonomyPolicy(settings, repo, logger=logger)
    return SimpleNamespace(settings=settings, clock=clock, storage=storage, repo=repo, policy=policy)


@pytest.mark.parametrize("text,kind,target,ambiguous", [
    ("给 23456 说晚安", "private", 23456, False),
    ("群号 12345", "group", 12345, False),
    ("问 12345 和 23456", "none", None, True),
    ("没有目标", "none", None, False),
])
def test_target_parsing(text, kind, target, ambiguous):
    hint = extract_target_hint(text)
    assert (hint.target_type, hint.target_id, hint.ambiguous) == (kind, target, ambiguous)


def test_repository_recovers_provider_and_respects_explicit_override(runtime):
    recovered = Mock()
    provider = Mock(side_effect=[None, recovered])
    repo = AutonomyRepository(runtime.settings, None, runtime.storage,
                              clock=lambda: 1000, datetime=datetime, logger=Mock(),
                              redis_provider=provider)
    assert repo.redis_client is None
    assert repo.redis_client is recovered
    repo.redis_client = None
    assert repo.redis_client is None
    assert provider.call_count == 2


def test_target_override_keeps_permissions_and_ambiguity(runtime):
    decision = AutonomyDecision("speak", "group", 12345, .95, "low", "候选消息", "理由")
    result = runtime.policy.apply_target_hint(decision, extract_target_hint("给 34567 说晚安"))
    assert (result.action, result.target_type, result.target_id, result.confidence, result.risk) == (
        "ask_owner", "private", 34567, .75, "medium")
    assert not runtime.policy.target_allowed("private", 34567)
    result = runtime.policy.apply_target_hint(decision, extract_target_hint("12345 和 23456"))
    assert (result.action, result.target_type, result.target_id, result.confidence) == (
        "ask_owner", "none", None, .7)


@pytest.mark.parametrize("confidence,risk,ask,direct", [
    (.44, "low", False, False), (.45, "low", True, False),
    (.819, "low", True, False), (.82, "low", False, True),
    (.99, "medium", True, False), (.99, "high", False, False),
])
def test_approval_thresholds(runtime, confidence, risk, ask, direct):
    decision = AutonomyDecision("speak", "group", 12345, confidence, risk, "内容", "理由")
    assert runtime.policy.should_ask_owner(decision) is ask
    assert runtime.policy.should_act_directly(decision) is direct


def test_allowlist_union_does_not_remove_configured_ids(runtime):
    runtime.repo.add_dynamic_allowlist("group", [12345, 34567])
    assert runtime.policy.group_ids() == [12345, 34567]
    runtime.repo.remove_dynamic_allowlist("group", [12345, 34567])
    assert runtime.policy.group_ids() == [12345]
    assert runtime.policy.private_user_ids() == [23456]
    assert not runtime.policy.target_allowed("none", 12345)
    assert not runtime.policy.target_allowed("group", None)


def test_commands_remain_exact():
    command = parse_whitelist_command("把 34567 加入私聊白名单")
    assert (command.action, command.target_type, command.target_ids) == ("add", "private", [34567])
    assert parse_whitelist_command("查看群白名单").action == "list"
    assert parse_whitelist_command("加入白名单") is None
    assert approval_command("批准") == ("approve", None)
    assert approval_command("取消") == ("cancel", None)
    assert approval_command("改成 新内容") == ("rewrite", "新内容")
    assert approval_command("批准 abcd") is None


def test_pending_and_cooldown_boundaries(runtime):
    repo = runtime.repo
    old = PendingAction("old", "group", 12345, "旧内容", "理由", 999)
    pending = PendingAction("new", "private", 23456, "新内容", "理由", 1000)
    repo.save_pending(old)
    repo.save_pending(pending)
    assert repo.load_latest_pending() is pending
    repo.set_cooldown("group", 12345)
    repo.set_cooldown("private", 23456)
    assert repo.cooldown_memory == {"autonomy:cooldown:group:12345": 1600,
                                    "autonomy:cooldown:private:23456": 1900}
    runtime.clock.value = 1300
    assert repo.load_latest_pending() is pending  # strict > TTL, not >=
    runtime.clock.value = 1300.01
    assert repo.load_latest_pending() is None
    runtime.clock.value = 1600
    assert not repo.in_cooldown("group", 12345)
    assert repo.in_cooldown("private", 23456)
    repo.delete_pending("new")
    assert "new" not in repo.pending_memory


def test_redis_keys_ttl_latest_and_log_retention(runtime):
    repo = runtime.repo
    redis = Mock()
    repo.redis_client = redis
    pending = PendingAction("abcd1234", "group", 12345, "内容", "理由", 1000)
    redis.eval.return_value = 1
    assert repo.save_pending(pending)
    args = redis.eval.call_args.args
    assert args[1:5] == (3, "autonomy:pending:abcd1234", "autonomy:pending:latest",
                         "autonomy:execution:abcd1234")
    assert json.loads(args[5]) == vars(pending)
    assert args[6:] == ("abcd1234", 300)
    redis.get.side_effect = ["abcd1234", args[5]]
    assert repo.load_latest_pending() == pending
    repo.delete_pending("abcd1234")
    assert redis.eval.call_args.args[1:] == (2, "autonomy:pending:abcd1234",
                                            "autonomy:pending:latest", "abcd1234")
    repo.set_cooldown("private", 23456)
    redis.set.assert_called_with("autonomy:cooldown:private:23456", 1900.0, ex=900)
    repo.append_log("sample", {"value": 1})
    assert redis.rpush.call_args.args[0] == "autonomy:logs"
    redis.ltrim.assert_called_with("autonomy:logs", -200, -1)
    redis.smembers.return_value = {"34567"}
    assert repo.dynamic_allowlist("group") == {34567}
    redis.smembers.assert_called_with("autonomy:allowlist:group")


def test_redis_failure_keeps_original_fallback_and_missing_semantics(runtime):
    repo = runtime.repo
    redis = Mock()
    for name in ("set", "get", "delete", "eval", "smembers", "sadd", "srem"):
        getattr(redis, name).side_effect = RuntimeError("offline")
    repo.redis_client = redis
    repo.add_dynamic_allowlist("private", [34567])
    assert repo.dynamic_allowlist("private") == {34567}
    redis.rpush.assert_not_called()  # original write-failure branch returns before logging
    repo.remove_dynamic_allowlist("private", [34567])
    assert repo.dynamic_allowlist("private") == set()
    pending = PendingAction("fallback", "group", 12345, "内容", "理由", 1000)
    repo.save_pending(pending)
    assert repo.load_latest_pending() is pending
    repo.set_cooldown("group", 12345)
    assert repo.in_cooldown("group", 12345)
    redis.get.side_effect = None
    redis.get.return_value = None
    assert repo.load_latest_pending() is None  # successful Redis miss does not consult memory
    assert not repo.in_cooldown("group", 12345)
    redis.smembers.return_value = set()
    redis.smembers.side_effect = None
    assert repo.dynamic_allowlist("private") == set()
    repo.delete_pending("fallback")
    assert not repo.pending_memory
