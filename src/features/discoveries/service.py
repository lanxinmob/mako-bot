"""Exact command routing; no model, billing or long-term storage dependency."""
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
import re
import time

from .models import DiscoveryReply
from .network import LookupUnavailable, PublicAPI


HELP = (
    "来点有趣的：\n"
    "小鸟：今日鸟图；小鸟 麻雀／Passer montanus：查鸟种\n"
    "传送：今天的历史身份；传送 唐朝 或 传送 埃及：选时代地点；传送 再来：换一个\n"
    "期刊 Nature／1932-6203：查刊名或 ISSN\n"
    "发表／投稿：今日真实期刊；投稿 machine learning：按相关文章找刊物\n"
    "也可以加“茉子”或 @茉子。"
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
    if text.startswith(("/", ".")):
        text = text[1:]
    match = re.fullmatch(r"(小鸟|今日小鸟|传送|期刊|发表|投稿|发现帮助)(?:[ \t]+([^\r\n]{1,100}))?", text)
    if match is None:
        return None
    name, argument = match.groups()
    if name == "发现帮助" and argument:
        return None
    kind = {"小鸟": "bird", "今日小鸟": "bird", "传送": "journey",
            "期刊": "journal", "发表": "suggest", "投稿": "suggest", "发现帮助": "help"}[name]
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
