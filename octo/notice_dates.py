"""Resolve common notice dates against the original message's India date."""
import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo

_MONTHS = 'january february march april may june july august september october november december'.split()
_MONTH_NUMBERS = {name: number for number, month in enumerate(_MONTHS, 1) for name in (month, month[:3])}
_WEEKDAYS = 'monday tuesday wednesday thursday friday saturday sunday'.split()


def resolve_notice_date(written, message_time, fallback=None):
    if not written:
        return None
    today = message_time.astimezone(ZoneInfo('Asia/Kolkata')).date()
    text = re.sub(r'\s+', ' ', written.strip().lower().rstrip('.'))
    text = re.sub(r'^on ', '', text)
    if text in ('today', 'tomorrow', 'day after tomorrow'):
        return (today + timedelta(days=('today', 'tomorrow', 'day after tomorrow').index(text))).isoformat()
    weekday = re.fullmatch(r'(?:(upcoming|coming|next|this) )?(' + '|'.join(_WEEKDAYS) + r')', text)
    if weekday:
        days = (_WEEKDAYS.index(weekday[2]) - today.weekday()) % 7
        if days == 0 and weekday[1] in ('upcoming', 'coming', 'next'):
            days = 7
        return (today + timedelta(days=days)).isoformat()
    text = re.sub(r'(?<=\d)(?:st|nd|rd|th)\b', '', text).replace(',', '')
    text = re.sub(r'\s+', ' ', text)
    months = '|'.join(_MONTH_NUMBERS)
    day_first = re.fullmatch(r'(\d{1,2}) (?:of )?(' + months + r')(?: (\d{4}))?', text)
    month_first = re.fullmatch(r'(' + months + r') (\d{1,2})(?: (\d{4}))?', text)
    try:
        if day_first or month_first:
            match = day_first or month_first
            day, month = (match[1], match[2]) if day_first else (match[2], match[1])
            # A yearless announcement uses the message's year. Never invent a
            # next-year event just because a stated date has already passed.
            return date(int(match[3] or today.year), _MONTH_NUMBERS[month], int(day)).isoformat()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            return date.fromisoformat(text).isoformat()
        if re.fullmatch(r'\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?', text):
            return None  # Ambiguous day/month ordering needs clarification.
        # Preserve model resolution for other languages and date expressions.
        return date.fromisoformat(fallback).isoformat() if fallback else None
    except (TypeError, ValueError):
        return None
