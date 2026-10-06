from src.features.discoveries.service import Command, RepeatGate, parse_command


def test_only_explicit_commands_claim_messages():
    for text in ("小鸟", "茉子，小鸟", "/小鸟", "mako 期刊 Nature", "传送 唐朝"):
        assert parse_command(text) is not None
    for text in ("这只小鸟很可爱", "今天发表了一篇论文", "传送门在哪里", "期刊\nNature", "发现帮助 extra"):
        assert parse_command(text) is None
    assert parse_command("投稿 machine learning") == Command("suggest", "machine learning")
    assert parse_command("小鸟 麻雀") == Command("bird", "麻雀")


def test_only_duplicate_invocations_are_silenced():
    now = [0]
    gate = RepeatGate(clock=lambda: now[0])
    key = ("bot", "group", 1, 7)
    bird = Command("bird")
    assert gate.admit(key, bird)
    assert not gate.admit(key, bird)
    assert gate.admit(key, Command("journey"))
    assert gate.admit(("bot", "group", 2, 7), bird)
    assert gate.admit(("bot", "group", 1, 8), bird)
    now[0] = 3
    assert gate.admit(key, bird)
