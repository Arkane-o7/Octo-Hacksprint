"""Small UI helpers; callers must authorize before invoking these functions."""
import re

from .i18n import message
from .presentation import plain


def intent(text):
    normalized = re.sub(r'[!?.।]+$', '', text.strip().casefold()).strip()
    for action, aliases in {
        'help': {'hi', 'hello', 'hey', 'help', 'नमस्ते', 'नमस्कार', 'मदद', 'सहायता', 'வணக்கம்', 'உதவி', 'namaste', 'namaskar', 'vanakkam'},
        'tomorrow': {'tomorrow', 'कल', 'நாளை'},
        'test': {'next test', 'अगली परीक्षा', 'அடுத்த தேர்வு'},
        'notes': {'find notes', 'नोट्स खोजें', 'குறிப்புகளைத் தேடு'},
    }.items():
        if normalized in aliases:
            return action
    return None


def welcome(parent, students, lang):
    context = (message('Linked children: {names}', lang, names=', '.join(plain(s['name']) for s in students))
               if students else message('Class-wide notices: {classes}', lang, classes=', '.join(plain(c) for c in parent['classes'])))
    return '\n'.join([message('Hi! I’m Octo. I can help with saved school notices.', lang), context,
                      message('Try: Tomorrow · Next test · Find notes', lang)])


def first_use(db, parent_id, sid):
    # Separate table in the existing encrypted connection. No context/outbox
    # migrations. Retain the first source so replay has identical copy.
    with db:
        db.execute('CREATE TABLE IF NOT EXISTS welcome_seen (parent_id TEXT PRIMARY KEY, source_id TEXT NOT NULL)')
        db.execute('INSERT OR IGNORE INTO welcome_seen VALUES (?, ?)', (parent_id, sid))
    return db.execute('SELECT source_id FROM welcome_seen WHERE parent_id=?', (parent_id,)).fetchone()[0] == sid


def shortcut(text, lang):
    templates = {
        'tomorrow': 'What is scheduled or needed tomorrow? Include any uncertainty in the saved notices.',
        'test': 'When is the next test explicitly mentioned in the saved notices? If no test is confirmed, say so.',
        'notes': 'Find the saved class notes and share an available document link. If no document is available, say so.',
    }
    return message(templates[intent(text)], lang) if intent(text) in templates else text
