"""Bounded reference state, never authority or a substitute for current facts."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict


class FollowupIntent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['new', 'reference', 'date', 'language', 'audio', 'ambiguous'] = 'new'


def scope(event, caller):
    return [event.session, event.chat_id, caller['id'], caller.get('class_id', ''),
            sorted(caller.get('student_ids', [])), sorted(caller.get('classes', [])),
            caller.get('class_wide_only', False)]


def date_only(text, timestamp, original=None):
    """Accept a complete date-only reply; never extract dates out of new notices."""
    value = text.strip().rstrip('.').strip()
    relative = {'today': 0, 'tomorrow': 1, 'day after tomorrow': 2}
    if value.lower() in relative:
        return (timestamp.astimezone(ZoneInfo('Asia/Kolkata')).date() + timedelta(days=relative[value.lower()])).isoformat()
    if re.fullmatch(r'20\d{2}', value) and original:
        value = original.strip() + ' ' + value
    for fmt in ('%Y-%m-%d', '%d %B %Y', '%d %b %Y'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def date_uncertainty_only(record):
    return all(re.search(r'\b(date|year|when|dated)\b', item, re.I)
               and not re.search(r'conflict|multiple|unreadable|illegible|incomplete', item, re.I)
               for item in record.unclear)


def fixture_followup(text):
    """Offline fixture only. Live understanding uses Sarvam's structured intent."""
    value = text.strip().lower()
    if value in ('read that aloud', 'read it aloud', 'read aloud'):
        return FollowupIntent(mode='audio')
    if value.startswith('in ') and value.endswith(' please'):
        return FollowupIntent(mode='language')
    if value.startswith('and '):
        return FollowupIntent(mode='date')
    if value in ('send its notes', 'show its calendar entry', 'send notes', 'show calendar', 'send calendar'):
        return FollowupIntent(mode='reference')
    return FollowupIntent()
