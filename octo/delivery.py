"""Small delivery policies; conversation intent and permissions stay in core."""
from .contracts import IncomingMessage


def should_speak(event: IncomingMessage, parent: dict, *, read_aloud=False) -> bool:
    """Audio is DM-only: explicit read-aloud, voice input, or saved opt-in."""
    return not event.is_group and (read_aloud or event.kind == 'voice' or parent.get('voice_replies') is True)
