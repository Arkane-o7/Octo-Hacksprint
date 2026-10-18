"""Combined transcript acceptance: encrypted fixtures, no credentials or network."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from octo.cart import CartService
from octo.config import Settings
from octo.contracts import Extraction, GroundedAnswer, Media, Transcript
from octo.core import Octo, Roster
from octo.offline import OfflineAI, OfflineTransport
from octo.replay import drain
from octo.storage import Store
from test_core import notice, question

KEY = 'ab' * 32  # Public synthetic test key, never a deployment secret.


class Transport(OfflineTransport):
    async def send_text(self, chat_id, text, reply_to=None):
        await super().send_text(chat_id, text, reply_to)
        return 'fixture-sent'

    async def send_voice(self, chat_id, path):
        self.sent.append({'chat_id': chat_id, 'audio': path.read_bytes()})
        return 'fixture-audio'


class AI(OfflineAI):
    def __init__(self):
        self.calls = []
        self.speech = []

    async def answer(self, prompt, facts, names, language):
        self.calls.append((prompt, facts, names, language))
        selected = next((f for f in facts if f['extraction'].get('subject') == ('Math' if 'mathematics' in prompt else 'Science')), facts[0])
        return GroundedAnswer(text='Fixture: ' + selected['extraction'].get('subject', 'School'),
                              language_code=language, source_ids=[selected['source_id']])

    async def synthesize(self, text, language, destination):
        self.speech.append((text, language))
        destination.write_bytes(b'SYNTHETIC, NOT PLAYABLE')
        return destination


class Calendar:
    configured = True
    def __init__(self):
        self.calls = []
        self.fail = False
    async def sync_fact(self, fact):
        self.calls.append(fact)
        if self.fail:
            raise TimeoutError('synthetic')
        return {'status': 'synced', 'event_id': 'fixture', 'url': 'https://calendar.google.com/calendar/event?eid=fixture'}


@pytest.fixture
def app(tmp_path):
    obj = Octo(Settings(data_dir=tmp_path, poll_seconds=0, calendar_id='fixture-calendar'),
               Store(tmp_path/'fixture.sqlite3', key=KEY), Roster(Path('roster.example.json')),
               AI(), Transport(), calendar=Calendar())
    obj.roster.identities['demo-parent-a']['voice_replies'] = False
    yield obj
    obj.store.close()


def restart(app):
    app.store.close()
    app.store = Store(app.settings.data_dir/'fixture.sqlite3', key=KEY)


async def send(app, event):
    assert await app.ingest(event) == 'queued'
    await drain(app)


@pytest.mark.parametrize('photo', [False, True])
async def test_missing_date_restart_completion_quote_calendar_and_provenance(app, photo):
    stamp = datetime.now(timezone.utc)
    async def extract(*args):
        return Extraction(kind='requirement', items=['crayons'], date_as_written='21 October', due_date='2099-10-21')
    app.ai.extract_notice = app.ai.extract_syllabus = extract
    original = notice('SOURCE', text='Bring crayons on 21 October', timestamp=stamp)
    if photo:
        original = original.model_copy(update={'kind': 'image', 'media': Media(url='fixture://board-clear', mime_type='image/jpeg')})
    await send(app, original)
    assert app.store.class_facts('5B')[0]['extraction']['due_date'] is None
    confirmations = [r for r in app.store.replies() if r['reply_to'] == 'SOURCE' and not r['dedupe_key'].endswith(':ack')]
    assert len(confirmations) == 1
    assert confirmations[0]['text'].count('Reply with just the date.') == 1
    assert confirmations[0]['text'].count('*Please confirm*') == 1
    assert 'When should students bring' not in confirmations[0]['text']
    assert 'crayons' in confirmations[0]['text'] and 'Ms. Rao' in confirmations[0]['text']
    assert 'When should students bring these items?' in app.store.class_facts('5B')[0]['extraction']['unclear']
    restart(app)
    app.settings.mode = 'live'  # Fake providers only; enable scheduling policy.
    followup = notice('DATE', text=str(stamp.year + 1), timestamp=stamp + timedelta(minutes=1))
    await app.ingest(followup)
    await app.process(app.store.next_message())
    reply = next(r for r in app.store.replies() if r['dedupe_key'].endswith(':date-clarified'))
    assert reply['reply_to'] == 'DATE'
    restart(app)
    await app.calendar_one()  # Must deliver clarification before fake Calendar work.
    assert app.transport.sent[-1]['reply_to'] == 'DATE'
    await app.process(app.store.message(followup.source_key))
    await drain(app)
    fact = app.store.class_facts('5B')[0]
    assert fact['source']['message_id'] == 'SOURCE'
    assert fact['source']['text'] == original.text
    assert fact['source']['clarifications'][0]['message_id'] == 'DATE'
    assert bool(fact['source']['ocr_text']) == photo
    assert fact['extraction']['due_date'] == f'{stamp.year + 1}-10-21'
    assert len(app.calendar.calls) == 1
    for table, count in [('facts', 1), ('calendar_jobs', 1), ('reminders', 2)]:
        assert app.store.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == count
    assert not any(':calendar:' in r['dedupe_key'] or 'Hi! I’m Octo' in r['text'] for r in app.store.replies())
    assert not (app.settings.data_dir/'fixture.sqlite3').read_bytes().startswith(b'SQLite format 3')


async def seed(app):
    for subject in ['Science', 'Math']:
        event = notice(subject, text=subject)
        app.store.save_fact(subject, app.roster.resolve(event), Extraction(kind='syllabus', subject=subject,
            sections=[{'chapter': subject, 'topics': ['Original topic']}], due_date='2026-10-21'), event)
        source = app.store.class_facts('5B')[0]['source']
        source['document'] = {'url': 'https://drive.google.com/file/d/fixture-' + subject}
        source['calendar'] = {'status': 'pending', 'url': 'https://calendar.google.com/fixture'}
        app.store.db.execute('UPDATE facts SET provenance=? WHERE source_id=?', (json.dumps(source), subject))
    app.store.db.commit()
    await send(app, question(text='What is the Science syllabus for Aarav?'))


async def test_parent_topic_links_language_and_read_aloud_across_encrypted_restart(app):
    await seed(app)
    for identifier, text in [('NOTES', 'Send notes'), ('CALENDAR', 'Show calendar'), ('LANG', 'In Tamil please')]:
        await send(app, question(identifier, text=text))
        assert [f['source_id'] for f in app.ai.calls[-1][1]] == ['Science']
    assert app.ai.calls[-1][3] == 'ta-IN'
    assert any('https://drive.google.com/file/d/fixture-Science' in r['text'] for r in app.store.replies())
    assert not any('https://calendar.google.com/fixture' in r['text'] for r in app.store.replies())
    restart(app)
    app.settings.mode = 'live'
    await send(app, question('AUDIO', text='Read aloud'))
    assert app.ai.speech == [('Fixture: Science', 'ta-IN')]
    assert app.ai.calls[-1][2:] == (['Aarav'], 'ta-IN')
    await send(app, question('NEW', text='What is the mathematics syllabus?'))
    assert 'REFERENCE_CONTEXT' not in app.ai.calls[-1][0]
    assert len(app.ai.calls[-1][1]) == 2
    await send(app, question('NEWREF', text='Send notes'))
    assert [f['source_id'] for f in app.ai.calls[-1][1]] == ['Math']


@pytest.mark.parametrize('boundary', ['expired', 'chat', 'person', 'students', 'revoked', 'session'])
async def test_saved_topic_does_not_cross_access_boundaries(app, boundary):
    await seed(app)
    event = question('FOLLOW', text='Read aloud')
    if boundary == 'expired':
        app.store.db.execute('UPDATE conversation_context SET expires=0'); app.store.db.commit()
    elif boundary == 'chat':
        event = event.model_copy(update={'chat_id': 'demo-class-5b@g.us', 'is_group': True})
    elif boundary == 'person':
        event = event.model_copy(update={'chat_id': 'demo-parent-b', 'sender_id': 'demo-parent-b'})
    elif boundary == 'students':
        app.roster.identities['demo-parent-a']['student_ids'] = ['meera']
    elif boundary == 'revoked':
        app.roster.set_group_members('demo-class-5b@g.us', [['demo-teacher']])
    elif boundary == 'session':
        event = event.model_copy(update={'session': 'other'})
    before = len(app.ai.calls)
    result = await app.ingest(event)
    await drain(app)
    assert len(app.ai.calls) == before and not app.ai.speech
    assert result == ('ignored' if boundary in ('revoked', 'session') else 'queued')


@pytest.mark.parametrize('kind', ['text', 'voice'])
@pytest.mark.parametrize('group', [False, True])
@pytest.mark.parametrize('preference', [False, True])
async def test_combined_audio_policy(app, kind, group, preference):
    await seed(app)
    app.settings.mode = 'live'
    app.roster.identities['demo-parent-a']['voice_replies'] = preference
    event = question('MATRIX', kind=kind, text='What is the Science syllabus?',
        media=Media(url='fixture://parent-hindi', mime_type='audio/ogg') if kind == 'voice' else None,
        is_group=group, chat_id='demo-class-5b@g.us' if group else 'demo-parent-a')
    await send(app, event)
    assert bool(app.ai.speech) == (not group and (kind == 'voice' or preference))
    if group:
        replies = [r for r in app.store.replies() if r['reply_to'] == 'MATRIX']
        assert all('Linked children' not in r['text'] and 'Hi! I’m Octo' not in r['text'] for r in replies)


async def test_context_quote_voice_and_replay_cannot_approve_or_revive_cart(app):
    await seed(app)
    cart = CartService(app.store.db)
    code = re.search(r'APPROVE ([A-F0-9]{10})', cart.propose('parent-a', 'demo-parent-a', ['crayons']))[1]
    async def transcript(*args):
        return Transcript(text='APPROVE ' + code, language_code='en-IN')
    app.ai.transcribe = transcript
    for index, changes in enumerate([{'is_quoted': True}, {'quoted_message_id': 'old'}, {'forwarded': True},
                                     {'kind': 'voice', 'media': Media(url='fixture://parent-hindi', mime_type='audio/ogg')} ]):
        await send(app, question('BAD' + str(index), text='APPROVE ' + code, **changes))
        assert cart.db.execute('SELECT status FROM carts WHERE code=?', (code,)).fetchone()[0] == 'pending'
    await send(app, question('APPROVE', text='APPROVE ' + code))
    await send(app, question('REPLAY', text='APPROVE ' + code))
    await send(app, question('HISTORY', text='Read aloud'))
    assert cart.db.execute('SELECT status FROM carts WHERE code=?', (code,)).fetchone()[0] == 'approved'
    assert len(cart.db.execute('SELECT * FROM carts').fetchall()) == 1
    assert sum('Demo approval recorded' in r['text'] for r in app.store.replies()) == 1

@pytest.mark.parametrize('text, marker', [('Bring crayons', 'unconfirmed after three attempts'),
    ('क्रेयॉन लाएँ', 'तीन कोशिशों'), ('கிரேயான்கள் கொண்டு வாருங்கள்', 'மூன்று முயற்சிகளுக்கு')])
async def test_calendar_failure_is_localized_once_and_never_success(app, text, marker):
    stamp = datetime.now(timezone.utc)
    due = (stamp + timedelta(days=3)).date().isoformat()
    async def extract(*args):
        return Extraction(kind='requirement', items=['SOURCE ITEM'], date_as_written=due, due_date=due)
    app.ai.extract_notice = extract
    app.settings.mode = 'live'
    app.calendar.fail = True
    await send(app, notice(text=text, timestamp=stamp))
    assert not any(':calendar-error:' in r['dedupe_key'] for r in app.store.replies())
    for _ in range(2):
        app.store.db.execute('UPDATE calendar_jobs SET next_attempt=0'); app.store.db.commit()
        await drain(app)
    errors = [r for r in app.store.replies() if ':calendar-error:' in r['dedupe_key']]
    assert len(errors) == 1 and marker in errors[0]['text']
    assert 'SOURCE ITEM' in app.store.replies()[0]['text']
    assert not any(':calendar:' in r['dedupe_key'] for r in app.store.replies())
    assert app.store.class_facts('5B')[0]['source'].get('calendar', {}).get('status') != 'synced'


async def test_encrypted_uncertain_ack_is_not_replayed(app):
    event = question('VOICE', kind='voice', text='', media=Media(url='fixture://parent-hindi', mime_type='audio/ogg'))
    calls = []
    async def uncertain(chat, text, reply_to=None):
        calls.append(reply_to)
        raise TimeoutError()
    async def stt(*args):
        assert calls == ['VOICE']
        raise TimeoutError()
    app.transport.send_text = uncertain
    app.ai.transcribe = stt
    await app.ingest(event)
    await app.process(app.store.next_message())
    restart(app)
    await app.process(app.store.message(event.source_key))
    ack = [r for r in app.store.replies() if r['dedupe_key'].endswith(':voice-ack')]
    assert len(ack) == 1 and ack[0]['status'] == 'uncertain' and ack[0]['reply_to'] == 'VOICE'
    assert calls == ['VOICE']


async def test_explicit_group_read_aloud_stays_written(app):
    await seed(app)
    await send(app, question('GROUP', is_group=True, chat_id='demo-class-5b@g.us', text='Science syllabus?'))
    app.settings.mode = 'live'
    await send(app, question('GROUP_AUDIO', is_group=True, chat_id='demo-class-5b@g.us', text='Read aloud'))
    assert 'REFERENCE_CONTEXT' in app.ai.calls[-1][0]
    assert not app.ai.speech


@pytest.mark.parametrize('written', ['01/02/2027', '21st October', '21 October'])
async def test_ambiguous_dates_never_schedule_based_on_model_guess(app, written):
    async def extract(*args):
        return Extraction(kind='requirement', items=['crayons'], date_as_written=written, due_date='2027-01-02')
    app.ai.extract_notice = extract
    app.settings.mode = 'live'
    await send(app, notice(text='Bring crayons on ' + written))
    assert app.store.class_facts('5B')[0]['extraction']['due_date'] is None
    assert not app.calendar.calls
    assert not app.store.db.execute('SELECT 1 FROM reminders').fetchone()


async def test_expired_cart_cannot_be_revived_by_followups(app):
    await seed(app)
    cart = CartService(app.store.db)
    code = re.search(r'APPROVE ([A-F0-9]{10})', cart.propose('parent-a', 'demo-parent-a', ['crayons'], now=1))[1]
    await send(app, question('STALE', text='APPROVE ' + code))
    await send(app, question('LANG_STALE', text='In Hindi please'))
    await send(app, question('AUDIO_STALE', text='Read aloud'))
    assert cart.db.execute('SELECT status FROM carts WHERE code=?', (code,)).fetchone()[0] == 'pending'
    assert len(cart.db.execute('SELECT * FROM carts').fetchall()) == 1

@pytest.mark.parametrize('kind,status', [('test', 'active'), ('lesson', 'cancelled'), ('requirement', 'cancelled')])
async def test_narrow_parser_does_not_enable_activity_updates(app, kind, status):
    async def extract(*args):
        return Extraction(kind=kind, status=status, items=['crayons'], due_date='2027-01-01', date_as_written='2027-01-01')
    app.ai.extract_notice = extract
    await send(app, notice(text='Unsupported update'))
    assert not app.store.class_facts('5B')
    assert app.settings.general_brain is False

@pytest.mark.parametrize('kind', ['requirement', 'school_day'])
@pytest.mark.parametrize('text, prompt', [('Bring supplies', 'Reply with just the date.'),
    ('सामग्री लाएँ', 'केवल तारीख़ भेजें।'), ('பொருட்கள் கொண்டு வாருங்கள்', 'தேதியை மட்டும் அனுப்புங்கள்.')])
async def test_single_localized_missing_date_prompt_and_restart(app, kind, text, prompt):
    async def extract(*args):
        return Extraction(kind=kind, items=['crayons', 'a drawing book'] if kind == 'requirement' else [],
                          school_day_status='no_classes' if kind == 'school_day' else None)
    app.ai.extract_notice = extract
    await send(app, notice('MISSING', text=text))
    replies = [r for r in app.store.replies() if r['reply_to'] == 'MISSING']
    assert len(replies) == 1 and replies[0]['text'].count(prompt) == 1
    assert len(app.store.class_facts('5B')) == (1 if kind == 'requirement' else 0)
    if kind == 'school_day':
        assert 'Saved' not in replies[0]['text'] and '✓' not in replies[0]['text']
    restart(app)
    await send(app, notice('COMPLETE', text='Tomorrow'))
    assert len(app.store.class_facts('5B')) == 1
    assert app.store.class_facts('5B')[0]['extraction']['due_date'] == '2026-10-19'


@pytest.mark.parametrize('kind', ['requirement', 'school_day'])
@pytest.mark.parametrize('unclear', [False, True])
async def test_multiple_or_unclear_notices_require_full_correction(app, unclear, kind):
    async def extract(*args):
        return Extraction(kind=kind, items=['crayons'] if kind == 'requirement' else [],
                          school_day_status='no_classes' if kind == 'school_day' else None,
                          unclear=['Quantity is unreadable'] if unclear else [])
    app.ai.extract_notice = extract
    await send(app, notice('FIRST', text='Bring crayons'))
    await send(app, notice('SECOND', text='Bring crayons'))
    replies = [r for r in app.store.replies() if r['reply_to'] == 'SECOND']
    assert len(replies) == 1 and 'full corrected notice' in replies[0]['text']
    assert 'Reply with just the date' not in replies[0]['text']
    if unclear and kind == 'requirement':
        assert 'Quantity is unreadable' in replies[0]['text']
    await send(app, notice('AMBIGUOUS_DATE', text='Tomorrow'))
    assert all(f['extraction']['due_date'] is None for f in app.store.class_facts('5B'))
