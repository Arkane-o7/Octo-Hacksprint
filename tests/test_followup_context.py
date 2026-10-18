"""Offline conversations: actual routing/persistence with synthetic provider replies."""
import json
from datetime import timedelta

from octo.contracts import Extraction, GroundedAnswer, Media
from octo.storage import Store
from test_core import octo, notice, question, put, output


async def undated(octo, identifier='UNDATED', **changes):
    async def extract(*args):
        return Extraction(kind='requirement', items=['crayons'], summary='Bring crayons')
    octo.ai.extract_notice = extract
    await put(octo, notice(identifier, text='Bring crayons.', **changes))


async def test_teacher_date_reply_amends_once_after_restart(octo):
    await undated(octo)
    original = octo.store.class_facts('5B')[0]
    octo.store.close()
    octo.store = Store(octo.settings.data_dir / 'test.sqlite3')
    event = notice('DATE', text='Tomorrow', timestamp=notice().timestamp + timedelta(days=1))
    await put(octo, event)
    facts = octo.store.class_facts('5B')
    assert len(facts) == 1 and facts[0]['source_id'] == original['source_id']
    assert facts[0]['extraction']['items'] == ['crayons']
    assert facts[0]['extraction']['due_date'] == '2026-10-20'
    assert facts[0]['source']['message_id'] == 'UNDATED'
    assert facts[0]['source']['clarifications'][0]['message_id'] == 'DATE'
    await octo.process(octo.store.message(event.source_key))  # crash/retry completion
    assert len(octo.store.class_facts('5B')) == 1
    assert octo.store.db.execute('SELECT COUNT(*) FROM reminders').fetchone()[0] == 0  # offline policy
    # A stale OCR/import retry must not overwrite the completed fact.
    await octo._save_extraction(original['source_id'], notice('UNDATED'), octo.roster.resolve(notice()), Extraction(kind='requirement', items=['crayons']))
    assert octo.store.class_facts('5B')[0]['extraction']['due_date'] == '2026-10-20'


async def test_multiple_pending_bare_date_and_wrong_chat_do_not_amend(octo):
    await put(octo, notice('BARE', text='Tomorrow'))
    assert not octo.store.class_facts('5B')
    await undated(octo)
    assert await octo.ingest(notice('WRONGCHAT', chat_id='demo-teacher', is_group=False, text='Tomorrow')) == 'ignored'
    assert octo.store.class_facts('5B')[0]['extraction']['due_date'] is None
    await undated(octo, 'SECOND')
    await put(octo, notice('AMBIGUOUS', text='Tomorrow'))
    assert all(f['extraction']['due_date'] is None for f in octo.store.class_facts('5B'))
    assert 'full corrected notice' in output(octo)


async def test_photo_followup_preserves_ocr_and_content(octo):
    async def extract(*args):
        return Extraction(kind='syllabus', sections=[{'chapter': 'Fractions', 'topics': ['halves']}])
    octo.ai.extract_syllabus = extract
    event = notice('PHOTO', kind='image', text='', media=Media(url='fixture://board-clear', mime_type='image/jpeg'))
    await put(octo, event)
    await put(octo, notice('DATE', text='20 October 2026'))
    fact = octo.store.class_facts('5B')[0]
    assert fact['extraction']['sections'][0]['chapter'] == 'Fractions'
    assert fact['extraction']['due_date'] == '2026-10-20'
    assert fact['source']['ocr_text']
    assert fact['source']['media_path']


async def test_missing_year_and_unreadable_notice(octo):
    async def extract(*args):
        return Extraction(kind='requirement', items=['crayons'], date_as_written='21 October', due_date='2026-10-21')
    octo.ai.extract_notice = extract
    await put(octo, notice('YEAR', text='Bring crayons on 21 October'))
    assert octo.store.class_facts('5B')[0]['extraction']['due_date'] is None
    await put(octo, notice('YEAR_REPLY', text='2027'))
    assert octo.store.class_facts('5B')[0]['extraction']['due_date'] == '2027-10-21'


async def seed_parent(octo):
    await put(octo, notice())
    fact = octo.store.class_facts('5B')[0]
    octo.ai.answer_override = GroundedAnswer(language_code='en-IN', text='Bring crayons.', source_ids=[fact['source_id']])
    await put(octo, question())
    return fact


async def test_parent_language_links_and_audio_use_actual_sources_no_cart(octo):
    fact = await seed_parent(octo)
    seen = []
    async def answer(text, facts, names, language):
        seen.append((text, facts))
        return GroundedAnswer(language_code='hi-IN', text='रंग लाएँ', source_ids=[fact['source_id']], proposed_items=['crayons'], cart_request_quote='please')
    octo.ai.answer = answer
    await put(octo, question('HINDI', text='In Hindi please'))
    assert 'REFERENCE_CONTEXT' in seen[-1][0]
    assert seen[-1][1][0]['extraction']['due_date'] == '2026-10-19'
    assert not octo.store.db.execute("SELECT 1 FROM outbox WHERE dedupe_key LIKE '%:cart'").fetchone()
    await put(octo, question('NOTES', text='Send its notes'))
    assert len(seen[-1][1]) == 1
    await put(octo, question('AUDIO', text='Read that aloud'))
    intents = octo.contexts.get(question('AUDIO'), octo.roster.resolve(question()), 'answer_intent')
    assert any(data['read_aloud'] and data['source_key'] == question('AUDIO').source_key for _, data in intents)
    await put(octo, question('NEW', text='What is the mathematics syllabus?'))
    assert 'REFERENCE_CONTEXT' not in seen[-1][0]


async def test_stale_expired_and_other_chat_context_clarifies(octo):
    fact = await seed_parent(octo)
    before = len(octo.ai.answer_calls)
    await put(octo, question('OTHER', chat_id='demo-class-5b@g.us', is_group=True, text='Send its notes'))
    assert len(octo.ai.answer_calls) == before
    with octo.store.db:
        record = fact['extraction']; record['items'] = ['pencils']
        octo.store.db.execute('UPDATE facts SET extraction=? WHERE source_id=?', (json.dumps(record), fact['source_id']))
    await put(octo, question('STALE', text='Send its notes'))
    assert len(octo.ai.answer_calls) == before
    with octo.store.db:
        octo.store.db.execute('UPDATE conversation_context SET expires=0')
    await put(octo, question('EXPIRED', text='In Hindi please'))
    assert len(octo.ai.answer_calls) == before
    assert 'full question' in output(octo)


async def test_multiple_children_selection_and_explicit_topic_switch(octo):
    fact = await seed_parent(octo)
    octo.ai.answer_override = GroundedAnswer(language_code='en-IN', text='Bring crayons', source_ids=[fact['source_id']])
    await put(octo, question('MEERA', sender_id='demo-parent-b', chat_id='demo-parent-b', text='What should Meera bring?'))
    assert octo.ai.answer_calls[-1][1] == ['Meera']
    await put(octo, question('MEERA_FOLLOW', sender_id='demo-parent-b', chat_id='demo-parent-b', text='And Friday?'))
    assert octo.ai.answer_calls[-1][1] == ['Meera']
    before = len(octo.ai.answer_calls)
    await put(octo, question('NEW_AMBIG', sender_id='demo-parent-b', chat_id='demo-parent-b', text='What is the syllabus?'))
    assert len(octo.ai.answer_calls) == before
    assert 'Which student' in output(octo)


async def test_other_teacher_parent_and_expiry_cannot_complete(octo):
    await undated(octo)
    octo.roster.identities['teacher-other'] = {'id': 'teacher-other', 'name': 'Other', 'whatsapp_ids': ['teacher-other'], 'classes': ['5B'], 'role': 'teacher'}
    octo.roster.memberships['demo-class-5b@g.us']['teacher-other'] = ('teacher-other',)
    await put(octo, notice('OTHER_TEACHER', sender_id='teacher-other', text='Tomorrow'))
    await put(octo, question('PARENT_DATE', text='Tomorrow'))
    assert octo.store.class_facts('5B')[0]['extraction']['due_date'] is None
    with octo.store.db:
        octo.store.db.execute("UPDATE conversation_context SET expires=0 WHERE kind='teacher'")
    await put(octo, notice('EXPIRED', text='Tomorrow'))
    assert octo.store.class_facts('5B')[0]['extraction']['due_date'] is None


async def test_clarification_queues_one_calendar_and_reminder_per_parent(octo):
    # Live policy against synthetic adapters only: no real services or contacts.
    from types import SimpleNamespace
    from datetime import datetime, timezone
    stamp = datetime.now(timezone.utc)
    await undated(octo, timestamp=stamp)
    octo.settings.mode = 'live'
    octo.calendar = SimpleNamespace(configured=True)
    event = notice('DATE', text='Tomorrow', timestamp=stamp)
    assert await octo.ingest(event) == 'queued'
    await octo.process(octo.store.message(event.source_key))
    await octo.process(octo.store.message(event.source_key))
    assert octo.store.db.execute('SELECT COUNT(*) FROM facts').fetchone()[0] == 1
    assert octo.store.db.execute('SELECT COUNT(*) FROM calendar_jobs').fetchone()[0] == 1
    assert octo.store.db.execute('SELECT COUNT(*) FROM reminders').fetchone()[0] == 2


async def test_undated_school_day_and_unreadable_photo(octo):
    async def school_day(*args):
        return Extraction(kind='school_day', school_day_status='no_classes')
    octo.ai.extract_notice = school_day
    await put(octo, notice('CLOSURE', text='No classes.'))
    assert not octo.store.class_facts('5B')
    await put(octo, notice('DATE', text='Tomorrow'))
    assert octo.store.class_facts('5B')[0]['extraction']['school_day_status'] == 'no_classes'
    async def unclear(*args):
        return Extraction(kind='syllabus', sections=[{'chapter': 'Unknown', 'topics': ['halves']}], unclear=['The topic is unreadable'])
    octo.ai.extract_syllabus = unclear
    await put(octo, notice('UNCLEAR', kind='image', text='', media=Media(url='fixture://board-clear', mime_type='image/jpeg')))
    await put(octo, notice('NO_TARGET', text='Tomorrow'))
    unclear_fact = next(f for f in octo.store.class_facts('5B') if f['extraction']['kind'] == 'syllabus')
    assert unclear_fact['extraction']['due_date'] is None
