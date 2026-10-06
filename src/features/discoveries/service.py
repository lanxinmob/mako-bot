"""Exact command routing; no model, billing or long-term storage dependency."""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
import re
import time

from .models import DiscoveryReply
from .network import LookupUnavailable, PublicAPI


HELP = (
    "哼哼，茉子大人藏了几样小玩意，要试哪个？\n\n"
    "🐦 看鸟\n发「小鸟」，我给你找位带翅膀的朋友。\n有想见的？试试「小鸟 麻雀」或「小鸟 Passer montanus」。\n\n"
    "🧭 换一段人生\n换个时代过一天？发「传送」，我送你去。\n想去哪儿？「传送 唐朝」「传送 埃及」。换一站就再发「传送」或「传送 再来」。\n\n"
    "📚 找本期刊\n要认真干活也行，茉子大人可是很靠谱的。\n「发表」或「投稿」看看今天的真实刊物。\n"
    "「期刊 Nature」「期刊 1932-6203」查刊；「投稿 machine learning」按论文主题找刊。\n\n"
    "📒 翻翻茉子的笔记（仅 owner）\n「人物档案」看人数和最近几位；\n"
    "「人物档案 ID」或「人物档案 名称」看完整档案。我会私聊给你，可别在群里摊开啦。\n\n"
    "直接发命令，叫我茉子或 @我也行。别光看说明，试试嘛~"
)


@dataclass(frozen=True)
class Command:
    kind: str
    argument: str = ""


def parse_command(text: str, nicknames=("茉子", "mako")) -> Command | None:
    text = text.strip()
    for nickname in sorted((n for n in nicknames if isinstance(n, str) and n), key=len, reverse=True):
        if text.casefold().startswith(nickname.casefold()):
            text = text[len(nickname):].lstrip(" \t,，:：")
            break
    if text == "/help":
        return Command("help")
    if text.startswith(("/", ".")):
        text = text[1:]
    match = re.fullmatch(r"(小鸟|今日小鸟|传送|期刊|发表|投稿)(?:[ \t]+([^\r\n]{1,100}))?", text)
    if match is None:
        return None
    name, argument = match.groups()
    kind = {"小鸟": "bird", "今日小鸟": "bird", "传送": "journey",
            "期刊": "journal", "发表": "suggest", "投稿": "suggest"}[name]
    return Command(kind, (argument or "").strip())


class RepeatGate:
    """Suppress repeated identical invocations, while retaining distinct commands."""
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.items = OrderedDict()

    def admit(self, key, command):
        now = self.clock()
        identity = (key, command)
        if now - self.items.get(identity, float("-inf")) < 3:
            return False
        self.items[identity] = now
        self.items.move_to_end(identity)
        while len(self.items) > 1024:
            self.items.popitem(last=False)
        return True


class DiscoveriesService:
    def __init__(self, api=None):
        self.api = api if api is not None else PublicAPI()

    async def run(self, command: Command, *, user_id: int = 0,
                  now: datetime | None = None) -> DiscoveryReply:
        try:
            if command.kind == "help":
                return DiscoveryReply(HELP)
            if command.kind == "journey":
                from .journeys import journey
                return journey(command.argument, user_id=user_id, now=now)
            if command.kind == "bird":
                from .birds import bird
                return await bird(self.api, command.argument, user_id=user_id, now=now)
            from .journals import journal, suggest
            handler = journal if command.kind == "journal" else suggest
            return await handler(self.api, command.argument, user_id=user_id, now=now)
        except LookupUnavailable:
            return DiscoveryReply("资料来源暂时没返回可核对的结果，稍后再试。历史传送仍可用。")
        except ValueError as exc:
            return DiscoveryReply(str(exc))
