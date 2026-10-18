"""Application checks for model-proposed records; no live APIs or delivery."""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from octo.config import Settings
from octo.contracts import Extraction, NoticeDecision, IncomingMessage
from octo.core import Octo, Roster
from octo.offline import OfflineAI, OfflineTransport
from octo.replay import drain
from octo.storage import Store


class Brain(OfflineAI):
    def __init__(self):
        self.decision = NoticeDecision()
        self.calls = []

    async def understand(self, text, stamp, class_label, context, history, students, **kwargs):
        self.calls.append((context, history))
        return self.decision


@pytest.fixture
def app(tmp_path):
    brain = Brain()
    obj = Octo(Settings(data_dir=tmp_path, general_brain=True), Store(tmp_path/'test.sqlite3'),
               Roster(Path('roster.example.json')), brain, OfflineTransport())
    yield obj
    obj.store.close()


def event(identifier='one', text='Teacher notice', **kwargs):
    return IncomingMessage(session='default', message_id=identifier,
                           chat_id='demo-class-5b@g.us', sender_id='demo-teacher',
                           is_group=True, timestamp=datetime.now(timezone.utc), text=text, **kwargs)


async def put(app, message, decision):
    app.ai.decision = decision
    assert await app.ingest(message) == 'queued'
    await drain(app)


async def test_greeting_acknowledgement_and_question_do_not_make_facts(app):
    await put(app, event(text='hi'), NoticeDecision(reply='Hi! Send me the class updates.'))
    await put(app, event('two', text='ok buddy'), NoticeDecision(reply='Got it.'))
    assert app.store.counts()['facts'] == 0
    assert 'Post a class-wide notice' in app.transport.sent[0]['text']
    assert app.ai.calls[-1][1][0]['message'] == 'hi'


async def test_mixed_unstructured_message_can_save_distinct_facts_and_dates(app):
    decision = NoticeDecision(records=[
        Extraction(kind='supplies', summary='Bring crayons tomorrow.', items=['crayons'], date_as_written='tomorrow'),
        Extraction(kind='homework', summary='Read poem 2 on 25 October 2026.', date_as_written='25 October 2026'),
        Extraction(kind='school_bus', summary='Bus pickup is at the east gate.'),
    ])
    message = event(text='crayons tmrw ... read poem 2 on 25 October 2026. bus pickup east gate')
    # An exact relative word is supplied in this fixture for deterministic arithmetic.
    message.text += ' tomorrow'
    await put(app, message, decision)
    facts = app.store.class_facts('5B')
    assert len(facts) == 3 and len({f['source_id'] for f in facts}) == 3
    assert {f['extraction']['kind'] for f in facts} == {'supplies', 'homework', 'school_bus'}
    assert next(f for f in facts if f['extraction']['kind'] == 'homework')['extraction']['due_date'] == '2026-10-25'
    assert all(f['source']['message_id'] == 'one' for f in facts)
    assert await app.ingest(message) == 'duplicate'


async def test_cancel_replaces_exact_record_cancels_pending_reminder_and_preserves_sources(app):
    app.settings.mode = 'live'  # Still fake adapters, only a temporary DB.
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).date().isoformat()
    await put(app, event(text=f'Football practice on {tomorrow}.'), NoticeDecision(records=[
        Extraction(kind='activity', summary='Football practice.', date_as_written=tomorrow, due_date=tomorrow)]))
    old = app.store.class_facts('5B')[0]
    assert app.store.db.execute('SELECT count(*) FROM reminders').fetchone()[0] == 2
    await put(app, event('cancel', text='Cancel that football practice.'), NoticeDecision(records=[
        Extraction(kind='activity', summary='Football practice cancelled.', status='cancelled',
                   replaces_source_ids=[old['source_id']])]))
    facts = app.store.class_facts('5B')
    assert len(facts) == 1 and facts[0]['extraction']['status'] == 'cancelled'
    assert facts[0]['extraction']['due_date'] == tomorrow
    assert facts[0]['source']['previous_sources'][0]['message_id'] == 'one'
    assert {row[0] for row in app.store.db.execute('SELECT status FROM reminders')} == {'cancelled'}
    assert app.store.counts()['facts'] == 2  # Original retained, hidden from current view.
    app.store.close()
    app.store = Store(app.settings.data_dir/'test.sqlite3')
    assert app.store.class_facts('5B')[0]['extraction']['status'] == 'cancelled'


async def test_postponement_reschedules_and_target_ambiguity_makes_no_change(app):
    app.settings.mode = 'live'
    first = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    second = (datetime.now(timezone.utc) + timedelta(days=4)).date().isoformat()
    await put(app, event(text=f'Science test on {first}'), NoticeDecision(records=[
        Extraction(kind='test', summary='Science test.', date_as_written=first, due_date=first)]))
    old = app.store.class_facts('5B')[0]
    await put(app, event('clarify', text='Move the test.'), NoticeDecision(reply='Which date should the test move to?'))
    assert app.store.class_facts('5B')[0]['source_id'] == old['source_id']
    await put(app, event('move', text=f'Postpone the science test to {second}.'), NoticeDecision(records=[
        Extraction(kind='test', summary='Science test postponed.', date_as_written=second, due_date=second,
                   date_changed=True, replaces_source_ids=[old['source_id']])]))
    assert app.store.class_facts('5B')[0]['extraction']['due_date'] == second
    statuses = [row[0] for row in app.store.db.execute('SELECT status FROM reminders')]
    assert statuses.count('cancelled') == 2 and statuses.count('pending') == 2


@pytest.mark.parametrize('record', [
    Extraction(kind='note', summary='Wrong class', class_as_written='6A'),
    Extraction(kind='note', summary='Wrong student', student_id='kabir'),
    Extraction(kind='event', summary='Unknown cancellation', status='cancelled', replaces_source_ids=['other-class-source']),
    Extraction(kind='event', summary='No target cancellation', status='cancelled'),
])
async def test_invalid_change_rejects_entire_batch_before_any_write(app, record):
    await put(app, event(), NoticeDecision(records=[Extraction(kind='note', summary='Valid first part'), record]))
    assert app.store.counts()['facts'] == 0


async def test_student_fact_is_filtered_before_parent_model_context(app):
    await put(app, event(text='Only Aarav must bring his signed form.'), NoticeDecision(records=[
        Extraction(kind='form', summary='Bring the signed form.', student_id='aarav')]))
    parents = app.roster.data['parents']
    assert len(app.store.facts_for(parents[0], app.roster.permitted_students(parents[0]))) == 1
    assert app.store.facts_for(parents[1], app.roster.permitted_students(parents[1])) == []


async def test_split_message_provenance_cannot_leak_other_child_to_parent(app):
    await put(app, event(text='Aarav bring a form. Meera bring PRIVATE_MEERA_MEDICAL_FORM.'), NoticeDecision(records=[
        Extraction(kind='form', summary='Bring a form.', student_id='aarav'),
        Extraction(kind='form', summary='Bring PRIVATE_MEERA_MEDICAL_FORM.', student_id='meera')]))
    teacher_context = app.store.class_facts('5B')
    assert 'PRIVATE_MEERA_MEDICAL_FORM' in json.dumps(teacher_context)
    parent = app.roster.data['parents'][0]
    facts = app.store.facts_for(parent, app.roster.permitted_students(parent))
    assert len(facts) == 1 and 'PRIVATE_MEERA_MEDICAL_FORM' not in json.dumps(facts)
    assert 'text' not in facts[0]['source'] and 'message_id' in facts[0]['source']


async def test_timer_enqueues_once_and_cancelled_fact_is_not_reminded(app):
    app.settings.mode = 'live'
    future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    await put(app, event(text=f'Bring crayons on {future}'), NoticeDecision(records=[
        Extraction(kind='requirement', summary='Bring crayons.', items=['crayons'], date_as_written=future, due_date=future)]))
    with app.store.db:
        app.store.db.execute('UPDATE reminders SET due_at=?', (time.time()-1,))
    assert await app.remind_one()
    assert await app.remind_one()
    assert not await app.remind_one()
    reminders = [r for r in app.store.replies() if r['dedupe_key'].startswith('reminder:')]
    assert len(reminders) == 2 and all('crayons' in r['text'] for r in reminders)


async def test_missing_whatsapp_message_id_is_not_reported_as_confirmed_send(app):
    app.settings.mode = 'live'
    app.store.reply('test-send', 'demo-parent-a', 'Test')
    await app.deliver_one()
    assert app.store.replies()[0]['status'] == 'uncertain'


async def test_partial_cancellation_splits_compound_fact_and_retires_old_reminders(app):
    app.settings.mode = 'live'
    future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    await put(app, event(text=f'Bring crayons and a drawing book on {future}.'), NoticeDecision(records=[
        Extraction(kind='supplies', summary='Bring crayons and a drawing book.',
                   items=['crayons', 'drawing book'], date_as_written=future, due_date=future)]))
    old = app.store.class_facts('5B')[0]
    assert app.store.db.execute('SELECT count(*) FROM reminders WHERE source_id=?', (old['source_id'],)).fetchone()[0] == 2
    # An old reminder may have reached the outbox but not the transport yet.
    app.store.reply('reminder:' + old['source_id'] + ':parent-a', 'demo-parent-a', 'Old compound reminder')
    await put(app, event('partial-cancel', text='No crayons needed; still bring the drawing book.'), NoticeDecision(records=[
        Extraction(kind='supplies', summary='Crayons are cancelled.', items=['crayons'],
                   status='cancelled', replaces_source_ids=[old['source_id']]),
        Extraction(kind='supplies', summary='Still bring the drawing book.', items=['drawing book'],
                   replaces_source_ids=[old['source_id']]),
    ]))

    current = app.store.class_facts('5B')
    assert len(current) == 2
    by_item = {fact['extraction']['items'][0]: fact for fact in current}
    assert by_item['crayons']['extraction']['status'] == 'cancelled'
    assert by_item['drawing book']['extraction']['status'] == 'active'
    assert all(fact['extraction']['due_date'] == future for fact in current)
    assert all(fact['source']['previous_sources'][0]['message_id'] == 'one' for fact in current)
    links = {tuple(row) for row in app.store.db.execute('SELECT old_source_id,new_source_id FROM fact_replacements')}
    assert links == {(old['source_id'], fact['source_id']) for fact in current}
    assert app.store.counts()['facts'] == 3  # Historical compound record remains.
    assert {row[0] for row in app.store.db.execute('SELECT status FROM reminders WHERE source_id=?', (old['source_id'],))} == {'cancelled'}
    assert app.store.db.execute('SELECT count(*) FROM reminders WHERE source_id=?', (by_item['crayons']['source_id'],)).fetchone()[0] == 0
    assert app.store.db.execute("SELECT count(*) FROM reminders WHERE source_id=? AND status='pending'", (by_item['drawing book']['source_id'],)).fetchone()[0] == 2
    assert next(row for row in app.store.replies() if row['dedupe_key'].startswith('reminder:'))['status'] == 'cancelled'
    assert not any(message['text'] == 'Old compound reminder' for message in app.transport.sent)
    for parent in app.roster.data['parents']:
        visible = app.store.facts_for(parent, app.roster.permitted_students(parent))
        assert old['source_id'] not in {fact['source_id'] for fact in visible}


@pytest.mark.parametrize('date_changed', [False, True])
async def test_correction_preserves_old_relative_date_unless_explicitly_changed(app, date_changed):
    original = event(text='Bring crayons tomorrow.').model_copy(update={
        'timestamp': datetime(2030, 1, 10, 10, tzinfo=timezone.utc),
    })
    await put(app, original, NoticeDecision(records=[
        Extraction(kind='supplies', summary='Bring crayons.', items=['crayons'], date_as_written='tomorrow')]))
    old = app.store.class_facts('5B')[0]
    assert old['extraction']['due_date'] == '2030-01-11'

    text = 'Bring pencils instead of crayons. Read poem 2 tomorrow.'
    if date_changed:
        text += ' Move the corrected supplies requirement to tomorrow too.'
    corrected = event('next-day-correction', text=text).model_copy(update={
        'timestamp': datetime(2030, 1, 11, 10, tzinfo=timezone.utc),
    })
    await put(app, corrected, NoticeDecision(records=[
        # This old relative wording and model-calculated date must not shift the
        # original requirement merely because another clause says tomorrow.
        Extraction(kind='supplies', summary='Bring pencils instead.', items=['pencils'],
                   date_as_written='tomorrow', due_date='2030-01-12', date_changed=date_changed,
                   replaces_source_ids=[old['source_id']]),
        Extraction(kind='homework', summary='Read poem 2.', date_as_written='tomorrow'),
    ]))
    records = {fact['extraction']['kind']: fact['extraction'] for fact in app.store.class_facts('5B')}
    assert records['supplies']['due_date'] == ('2030-01-12' if date_changed else '2030-01-11')
    assert records['homework']['due_date'] == '2030-01-12'


@pytest.mark.parametrize('crash_point', ['after_save', 'after_delivery'])
async def test_applied_decision_recovery_does_not_reinvoke_model_or_send_twice(app, monkeypatch, crash_point):
    class SimulatedProcessStop(BaseException):
        pass

    app.settings.mode = 'live'

    async def fake_confirmed_send(chat_id, text, reply_to=None):
        app.transport.sent.append({'chat_id': chat_id, 'text': text})
        return f'fixture-message-{len(app.transport.sent)}'

    monkeypatch.setattr(app.transport, 'send_text', fake_confirmed_send)
    future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    await put(app, event(text=f'Bring crayons on {future}.'), NoticeDecision(records=[
        Extraction(kind='supplies', summary='Bring crayons.', items=['crayons'], date_as_written=future)]))
    old = app.store.class_facts('5B')[0]
    correction = event('crash-correction', text='Bring pencils instead of crayons, on the same date.')
    app.ai.decision = NoticeDecision(records=[
        Extraction(kind='supplies', summary='Bring pencils instead.', items=['pencils'],
                   replaces_source_ids=[old['source_id']])])
    assert await app.ingest(correction) == 'queued'
    row = app.store.next_message()

    with monkeypatch.context() as crash:
        if crash_point == 'after_save':
            original_save = app.store.save_decision

            def save_then_stop(*args, **kwargs):
                original_save(*args, **kwargs)
                raise SimulatedProcessStop()

            crash.setattr(app.store, 'save_decision', save_then_stop)
        else:
            original_understand = app._understand

            async def understand_deliver_then_stop(*args, **kwargs):
                await original_understand(*args, **kwargs)
                assert await app.deliver_one()
                raise SimulatedProcessStop()

            crash.setattr(app, '_understand', understand_deliver_then_stop)
        with pytest.raises(SimulatedProcessStop):
            await app.process(row)

    assert app.store.message(correction.source_key)['status'] == 'processing'
    marker = NoticeDecision.model_validate_json(app.store.applied_decision(correction.source_key))
    assert marker.records[0].due_date == future
    assert len(app.ai.calls) == 2
    assert app.store.counts()['facts'] == 2
    new_id = app.store.class_facts('5B')[0]['source_id']

    # If recovery incorrectly calls the model again, this would try to replace
    # the just-created record with itself. The persisted marker must bypass it.
    app.ai.decision = NoticeDecision(records=[
        Extraction(kind='supplies', summary='Unexpected second interpretation.', items=['eraser'],
                   replaces_source_ids=[new_id])])
    app.store.close()
    app.store = Store(app.settings.data_dir / 'test.sqlite3')
    assert app.store.message(correction.source_key)['status'] == 'pending'
    await drain(app)

    assert app.store.message(correction.source_key)['status'] == 'done'
    assert len(app.ai.calls) == 2
    facts = app.store.class_facts('5B')
    assert len(facts) == 1 and facts[0]['extraction']['items'] == ['pencils']
    assert app.store.counts()['facts'] == 2
    assert app.store.db.execute('SELECT count(*) FROM applied_decisions').fetchone()[0] == 2
    assert [tuple(r) for r in app.store.db.execute('SELECT old_source_id,new_source_id FROM fact_replacements')] == [(old['source_id'], new_id)]
    assert len([r for r in app.store.replies() if r['dedupe_key'] == new_id + ':answer']) == 1
    assert sum('Bring pencils instead.' in message['text'] for message in app.transport.sent) == 1
    assert app.store.db.execute("SELECT count(*) FROM reminders WHERE source_id=? AND status='pending'", (new_id,)).fetchone()[0] == 2
    assert {r[0] for r in app.store.db.execute('SELECT status FROM reminders WHERE source_id=?', (old['source_id'],))} == {'cancelled'}


async def test_self_target_is_rejected_before_a_record_can_hide_itself(app):
    message = event(text='Bring crayons tomorrow.')
    await put(app, message, NoticeDecision(records=[
        Extraction(kind='supplies', summary='Bring crayons.', items=['crayons'], date_as_written='tomorrow')]))
    current = app.store.class_facts('5B')
    sid = current[0]['source_id']
    invalid = NoticeDecision(records=[
        Extraction(kind='supplies', summary='Cancel crayons.', status='cancelled',
                   replaces_source_ids=[sid])])
    with pytest.raises(ValueError, match='unique saved notice'):
        await app._apply_decision(sid, message, app.roster.resolve(message), invalid, current, message.text)
    assert app.store.class_facts('5B')[0]['source_id'] == sid
    assert app.store.db.execute('SELECT count(*) FROM fact_replacements').fetchone()[0] == 0
    assert app.store.counts()['facts'] == 1


async def test_postponement_omission_preserves_saved_syllabus_fields(app):
    from octo.contracts import StudySection
    await put(app,event(text='Science test on 2026-10-20. Chapter 6 roots pages 42-47.'),NoticeDecision(records=[
        Extraction(kind='test',subject='Science',summary='Science test',due_date='2026-10-20',date_as_written='2026-10-20',
                   sections=[StudySection(chapter='Chapter 6',topics=['roots'],pages='42-47')])]))
    old=app.store.class_facts('5B')[0]['source_id']
    await put(app,event('new-date',text='Science test postponed from 2026-10-20 to 2026-10-21.'),NoticeDecision(records=[
        Extraction(kind='test',summary='Science test postponed',due_date='2026-10-21',date_as_written='2026-10-21',date_changed=True,replaces_source_ids=[old])]))
    current=app.store.class_facts('5B')[0]['extraction']
    assert current['due_date']=='2026-10-21'
    assert current['subject']=='Science' and current['sections'][0]['topics']==['roots']


async def test_merged_explicit_dates_cannot_silently_drop_one_notice(app):
    await put(app,event(text='Crayons on 2026-10-20; poem 2 on 2026-10-21.'),NoticeDecision(records=[
        Extraction(kind='notice',summary='Bring crayons and read poem 2',items=['crayons'],due_date='2026-10-20',date_as_written='2026-10-20')]))
    assert not app.store.class_facts('5B')
    assert 'different dates' in app.store.replies()[0]['text']


async def test_conflicting_old_and_new_date_proposal_cannot_move_wrong_reminder(app):
    await put(app,event(text='Science test on 2026-10-20.'),NoticeDecision(records=[
        Extraction(kind='test',summary='Science test',due_date='2026-10-20',date_as_written='2026-10-20')]))
    old=app.store.class_facts('5B')[0]['source_id']
    await put(app,event('inconsistent-date',text='Move Science test from 2026-10-20 to 2026-10-21.'),NoticeDecision(records=[
        Extraction(kind='test',summary='Science test postponed',due_date='2026-10-21',date_as_written='2026-10-20',date_changed=True,replaces_source_ids=[old])]))
    assert app.store.class_facts('5B')[0]['source_id']==old
    assert 'new date is inconsistent' in app.store.replies()[-1]['text']


async def test_split_replacement_cannot_inherit_cancelled_items_back_into_active_part(app):
    await put(app,event(text='Bring crayons and drawing book on 2026-10-20.'),NoticeDecision(records=[
        Extraction(kind='requirement',summary='Bring supplies',items=['crayons','drawing book'],due_date='2026-10-20',date_as_written='2026-10-20')]))
    old=app.store.class_facts('5B')[0]['source_id']
    await put(app,event('split-omission',text='Drawing book is no longer needed; still bring crayons.'),NoticeDecision(records=[
        Extraction(kind='requirement',summary='Drawing book no longer needed',status='cancelled',items=['drawing book'],replaces_source_ids=[old]),
        Extraction(kind='requirement',summary='Bring crayons',replaces_source_ids=[old])]))
    assert app.store.class_facts('5B')[0]['source_id']==old
    assert 'cancelled and remaining' in app.store.replies()[-1]['text']
