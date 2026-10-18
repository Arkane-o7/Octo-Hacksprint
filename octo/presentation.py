"""Small, deterministic WhatsApp layouts; no changes to school facts or permissions."""
from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')

# Only app chrome is translated here; answers remain in the model-selected language.
LABELS = {
    'en': ('Sources', 'Calendar', 'Document', 'Ask for the calendar link if you need it.'),
    'hi': ('स्रोत', 'कैलेंडर', 'दस्तावेज़', 'कैलेंडर लिंक चाहिए तो पूछें।'),
    'ta': ('ஆதாரங்கள்', 'நாட்காட்டி', 'ஆவணம்', 'நாட்காட்டி இணைப்பு வேண்டுமெனில் கேளுங்கள்.'),
    'te': ('ఆధారాలు', 'క్యాలెండర్', 'పత్రం', 'క్యాలెండర్ లింక్ కావాలంటే అడగండి.'),
    'kn': ('ಮೂಲಗಳು', 'ಕ್ಯಾಲೆಂಡರ್', 'ದಾಖಲೆ', 'ಕ್ಯಾಲೆಂಡರ್ ಲಿಂಕ್ ಬೇಕಿದ್ದರೆ ಕೇಳಿ.'),
    'ml': ('ഉറവിടങ്ങൾ', 'കലണ്ടർ', 'രേഖ', 'കലണ്ടർ ലിങ്ക് വേണമെങ്കിൽ ചോദിക്കൂ.'),
    'mr': ('स्रोत', 'कॅलेंडर', 'दस्तऐवज', 'कॅलेंडर लिंक हवी असल्यास विचारा.'),
    'bn': ('সূত্র', 'ক্যালেন্ডার', 'নথি', 'ক্যালেন্ডার লিঙ্ক চাইলে জিজ্ঞাসা করুন।'),
    'gu': ('સ્રોત', 'કૅલેન્ડર', 'દસ્તાવેજ', 'કૅલેન્ડર લિંક જોઈએ તો પૂછો.'),
    'pa': ('ਸਰੋਤ', 'ਕੈਲੰਡਰ', 'ਦਸਤਾਵੇਜ਼', 'ਕੈਲੰਡਰ ਲਿੰਕ ਚਾਹੀਦਾ ਹੋਵੇ ਤਾਂ ਪੁੱਛੋ।'),
    'od': ('ଉତ୍ସ', 'କ୍ୟାଲେଣ୍ଡର', 'ଦଲିଲ', 'କ୍ୟାଲେଣ୍ଡର ଲିଙ୍କ୍ ଦରକାର ହେଲେ ପଚାରନ୍ତୁ।'),
}


def plain(value: str) -> str:
    """Keep source text from injecting WhatsApp formatting into template headings."""
    return re.sub(r'\s+', ' ', str(value)).strip().translate(str.maketrans('', '', '*_~`'))


def friendly_date(value: str | None) -> str:
    if not value:
        return ''
    try:
        parsed = date.fromisoformat(value)
        return f'{parsed:%a}, {parsed.day} {parsed:%b %Y}'
    except ValueError:
        return plain(value)


def source_line(source: dict) -> str:
    sender = plain(source.get('sender') or 'Teacher')
    try:
        stamp = datetime.fromisoformat(source.get('timestamp', '').replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Timestamp needs timezone')
        stamp = stamp.astimezone(IST)
        clock = stamp.strftime('%I:%M %p').lstrip('0').lower()
        when = f'{stamp.day} {stamp:%b %Y} · {clock}'
        return f'{sender} · {when} IST'
    except (ValueError, TypeError):
        return sender


def saved_notice(record, class_id: str, source: dict, *, reminder=False) -> str:
    if record.kind == 'school_day':
        title = 'No classes' if record.school_day_status == 'no_classes' else 'Classes as usual'
    elif record.status == 'cancelled':
        title = 'Activity cancelled'
    elif record.status == 'completed':
        title = 'Marked complete'
    elif record.items:
        title = 'What to bring'
    elif record.sections:
        title = 'Study checklist' if record.kind == 'syllabus' else 'Class notes'
    else:
        title = 'School update'
    lines = [f'✓ *{title}*', f'Class {plain(class_id)}' + (f' · {plain(record.subject)}' if record.subject else '')]
    if record.due_date:
        lines.append(friendly_date(record.due_date))
    elif record.date_as_written:
        lines.append(f'Date to confirm: {plain(record.date_as_written)}')
    if record.summary:
        lines += ['', plain(record.summary)]
    if record.items:
        lines += ['', *('• ' + plain(item) for item in record.items)]
    for section in record.sections:
        lines.append('')
        if section.chapter:
            chapter = plain(section.chapter)
            if chapter.isdigit():
                chapter = 'Chapter ' + chapter
            lines.append('*' + chapter + '*')
        lines.extend('• ' + plain(topic) for topic in section.topics)
        if section.pages:
            lines.append('Pages ' + plain(section.pages))
    if record.instructions:
        lines += ['', '*Remember*', *('• ' + plain(item) for item in record.instructions)]
    unclear = list(dict.fromkeys(record.unclear))
    if record.date_as_written and not record.due_date and not unclear:
        unclear.append('Please confirm the full date, including the year.')
    if unclear:
        lines += ['', '*Please confirm*', *('• ' + plain(item) for item in unclear)]
    if reminder:
        lines += ['', 'Reminder scheduled.']
    lines += ['', '_Saved · ' + source_line(source) + '_']
    return '\n'.join(lines)


def requested_link_types(question: str, suggested=()) -> list[str]:
    """Keep explicit navigation usable if the model omits its optional UI field.

    This selects display-only links from already authorized/cited facts. It never
    selects school records, executes an action, or grants access.
    """
    selected = set(suggested)
    location = re.search(r'\b(where|find|open|send|share|link|show)\b|कहाँ|कहां|लिंक|भेज|எங்கே|இணைப்பு|அனுப்பு|ఎక్కడ|లింక్|పంప', question, re.I)
    if location:
        if re.search(r'\b(notes?|pdf|documents?)\b|नोट्स|दस्तावेज|குறிப்புகள்|ஆவணம்|నోట్స్|పత్రం', question, re.I):
            selected.add('document')
        if re.search(r'\bcalendar\b|कैलेंडर|நாட்காட்டி|காலண்டர்|క్యాలెండర్', question, re.I):
            selected.add('calendar')
    return sorted(selected & {'calendar', 'document'})


def answer_text(text: str, facts: list[dict], language: str, requested_links=()) -> str:
    labels = LABELS.get(language.split('-')[0], LABELS['en'])
    # Links come only from the authorized, cited database records below.
    body = re.sub(r'https?://[^\s<>]+', '', text)
    for fact in facts:
        body = body.replace('[' + fact['source_id'] + ']', '').replace(fact['source_id'], '')
    body = re.sub(r'\*\*([^\n*]+)\*\*', r'*\1*', body)
    body = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', body, flags=re.M)
    # Drop empty labels left after removing provider-echoed IDs/links.
    labels_pattern = r'(?:sources?|calendar|document|स्रोत|कैलेंडर|दस्तावेज़|ஆதாரங்கள்|நாட்காட்டி|ஆவணம்)'
    body = re.sub(r'^\s*[*_]*' + labels_pattern + r'\s*:?[*_]*\s*:?[ \t]*$', '', body, flags=re.M | re.I)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()
    sources = [source_line(fact['source']) for fact in facts]
    # One source per line, no database IDs, UTC timestamps or automatic URLs.
    blocks = [body, '*' + labels[0] + '*\n' + '\n'.join(f'• {s}' for s in dict.fromkeys(sources))]
    seen = set()
    for fact in facts:
        for kind, label in (('document', labels[2]), ('calendar', labels[1])):
            if kind not in requested_links:
                continue
            item = fact['source'].get(kind) or {}
            if kind == 'calendar' and item.get('status') != 'synced':
                continue
            url = item.get('url', '')
            if url.startswith('https://') and url not in seen:
                seen.add(url)
                subject = plain(fact['extraction'].get('subject') or '')
                day = friendly_date(fact['extraction'].get('due_date'))
                detail = ' · '.join(filter(None, [subject, day]))
                blocks.append(f'*{label}*' + (f' · {detail}' if detail else '') + '\n' + url)
    return '\n\n'.join(blocks)


def calendar_saved(record: dict, class_id: str) -> str:
    details = ' · '.join(filter(None, ['Class ' + plain(class_id), plain(record.get('subject') or '')]))
    return f'📅 *Calendar updated*\n{details}\n{friendly_date(record.get("due_date"))} · all-day\n\nAsk “Show the calendar entry” for the link.'


def error_message(message: str) -> str:
    if 'could not hear' in message:
        return '*I couldn’t hear that clearly*\n\nPlease record a short voice note again, or type your message.'
    return '*Couldn’t finish that*\n\n' + message
