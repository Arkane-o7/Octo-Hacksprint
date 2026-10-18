"""Offline UX acceptance; no network or handset claims."""
import re

import pytest

from octo.contracts import Extraction, Media, StudySection, Transcript
from octo.i18n import COPY, cart_chrome, language, message
from octo.presentation import saved_notice
from octo.storage import Store
from octo.welcome import intent
from test_core import octo, put, question, notice, output


async def test_help_no_facts_repeated_greeting_and_restart(octo):
    await put(octo, question(text='Hi'))
    first = output(octo)
    assert 'Linked children: Aarav' in first
    assert 'Tomorrow · Next test · Find notes' in first
    assert 'Sources' not in first and not octo.ai.answer_calls
    await put(octo, question('P2', text='help'))
    assert output(octo).count('Hi! I’m Octo') == 2
    octo.store.close()
    octo.store = Store(octo.settings.data_dir / 'test.sqlite3')
    await put(octo, question('P3'))
    assert output(octo).count('Hi! I’m Octo') == 2
    assert 'do not have saved' in output(octo)


async def test_first_substantive_answer_is_first_and_welcome_only_once(octo):
    await put(octo, notice())
    await put(octo, question())
    text = next(r['text'] for r in octo.store.replies() if r['chat_id'] == 'demo-parent-a' and 'crayons' in r['text'])
    assert text.index('crayons') < text.index('Hi! I’m Octo')
    await put(octo, question('P2'))
    assert output(octo).count('Hi! I’m Octo') == 1


async def test_outsider_and_group_greeting_are_silent(octo):
    assert await octo.ingest(question(sender_id='outsider', chat_id='outsider', text='Hi')) == 'ignored'
    await put(octo, question(text='Hi', is_group=True, chat_id='demo-class-5b@g.us'))
    assert not octo.store.replies()
    await put(octo, question('P2', text='help', is_group=True, chat_id='demo-class-5b@g.us'))
    assert 'Try: Tomorrow' in output(octo) and 'Aarav' not in output(octo)


async def test_unlinked_verified_member_has_only_class_context(octo):
    octo.roster.set_group_members('demo-class-5b@g.us', [['123456@c.us']])
    await put(octo, question(sender_id='123456@c.us', chat_id='123456@c.us', text='Hi'))
    assert 'Class-wide notices: 5B' in output(octo)
    assert 'Aarav' not in output(octo) and 'Linked children' not in output(octo)


@pytest.mark.parametrize('text, expected', [('Tomorrow', 'scheduled or needed tomorrow'), ('Next test', 'next test explicitly mentioned'), ('Find notes', 'available document link')])
async def test_shortcuts_use_existing_scoped_answer(octo, text, expected):
    await put(octo, notice())
    original = octo.ai.answer
    questions = []
    async def answer(question_text, facts, names, lang):
        questions.append(question_text)
        assert all(f['class_id'] == '5B' for f in facts)
        assert names == ['Aarav']
        return await original(question_text, facts, names, lang)
    octo.ai.answer = answer
    await put(octo, question(text=text))
    assert expected in questions[0]
    assert octo.store.db.execute('SELECT count(*) FROM facts').fetchone()[0] == 1


@pytest.mark.parametrize('text, expected', [('Hi', 'Hi!'), ('नमस्ते', 'नमस्ते!'), ('வணக்கம்', 'வணக்கம்!')])
async def test_typed_greeting_follows_language(octo, text, expected):
    await put(octo, question(text=text))
    assert expected in output(octo)


@pytest.mark.parametrize('text, expected', [('What is due?', 'do not have saved'), ('कल क्या चाहिए?', 'अभी सहेजी नहीं'), ('நாளை என்ன வேண்டும்?', 'இன்னும் சேமிக்கப்படவில்லை')])
async def test_no_data_follows_current_text(octo, text, expected):
    await put(octo, question(text=text))
    assert expected in output(octo)


async def test_voice_stt_language_and_unheard_roster_fallback(octo):
    async def transcribe(*args):
        return Transcript(text='What is due?', language_code='ta-IN')
    octo.ai.transcribe = transcribe
    await put(octo, question(kind='voice', media=Media(url='fixture://parent-hindi', mime_type='audio/ogg')))
    assert 'இன்னும் சேமிக்கப்படவில்லை' in output(octo)
    async def unheard(*args):
        return Transcript(text='', language_code='ta-IN')
    octo.ai.transcribe = unheard
    await put(octo, question('P2', kind='voice', media=Media(url='fixture://parent-hindi', mime_type='audio/ogg')))
    assert 'आवाज़ साफ़ सुनाई नहीं दी' in output(octo)  # roster, not unknown audio


async def test_notes_clarifies_multiple_subjects(octo):
    async def extract(text, *args):
        return Extraction(kind='notes', subject=text, sections=[StudySection(topics=['Topic as written'])])
    octo.ai.extract_notice = extract
    await put(octo, notice(text='Science'))
    await put(octo, notice('T2', text='Math'))
    await put(octo, question(text='Find notes'))
    assert 'Which subject? Math, Science' in output(octo)
    assert not octo.ai.answer_calls


def test_catalog_complete_and_source_text_preserved():
    assert all(set(v) == {'en', 'hi', 'ta'} and all(v.values()) for v in COPY.values())
    record = Extraction(kind='syllabus', summary='Do NOT study Chapter 3.', sections=[StudySection(chapter='2', topics=['Only till heading 2'])], unclear=['Date not confirmed'])
    for lang, label in [('hi-IN', 'पढ़ाई की सूची'), ('ta-IN', 'படிப்புப் பட்டியல்')]:
        rendered = saved_notice(record, '5B', {'sender': 'Teacher'}, language=lang)
        assert label in rendered and 'Do NOT study Chapter 3.' in rendered
        assert 'Only till heading 2' in rendered and 'Date not confirmed' in rendered
    assert language('English typed question', 'hi-IN') == 'en-IN'
    assert language('', 'te-IN') == 'te-IN'
    assert intent('Hi, what is due tomorrow?') is None


def test_cart_commands_and_warning_meaning_preserved():
    original = 'SIMULATED — no purchase made.\nAPPROVE ABCDEF1234\nCANCEL ABCDEF1234\nCHANGE ABCDEF1234 crayons, drawing book\nFixed demo prices; no merchant connection.'
    for lang in ['hi-IN', 'ta-IN']:
        translated = cart_chrome(original, lang)
        assert re.findall(r'^(?:APPROVE|CANCEL|CHANGE).*$', translated, re.M) == re.findall(r'^(?:APPROVE|CANCEL|CHANGE).*$', original, re.M)
        assert message('SIMULATED — no purchase made.', lang) in translated


@pytest.mark.parametrize('text, expected', [('रिया के बारे में बताओ', 'केवल आपके खाते'), ('Riya பற்றி சொல்', 'இணைக்கப்பட்ட குழந்தைகளை')])
async def test_permission_copy_is_localized_without_other_child_facts(octo, text, expected):
    # Use the actual other fixture student's name, keeping the language signal.
    other = next(s for s in octo.roster.students.values() if s['id'] not in octo.roster.resolve(question())['student_ids'])
    text = other['name'] + ' ' + text
    await put(octo, question(text=text))
    assert expected in output(octo)
    assert not octo.ai.answer_calls


@pytest.mark.parametrize('text, expected', [('यह सूचना है', 'सूचना सहेजी नहीं गई'), ('இது அறிவிப்பு', 'அறிவிப்பு சேமிக்கப்படவில்லை')])
async def test_unsupported_teacher_notice_is_not_saved(octo, text, expected):
    async def extract(*args):
        return Extraction(kind='unknown')
    octo.ai.extract_notice = extract
    await put(octo, notice(text=text))
    assert expected in output(octo)
    assert octo.store.counts()['facts'] == 0


async def test_welcome_delivery_rechecks_membership(octo):
    event = question(text='Hi')
    assert await octo.ingest(event) == 'queued'
    await octo.process(octo.store.next_message())
    octo.roster.set_group_members('demo-class-5b@g.us', [])
    await octo.deliver_one()
    assert octo.store.replies()[0]['status'] == 'cancelled'


async def test_shortcut_expansion_cannot_authorize_cart(octo):
    from octo.contracts import GroundedAnswer
    await put(octo, notice())
    async def answer(question_text, facts, *args):
        return GroundedAnswer(text='Saved information.', language_code='en-IN',
                              source_ids=[facts[0]['source_id']], proposed_items=['crayons'],
                              cart_request_quote='scheduled or needed tomorrow')
    octo.ai.answer = answer
    await put(octo, question(text='Tomorrow'))
    assert not any(':cart' in r['dedupe_key'] for r in octo.store.replies())
