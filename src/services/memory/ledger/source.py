"""Source metadata is taken from the adapter event, never from message arguments."""
from datetime import datetime
import time


def from_event(event, bot):
    occurred = getattr(event, 'time', None)
    try:
        occurred = datetime.fromtimestamp(occurred).astimezone().isoformat() if occurred else None
    except (ValueError, TypeError, OSError):
        occurred = None
    return dict(bot_id=str(bot.self_id), message_id=str(event.message_id), user_id=event.user_id,
                scene=event.message_type, occurred_at=occurred,
                received_ns=time.time_ns(),
                received_at=datetime.now().astimezone().isoformat(), quoted=getattr(event, 'reply', None) is not None)
