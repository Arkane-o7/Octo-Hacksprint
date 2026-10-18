"""Durable numbered menus over ordinary WAHA text; never an authority source."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import time

from .menu_copy import LANGUAGES, copy, menu_language
from .presentation import answer_text, plain

MENU_TTL = 30 * 60
OPEN_MENU = {'menu', 'help', 'hi', 'hello', 'start', 'मेन्यू', 'मेनू', 'मदद', 'नमस्ते', 'உதவி', 'வணக்கம்',
             'మెనూ', 'సహాయం', 'నమస్కారం', 'मदत', 'नमस्कार', 'মেনু', 'সাহায্য', 'নমস্কার', 'મેનુ', 'મદદ', 'નમસ્તે'}
NEUTRAL_MENU_COMMANDS = {'menu', 'help', 'start', '0'}
CHOOSE_LABEL = {'en': 'Choose', 'hi': 'चुनें', 'ta': 'தேர்ந்தெடுக்கவும்', 'te': 'ఎంచుకోండి',
                'mr': 'निवडा', 'bn': 'বেছে নিন', 'gu': 'પસંદ કરો'}
TAP_HINT = {'en': 'Tap the button below, or reply with a number.',
            'hi': 'नीचे का बटन दबाएँ या नंबर भेजें।',
            'ta': 'கீழே உள்ள பொத்தானைத் தொடவும் அல்லது எண்ணை அனுப்பவும்.',
            'te': 'కింద ఉన్న బటన్‌ను నొక్కండి లేదా సంఖ్యను పంపండి.',
            'mr': 'खालील बटण दाबा किंवा क्रमांक पाठवा.',
            'bn': 'নিচের বোতামে ট্যাপ করুন বা নম্বর পাঠান।',
            'gu': 'નીચેનું બટન દબાવો અથવા નંબર મોકલો.'}
QUESTIONS = {
    'en-IN': {'1': 'What are the saved school notices for today?', '2': 'What are the saved school notices for tomorrow?', '3': 'Show the saved class notes, syllabus and document links.'},
    'hi-IN': {'1': 'आज के लिए स्कूल की क्या जानकारी सेव है?', '2': 'कल के लिए स्कूल की क्या जानकारी सेव है?', '3': 'सेव किए हुए कक्षा के नोट्स, पाठ्यक्रम और दस्तावेज़ लिंक दिखाएँ।'},
    'ta-IN': {'1': 'இன்றைக்கு சேமிக்கப்பட்ட பள்ளி அறிவிப்புகள் என்ன?', '2': 'நாளைக்கு சேமிக்கப்பட்ட பள்ளி அறிவிப்புகள் என்ன?', '3': 'சேமிக்கப்பட்ட வகுப்புக் குறிப்புகள், பாடத்திட்டம் மற்றும் ஆவண இணைப்புகளைக் காட்டு.'},
    'te-IN': {'1': 'ఈరోజు కోసం సేవ్ చేసిన పాఠశాల ప్రకటనలు ఏమిటి?', '2': 'రేపటి కోసం సేవ్ చేసిన పాఠశాల ప్రకటనలు ఏమిటి?', '3': 'సేవ్ చేసిన తరగతి నోట్స్, సిలబస్, పత్రాల లింకులు చూపించండి.'},
    'mr-IN': {'1': 'आजसाठी शाळेच्या कोणत्या सूचना जतन केल्या आहेत?', '2': 'उद्यासाठी शाळेच्या कोणत्या सूचना जतन केल्या आहेत?', '3': 'जतन केलेल्या वर्गाच्या नोट्स, अभ्यासक्रम आणि कागदपत्रांच्या लिंक्स दाखवा.'},
    'bn-IN': {'1': 'আজকের জন্য স্কুলের কী কী বিজ্ঞপ্তি সংরক্ষিত আছে?', '2': 'আগামীকালের জন্য স্কুলের কী কী বিজ্ঞপ্তি সংরক্ষিত আছে?', '3': 'সংরক্ষিত ক্লাসের নোট, পাঠ্যসূচি ও নথির লিঙ্ক দেখান।'},
    'gu-IN': {'1': 'આજ માટે શાળાની કઈ સૂચનાઓ સાચવેલી છે?', '2': 'આવતીકાલ માટે શાળાની કઈ સૂચનાઓ સાચવેલી છે?', '3': 'સાચવેલી વર્ગની નોટ્સ, અભ્યાસક્રમ અને દસ્તાવેજોની લિંક્સ બતાવો.'},
}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def scope(parent):
    return fingerprint({key: parent.get(key) for key in ('id', 'role', 'student_ids', 'classes', 'class_wide_only')})


@dataclass
class MenuRoute:
    handled: bool = False
    text: str = ''
    student_id: str | None = None
    selected: bool = False
    links: tuple[str, ...] = ()


class Menus:
    def __init__(self, app):
        self.app = app
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS ux_menus (
                session TEXT, chat TEXT, person TEXT, scope TEXT NOT NULL,
                state TEXT NOT NULL, expires REAL NOT NULL,
                PRIMARY KEY(session,chat,person));
            CREATE TABLE IF NOT EXISTS ux_preferences (
                session TEXT, chat TEXT, person TEXT, preferences TEXT NOT NULL,
                PRIMARY KEY(session,chat,person));
            CREATE TABLE IF NOT EXISTS ux_menu_inputs (
                source_key TEXT PRIMARY KEY, scope TEXT NOT NULL, state TEXT NOT NULL);
        ''')

    @property
    def db(self):
        return self.app.store.db

    @staticmethod
    def key(event, parent):
        return event.session, event.chat_id, parent['id']

    def _saved_preferences(self, event, parent):
        row = self.db.execute('SELECT preferences FROM ux_preferences WHERE session=? AND chat=? AND person=?', self.key(event, parent)).fetchone()
        return json.loads(row[0]) if row else {}

    def preferences(self, event, parent):
        if event.is_group:
            return parent
        return {**parent, **self._saved_preferences(event, parent)}

    def _preference(self, event, parent, **values):
        # Only explicit display/audio settings; never identity or permissions.
        assert set(values) <= {'language', 'voice_replies'}
        saved = self._saved_preferences(event, parent)
        saved.update(values)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO ux_preferences VALUES(?,?,?,?)', (*self.key(event, parent), json.dumps(saved)))

    def _set(self, sid, event, parent, page, language, **extra):
        state = dict(page=page, language=language, message_key=f'{sid}:answer', **extra)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO ux_menus VALUES(?,?,?,?,?,?)',
                            (*self.key(event, parent), scope(parent), json.dumps(state), time.time() + MENU_TTL))
        return state

    def welcome(self, sid, event, parent):
        """Queue an unsolicited join welcome atomically; there is no user quote."""
        language = parent.get('language', 'en-IN')
        text = copy('welcome', language) + '\n\n' + copy('main', language)
        if self.app.settings.mode == 'offline':
            text = '[OFFLINE DEMO — synthetic fixture responses; no live delivery]\n' + text
        # Caller owns the transaction; do not commit in Store.reply or _set.
        self.db.execute('INSERT OR IGNORE INTO outbox(dedupe_key,chat_id,text) VALUES(?,?,?)',
                        (f'{sid}:answer', event.chat_id, text))
        state = dict(page='main', language=language, message_key=f'{sid}:answer')
        self.db.execute('INSERT OR REPLACE INTO ux_menus VALUES(?,?,?,?,?,?)',
                        (*self.key(event, parent), scope(parent), json.dumps(state), time.time() + MENU_TTL))

    def clear(self, event, parent):
        with self.db:
            self.db.execute('DELETE FROM ux_menus WHERE session=? AND chat=? AND person=?', self.key(event, parent))

    def outgoing(self, reply):
        """Render only the current scoped menu, never arbitrary model text."""
        if not self.app.settings.tappable_menus or reply['chat_id'].endswith('@g.us'):
            return None
        row = self.db.execute("SELECT state,expires FROM ux_menus WHERE chat=? AND json_extract(state,'$.message_key')=?",
                              (reply['chat_id'], reply['dedupe_key'])).fetchone()
        if not row or row['expires'] <= time.time():
            return None
        state = json.loads(row['state'])
        page = state['page']
        if page not in ('main', 'settings', 'languages', 'audio', 'ask', 'answer'):
            return None
        text = copy('footer' if page == 'answer' else page, state['language'])
        token = fingerprint(state['message_key'])[:16]
        rows = [{'title': label[:24], 'rowId': f'octo:{token}:{number}'}
                for number, label in re.findall(r'(?m)^([0-9]{1,2}) · (.+)$', text)]
        # Preserve long answers as ordinary text instead of truncating facts.
        if not rows or len(rows) > 10 or len(reply['text']) > 3500:
            return None
        button = CHOOSE_LABEL.get(state['language'].split('-')[0], 'Choose')
        return {'title': 'Octo', 'description': reply['text'], 'button': button,
                'footer': TAP_HINT.get(state['language'].split('-')[0], TAP_HINT['en']),
                'sections': [{'title': button, 'rows': rows}]}

    def _snapshot(self, event, parent):
        # Save the interpretation BEFORE changing pages: restart cannot reinterpret
        # "1" as a different action after moving from one menu to another.
        old = self.db.execute('SELECT scope,state FROM ux_menu_inputs WHERE source_key=?', (event.source_key,)).fetchone()
        if old:
            return json.loads(old['state']) if old['scope'] == scope(parent) else {}
        row = self.db.execute('SELECT * FROM ux_menus WHERE session=? AND chat=? AND person=?', self.key(event, parent)).fetchone()
        state = {}
        if row and row['scope'] == scope(parent) and row['expires'] > time.time():
            candidate = json.loads(row['state'])
            delivered = self.db.execute('SELECT status,remote_id FROM outbox WHERE dedupe_key=?', (candidate['message_key'],)).fetchone()
            if delivered and delivered['status'] in ('sent', 'fixture'):
                state = {**candidate, 'expires': row['expires'], 'remote_id': delivered['remote_id']}
        with self.db:
            self.db.execute('INSERT INTO ux_menu_inputs VALUES(?,?,?)', (event.source_key, scope(parent), json.dumps(state)))
        return state

    def show(self, sid, event, parent, page='main', *, language=None, prefix=''):
        language = language or parent.get('language', 'en-IN')
        self.app.reply(sid, event, (prefix + '\n\n' if prefix else '') + copy(page, language))
        self._set(sid, event, parent, page, language)
        return MenuRoute(handled=True)

    def choose_child(self, sid, event, parent, text, students, language, links=()):
        lines = [copy('choose', language), '']
        lines.extend(f"{index} · {plain(student['name'])}" for index, student in enumerate(students, 1))
        lines += ['', copy('hint', language)]
        self.app.reply(sid, event, '\n'.join(lines))
        self._set(sid, event, parent, 'children', language, question=text,
                  children=[student['id'] for student in students], links=list(links))

    def answer_menu(self, sid, event, parent, answer, facts, students):
        if event.is_group:
            return ''
        self._set(sid, event, parent, 'answer', answer.language_code,
                  speech=answer.spoken_text or answer.text,
                  facts={f['source_id']: fingerprint(f['extraction']) for f in facts},
                  children=[s['id'] for s in students])
        return '\n\n' + copy('footer', answer.language_code)

    def _answer_facts(self, state, parent):
        allowed = self.app.roster.permitted_students(parent)
        ids = state.get('children', [])
        if not set(ids) <= {s['id'] for s in allowed}:
            return None
        students = [s for s in allowed if s['id'] in ids]
        current = {f['source_id']: f for f in self.app.store.facts_for(parent, students)}
        wanted = state.get('facts', {})
        if not wanted or any(sid not in current or fingerprint(current[sid]['extraction']) != digest for sid, digest in wanted.items()):
            return None
        return [current[sid] for sid in wanted]

    async def handle(self, sid, event, parent, text):
        clean = text.strip().casefold().rstrip('!?.।')
        selection = None
        if event.menu_choice_id is not None:
            selection = re.fullmatch(r'octo:([a-f0-9]{16}):([0-9]{1,2})', event.menu_choice_id)
            if not selection:
                self.app.reply(sid, event, copy('fresh', parent.get('language', 'en-IN')))
                return MenuRoute(handled=True)
            clean = selection[2]
        opening = clean in OPEN_MENU or clean == '0'
        numeric = bool(re.fullmatch(r'[0-9]{1,2}', clean))
        language = menu_language(text, parent)
        # Only typed menu interactions. Voice/forwarded content cannot change a
        # preference or execute a stored choice, even if STT says a number.
        if event.is_group:
            if opening or numeric:
                self.app.reply(sid, event, copy('group', language))
                return MenuRoute(handled=True)
            return MenuRoute(text=text)
        if not opening and not numeric:
            self.clear(event, parent)
            return MenuRoute(text=text)
        if event.kind != 'text' or event.forwarded:
            self.app.reply(sid, event, copy('fresh', language))
            return MenuRoute(handled=True)
        state = self._snapshot(event, parent)
        if selection and (not state or state['expires'] <= time.time()
                          or fingerprint(state['message_key'])[:16] != selection[1]):
            return self.show(sid, event, parent, language=language, prefix=copy('expired', language))
        if not selection and (event.is_quoted or event.quoted_message_id):
            if not state.get('remote_id') or state['remote_id'] != event.quoted_message_id:
                self.app.reply(sid, event, copy('fresh', language))
                return MenuRoute(handled=True)
        if opening:
            if clean in NEUTRAL_MENU_COMMANDS:
                language = self._saved_preferences(event, parent).get('language', language)
            return self.show(sid, event, parent, language=language)
        if not state or state['expires'] <= time.time():
            return self.show(sid, event, parent, language=language, prefix=copy('expired', language))
        language = state['language']
        page = state['page']
        if page == 'main':
            if clean in ('1', '2', '3'):
                return MenuRoute(text=QUESTIONS.get(language, QUESTIONS['en-IN'])[clean],
                                 selected=True, links=('document',) if clean == '3' else ())
            if clean == '4':
                return self.show(sid, event, parent, 'settings', language=language)
        elif page == 'settings' and clean in ('1', '2'):
            return self.show(sid, event, parent, 'languages' if clean == '1' else 'audio', language=language)
        elif page == 'languages' and clean in LANGUAGES:
            language = LANGUAGES[clean][0]
            self._preference(event, parent, language=language)
            return self.show(sid, event, parent, language=language, prefix=copy('saved', language))
        elif page == 'audio' and clean in ('1', '2'):
            self._preference(event, parent, voice_replies=clean == '2')
            return self.show(sid, event, parent, language=language, prefix=copy('saved', language))
        elif page == 'children' and 1 <= int(clean) <= len(state['children']):
            chosen = state['children'][int(clean) - 1]
            if chosen in parent['student_ids']:
                return MenuRoute(text=state['question'], student_id=chosen, selected=True, links=tuple(state.get('links', [])))
        elif page == 'answer':
            if clean == '3':
                return self.show(sid, event, parent, 'ask', language=language)
            if clean in ('1', '2'):
                facts = self._answer_facts(state, parent)
                if facts is None:
                    return self.show(sid, event, parent, language=language, prefix=copy('stale', language))
                if clean == '2':
                    self.app.reply(sid, event, answer_text(copy('sources', language), facts, language, ['calendar', 'document']) + '\n\n' + copy('footer', language))
                    self._set(sid, event, parent, 'answer', language, speech=state['speech'], facts=state['facts'], children=state['children'])
                else:
                    if self.app.settings.mode == 'offline':
                        self.app.reply(sid, event, copy('offline', language))
                    elif not self.db.execute('SELECT 1 FROM outbox WHERE dedupe_key=?', (f'{sid}:audio',)).fetchone():
                        try:
                            path = await self.app.ai.synthesize(state['speech'], language, self.app.media_dir / f'{sid}-read.mp3')
                            self.app.store.reply(f'{sid}:audio', event.chat_id, '', kind='voice', path=str(path), reply_to=event.message_id, reply_chat_id=event.chat_id)
                        except Exception:
                            self.app.reply(sid, event, copy('audio_failed', language))
                return MenuRoute(handled=True)
        return self.show(sid, event, parent, language=language, prefix=copy('expired', language))
