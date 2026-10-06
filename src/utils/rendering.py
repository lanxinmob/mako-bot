"""Pure OneBot text-to-segment rendering."""
from nonebot.adapters.onebot.v11 import Message, MessageSegment

def render_group_text(text: str, name_to_user: dict[str, int]) -> Message:
    """Convert display-name occurrences to @ segments, preferring long names."""

    names = sorted(name_to_user, key=len, reverse=True)
    segments: list[MessageSegment] = []
    position = 0
    while position < len(text):
        name = next((item for item in names if text.startswith(item, position)), None)
        if name:
            segments.append(MessageSegment.at(name_to_user[name]))
            position += len(name)
        else:
            segments.append(MessageSegment.text(text[position]))
            position += 1
    return Message(segments)
