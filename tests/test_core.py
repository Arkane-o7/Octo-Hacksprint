"""Application invariants with synthetic adapters; no live accuracy assertions."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from octo.config import Settings
from octo.contracts import Extraction, GroundedAnswer, IncomingMessage, Media
from octo.core import Octo, Roster
from octo.offline import OfflineAI, OfflineTransport
from octo.replay import drain
from octo.sarvam import AudioTooLongError, SarvamError
from octo.storage import Store


STAMP = datetime(2026, 10, 17, 20, tzinfo=timezone.utc)  # Oct 18 in India.


def notice(identifier='T1', **changes):
    values = dict(session='default', message_id=identifier, chat_id='demo-class-5b@g.us',
                  sender_id='demo-teacher', timestamp=STAMP, is_group=True,
                  text='Bring crayons and a drawing book tomorrow.')
    values.update(changes)
    return IncomingMessage(**values)


def question(identifier='P1', **changes):
    values = dict(session='default', message_id=identifier, chat_id='demo-parent-a',
                  sender_id='demo-parent-a', timestamp=STAMP, text='What does Aarav need tomorrow?')
    values.update(changes)
    return IncomingMessage(**values)


class SpyAI(OfflineAI):
    def __init__(self):
        self.answer_calls = []
        self.tts_fails = False
        self.audio_long = False
        self.submissions = 0
        self.job_status = 'completed'
        self.answer_override = None

    async def answer(self, question, facts, student_names, language):
        self.answer_calls.append((facts, student_names))
        return self.answer_override or await super().answer(question, facts, student_names, language)

    async def submit_document(self, path):
        assert path.suffix == '.jpg'
        self.submissions += 1
        return await super().submit_document(path)

    async def document_status(self, job_id):
        return self.job_status

    async def transcribe(self, path, keyterms):
        assert path.suffix == '.ogg'
        if self.audio_long:
            raise AudioTooLongError('Please send a voice note shorter than 30 seconds.')
        return await super().transcribe(path, keyterms)

    async def synthesize(self, text, language, destination):
        if self.tts_fails:
            raise SarvamError('Speech service unavailable')
        destination.write_bytes(b'SYNTHETIC AUDIO BYTES - NOT PLAYABLE')
        return destination


@pytest.fixture
def octo(tmp_path):
    settings = Settings(data_dir=tmp_path, poll_seconds=0)
    obj = Octo(settings, Store(tmp_path / 'test.sqlite3'), Roster(Path('roster.example.json')), SpyAI(), OfflineTransport())
    yield obj
    obj.store.close()


async def put(octo, event):
    assert await octo.ingest(event) == 'queued'
    await drain(octo)


def output(octo):
    return '\n'.join(r['text'] for r in octo.store.replies())


async def test_requirement_date_source_dedup_and_restart(octo):
    event = notice()
    await put(octo, event)
    assert await octo.ingest(event) == 'duplicate'
    row = octo.store.db.execute('SELECT * FROM facts').fetchone()
    assert json.loads(row['extraction'])['due_date'] == '2026-10-19'
    assert json.loads(row['provenance'])['message_id'] == 'T1'
    await put(octo, question())
    assert 'crayons' in output(octo) and 'Sources:' in output(octo)
    other_connection = Store(octo.settings.data_dir / 'test.sqlite3')
    assert other_connection.counts()['facts'] == 1
    assert not other_connection.enqueue(event, octo.roster.resolve(event))
    other_connection.close()


async def test_school_day_survives_restart_is_date_bound_and_available_to_parent(octo):
    async def extract(text, timestamp, class_label):
        return Extraction(kind='school_day', school_day_status='no_classes',
                          date_as_written='tomorrow', due_date='2099-01-01')

    octo.ai.extract_notice = extract
    event = notice('HOLIDAY', text='Tomorrow is a holiday, no classes tomorrow')
    await put(octo, event)
    assert await octo.ingest(event) == 'duplicate'
    assert octo.store.counts()['facts'] == 1
    saved = octo.store.db.execute('SELECT * FROM facts').fetchone()
    record = json.loads(saved['extraction'])
    assert record['kind'] == 'school_day'
    assert record['school_day_status'] == 'no_classes'
    assert record['due_date'] == '2026-10-19'  # Message timestamp is Oct 18 IST.
    assert record['items'] == [] and record['sections'] == []
    assert json.loads(saved['provenance'])['text'] == event.text
    assert 'No classes.' in output(octo) and '2026-10-19' in output(octo)
    source_id = saved['source_id']
    octo.store.close()
    octo.store = Store(octo.settings.data_dir / 'test.sqlite3')
    octo.ai.answer_override = GroundedAnswer(language_code='en-IN', text='No classes tomorrow.', source_ids=[source_id])
    await put(octo, question(text='Does Aarav have class tomorrow?'))
    facts, names = octo.ai.answer_calls[-1]
    assert names == ['Aarav']
    assert facts[0]['extraction']['school_day_status'] == 'no_classes'
    assert source_id in output(octo) and 'Sources:' in output(octo)


@pytest.mark.parametrize('changes', [
    {'date_as_written': None, 'due_date': '2026-10-19'},
    {'date_as_written': 'sometime', 'due_date': None},
    {'subject': 'Science'},
    {'unclear': ['The notice says maybe.']},
    {'school_day_status': None},
    {'items': ['crayons']},
])
async def test_ambiguous_or_lesson_specific_closure_does_not_change_class_day(octo, changes):
    record = Extraction(kind='school_day', school_day_status='no_classes',
                        date_as_written='tomorrow', due_date='2026-10-19')
    record = record.model_copy(update=changes)

    async def extract(*args):
        return record

    octo.ai.extract_notice = extract
    await put(octo, notice(text='Unclear class notice'))
    assert octo.store.counts()['facts'] == 0
    assert 'have not changed' in output(octo)


async def test_class_day_updates_preserve_existing_requirements_and_sources(octo):
    await put(octo, notice())

    async def extract(text, timestamp, class_label):
        return Extraction(kind='school_day', school_day_status='no_classes' if 'holiday' in text else 'classes_scheduled',
                          date_as_written='tomorrow')

    octo.ai.extract_notice = extract
    await put(octo, notice('CLOSE', text='Tomorrow is a holiday.'))
    await put(octo, notice('OPEN', text='Classes as usual tomorrow.'))
    records = [json.loads(r[0]) for r in octo.store.db.execute('SELECT extraction FROM facts ORDER BY created')]
    assert len(records) == 3
    assert records[0]['items'] == ['crayons', 'a drawing book']
    assert records[1]['school_day_status'] == 'no_classes'
    assert records[2]['school_day_status'] == 'classes_scheduled'
    assert 'Classes as usual.' in output(octo)


@pytest.mark.parametrize('changes', [
    {'sender_id': 'stranger'}, {'session': 'personal'},
    {'chat_id': 'personal-group@g.us'},
])
async def test_unallowlisted_source_never_enters_storage(octo, changes):
    assert await octo.ingest(notice(**changes)) == 'ignored'
    assert octo.store.counts()['inbox'] == 0


async def test_teacher_dm_and_conflicting_sender_alias_are_ignored(octo):
    assert await octo.ingest(notice(chat_id='demo-teacher', is_group=False)) == 'ignored'
    assert await octo.ingest(question(sender_aliases=['demo-parent-b'])) == 'ignored'


async def test_shared_class_facts_but_private_student_records_are_scoped(octo):
    await put(octo, notice())
    source = {'sender': 'Private fixture', 'timestamp': STAMP.isoformat()}
    private = Extraction(kind='requirement', items=['PRIVATE MEERA ITEM']).model_dump_json()
    with octo.store.db:
        octo.store.db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?)',
                             ('private-b', '5B', 'parent-b', 'meera', private, json.dumps(source), 1))
        octo.store.db.execute('INSERT INTO facts VALUES(?,?,?,?,?,?,?)',
                             ('class-6', '6A', None, None, Extraction(kind='requirement', items=['CLASS SIX ITEM']).model_dump_json(), json.dumps(source), 2))
    await put(octo, question())
    facts, names = octo.ai.answer_calls[-1]
    assert names == ['Aarav']
    assert {f['source_id'] for f in facts}.isdisjoint({'private-b', 'class-6'})
    await put(octo, question('P2', sender_id='demo-parent-b', chat_id='demo-parent-b', text='What does Meera need?'))
    facts, names = octo.ai.answer_calls[-1]
    assert names == ['Meera']
    assert 'private-b' in {f['source_id'] for f in facts}
    assert 'class-6' not in {f['source_id'] for f in facts}
    assert any('crayons' in str(f) for f in facts)
    group = '\n'.join(r['text'] for r in octo.store.replies() if r['chat_id'].endswith('@g.us'))
    assert 'PRIVATE' not in group


async def test_unauthorized_student_and_ambiguous_family_question_do_not_call_model(octo):
    await put(octo, notice())
    await put(octo, question(text='What does Meera need?'))
    await put(octo, question('P2', sender_id='demo-parent-b', chat_id='demo-parent-b', text='What does my child need?'))
    assert not octo.ai.answer_calls
    assert 'linked to your' in output(octo) and 'Which student' in output(octo)


async def test_photo_is_copied_before_model_work_and_retains_suffix_caption(octo):
    event = notice('IMG', kind='image', text='Science syllabus', media=Media(url='fixture://board-clear', mime_type='image/jpeg'))
    await octo.ingest(event)
    row = octo.store.message(event.source_key)
    saved = IncomingMessage.model_validate_json(row['event'])
    assert Path(saved.media.local_path).suffix == '.jpg'
    assert Path(saved.media.local_path).is_file()
    assert octo.ai.submissions == 0
    await drain(octo)
    assert 'Parts of a plant' in output(octo)
    provenance = json.loads(octo.store.db.execute('SELECT provenance FROM facts').fetchone()[0])
    assert provenance['text'] == 'Science syllabus'
    assert provenance['media_path'] == saved.media.local_path


async def test_unclear_syllabus_leaves_date_and_pages_unset(octo):
    await put(octo, notice('IMG', kind='image', media=Media(url='fixture://board-unclear', mime_type='image/jpeg')))
    record = json.loads(octo.store.db.execute('SELECT extraction FROM facts').fetchone()[0])
    assert record['due_date'] is None and record['sections'][0]['pages'] is None
    assert record['unclear'] and 'Please clarify:' in output(octo)


async def test_explicit_full_syllabus_date_is_resolved_when_model_leaves_it_null(octo):
    from octo.contracts import StudySection
    event = notice('DATE', text='Science test: 18 October 2026. Chapter 6: Roots.')
    caller = octo.roster.resolve(event)
    record = Extraction(kind='syllabus', date_as_written='18 October 2026',
                        sections=[StudySection(chapter='Chapter 6', topics=['Roots'])])
    await octo._save_extraction('date-source', event, caller, record)
    saved = json.loads(octo.store.db.execute('SELECT extraction FROM facts').fetchone()[0])
    assert saved['due_date'] == '2026-10-18'


async def test_pending_ocr_job_resumes_without_submitting_again(octo):
    octo.ai.job_status = 'running'
    event = notice('IMG', kind='image', media=Media(url='fixture://board-clear', mime_type='image/jpeg'))
    await octo.ingest(event)
    await octo.tick()
    assert octo.store.message(event.source_key)['job_id'] == 'fixture-clear'
    octo.store.close()
    octo.store = Store(octo.settings.data_dir / 'test.sqlite3')
    octo.ai.job_status = 'completed'
    await drain(octo)
    assert octo.ai.submissions == 1 and octo.store.counts()['facts'] == 1


async def test_overlong_voice_has_actionable_reply(octo):
    octo.ai.audio_long = True
    await put(octo, question(kind='voice', media=Media(url='fixture://parent-hindi', mime_type='audio/ogg; codecs=opus')))
    assert 'shorter than 30 seconds' in output(octo)


async def test_text_survives_tts_failure_and_cannot_claim_audio_sent(octo):
    await put(octo, notice())
    octo.settings.mode = 'live'  # Still injected synthetic adapters; no network.
    octo.ai.tts_fails = True
    await put(octo, question(kind='voice', media=Media(url='fixture://parent-hindi', mime_type='audio/ogg')))
    parent_replies = [r for r in octo.store.replies() if r['chat_id'] == 'demo-parent-a']
    assert 'crayons' in parent_replies[0]['text']
    assert 'audio is unavailable' in parent_replies[1]['text']
    assert all(r['kind'] == 'text' for r in parent_replies)


async def test_spoken_answer_does_not_silently_cut_later_exclusion(octo):
    await put(octo, notice())
    source_id = octo.store.db.execute('SELECT source_id FROM facts').fetchone()[0]
    spoken = 'Read these topics. ' * 45 + 'Do not study the appendix.'
    octo.ai.answer_override = GroundedAnswer(language_code='en-IN', text=spoken, spoken_text=spoken, source_ids=[source_id])
    octo.settings.mode = 'live'
    captured = []

    async def speak(text, language, destination):
        captured.append(text)
        raise SarvamError('Intentionally skip playback in this synthetic test')

    octo.ai.synthesize = speak
    await put(octo, question())
    assert captured == [spoken]


async def test_unknown_source_ids_cannot_be_sent_as_grounded(octo):
    await put(octo, notice())
    octo.ai.answer_override = GroundedAnswer(language_code='en-IN', text='Unsupported fact', source_ids=['made-up'])
    await put(octo, question())
    assert 'Unsupported fact' not in output(octo)
    assert 'could not verify' in output(octo)


async def test_each_question_routes_selected_language_to_tts_without_changing_preference(octo):
    await put(octo, notice())
    sid = octo.store.db.execute('SELECT source_id FROM facts').fetchone()[0]
    preference = octo.roster.resolve(question())['language']
    octo.settings.mode = 'live'  # Synthetic adapters only, no network.
    spoken = []

    async def speak(text, language, destination):
        spoken.append((text, language))
        destination.write_bytes(b'SYNTHETIC AUDIO - NOT PLAYABLE')
        return destination

    octo.ai.synthesize = speak
    cases = [('What should I bring?', 'en-IN', 'Bring crayons.'),
             ('कल क्या लाना है?', 'hi-IN', 'क्रेयॉन लाएँ।'),
             ('நாளை என்ன கொண்டு வர வேண்டும்?', 'ta-IN', 'வண்ணக்கோல்கள் கொண்டு வரவும்.'),
             ('What should I bring? Reply in Telugu.', 'te-IN', 'క్రేయాన్లు తీసుకురండి.')]
    for index, (text, language, reply) in enumerate(cases):
        octo.ai.answer_override = GroundedAnswer(language_code=language, text=reply,
            spoken_text=reply, source_ids=[sid])
        await put(octo, question('LANG-' + str(index), text=text))
        assert spoken[-1] == (reply, language)
        assert octo.roster.resolve(question())['language'] == preference
        assert any(r['text'].startswith(reply + '\n\nSources:\n') for r in octo.store.replies())


async def test_voice_language_uses_transcribed_question_and_selected_answer_language(octo):
    from octo.contracts import Transcript
    await put(octo, notice())
    sid = octo.store.db.execute('SELECT source_id FROM facts').fetchone()[0]
    octo.settings.mode = 'live'
    transcript = 'நாளை என்ன கொண்டு வர வேண்டும்?'
    spoken = []

    async def transcribe(path, names):
        return Transcript(text=transcript, language_code='ta-IN')

    async def answer(text, facts, names, fallback):
        assert transcript in text and 'ignored caption' not in text
        return GroundedAnswer(language_code='ta-IN', text='வண்ணக்கோல்கள் கொண்டு வரவும்.', source_ids=[sid])

    async def speak(text, language, destination):
        spoken.append(language)
        destination.write_bytes(b'SYNTHETIC AUDIO - NOT PLAYABLE')
        return destination

    octo.ai.transcribe, octo.ai.answer, octo.ai.synthesize = transcribe, answer, speak
    await put(octo, question('VOICE-LANG', kind='voice', text='ignored caption',
        media=Media(url='fixture://parent-tamil', mime_type='audio/ogg')))
    assert spoken == ['ta-IN']


async def test_forward_and_individual_notices_do_not_become_class_facts(octo):
    await put(octo, notice(forwarded=True))
    await put(octo, notice('T2', text='Only Aarav must bring crayons and a drawing book tomorrow.'))
    assert octo.store.counts()['facts'] == 0


async def test_unknown_purchase_code_does_not_invoke_model_or_approval(octo):
    await put(octo, question(text='APPROVE ABC123'))
    assert 'SIMULATED' in output(octo) and 'no purchase made' in output(octo)
    assert not octo.ai.answer_calls


async def test_ambiguous_delivery_not_retried_on_restart(octo):
    async def fail_send(*args, **kwargs):
        raise TimeoutError('May have sent')
    octo.transport.send_text = fail_send
    await put(octo, notice())
    assert octo.store.replies()[0]['status'] == 'uncertain'
    octo.store.close()
    octo.store = Store(octo.settings.data_dir / 'test.sqlite3')
    assert not await octo.deliver_one()
