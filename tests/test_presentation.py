from octo.contracts import Extraction, StudySection
from octo.presentation import saved_notice, answer_text

SOURCE = {'sender': 'Ms. Rao', 'timestamp': '2026-10-17T17:44:07+00:00'}
FACT = {'source_id': 'opaque-secret-source', 'source': {**SOURCE,
        'calendar': {'status': 'synced', 'url': 'https://www.google.com/calendar/event?eid=fixture'},
        'document': {'url': 'https://drive.google.com/file/d/fixture/view'}},
        'extraction': {'subject': 'Science', 'due_date': '2026-10-20'}}


def test_unknown_photo_date_and_coverage_boundary_remain_visible():
    record = Extraction(kind='syllabus', date_as_written='25th October',
                        sections=[StudySection(chapter='Chapter 4', topics=['Future in AI (till heading 2)'])])
    text = saved_notice(record, '5B', SOURCE)
    assert '25th October' in text and '*Please confirm*' in text
    assert 'including the year' in text
    assert 'till heading 2' in text
    assert 'Date to confirm' in text
    assert record.due_date is None and not record.unclear  # Presentation never mutates facts.


def test_default_answer_removes_link_dump_but_keeps_reference():
    text = answer_text('Study roots. [opaque-secret-source]\nhttps://untrusted.example/', [FACT], 'en-IN')
    assert 'http' not in text and 'opaque-secret-source' not in text
    assert 'Ms. Rao · 17 Oct 2026 · 11:14 pm IST' in text
    assert '*Sources*' in text
    assert '+00:00' not in text


def test_only_requested_verified_links_appear_and_are_deduplicated():
    text = answer_text('Here is the entry.', [FACT, FACT], 'hi-IN', ['calendar'])
    assert text.count(FACT['source']['calendar']['url']) == 1
    assert 'drive.google' not in text and '*कैलेंडर*' in text and '*स्रोत*' in text
    text = answer_text('Here are the notes.', [FACT], 'ta-IN', ['document'])
    assert 'drive.google' in text and 'calendar/event' not in text
    assert '*ஆதாரங்கள்*' in text


def test_unconfirmed_calendar_link_never_presented_as_synced():
    fact = {**FACT, 'source': {**SOURCE, 'calendar': {'status': 'unconfirmed', 'url': 'https://example.org/'}}}
    assert 'https://' not in answer_text('Waiting for Calendar.', [fact], 'en-IN', ['calendar'])


def test_notice_keeps_exceptions_and_original_reference():
    record = Extraction(kind='requirement', summary='Bring pencils, except red ones.', items=['pencils'], due_date='2026-10-20')
    text = saved_notice(record, '5B', SOURCE, reminder=True)
    assert 'except red ones' in text
    assert 'Tue, 20 Oct 2026' in text and 'Reminder scheduled' in text
    assert '_Saved · Ms. Rao' in text


def test_explicit_navigation_survives_an_omitted_model_ui_field():
    from octo.presentation import requested_link_types
    assert requested_link_types('Where are the Science Chapter 6 notes?') == ['document']
    assert requested_link_types('Show the calendar entry.') == ['calendar']
    assert requested_link_types('साइंस के नोट्स कहाँ हैं?') == ['document']
    assert requested_link_types('What topics are in the notes?') == []
    assert requested_link_types('What is the next exam?') == []
