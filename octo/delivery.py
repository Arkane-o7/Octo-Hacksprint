"""Small delivery policies; conversation intent and permissions stay in core."""
from .contracts import IncomingMessage


def should_speak(event: IncomingMessage, parent: dict) -> bool:
    """Automatic audio is DM-only, for voice input or a saved explicit opt-in."""
    return not event.is_group and (event.kind == 'voice' or parent.get('voice_replies') is True)
