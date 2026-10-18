import pytest

from octo.contracts import Extraction, GroundedAnswer
from test_core import octo, notice, output, put, question


async def test_competition_is_saved_with_date_arrival_and_participant_scope(octo):
    async def extract(*args):
        return Extraction(kind='event', summary='School Karate competition for participants.',
                          date_as_written='24th October', due_date=None,
                          instructions=['All participants should arrive by 10 AM.'])
    octo.ai.extract_notice = extract
    await put(octo, notice('KARATE', text='24th October the school is hosting Karate competetion, request all the participants to arrive by 10 AM'))
    fact = octo.store.class_facts('5B')[0]
    assert fact['extraction']['kind'] == 'event'
    assert fact['extraction']['school_day_status'] is None
    assert fact['extraction']['due_date'] == '2026-10-24'
    assert fact['extraction']['instructions'] == ['All participants should arrive by 10 AM.']
    assert fact['extraction']['unclear'] == []
    assert 'Karate competition' in output(octo) and '10 AM' in output(octo)
    assert '2026-10-24' in output(octo) and 'Which date' not in output(octo)
    octo.ai.answer_override = GroundedAnswer(language_code='en-IN', text='The Karate competition is on 24 October; participants should arrive by 10 AM.', source_ids=[fact['source_id']])
    await put(octo, question(text='When is the Karate competition?'))
    assert octo.ai.answer_calls[-1][0][0]['extraction']['kind'] == 'event'
    assert fact['source_id'] in output(octo)


async def test_half_day_is_saved_without_inventing_dismissal_time(octo):
    async def extract(*args):
        return Extraction(kind='school_day', school_day_status='half_day',
                          date_as_written='upcoming Friday', due_date='2026-10-30')
    octo.ai.extract_notice = extract
    await put(octo, notice('HALFDAY', text='upcoming Friday will be halfday'))
    fact = octo.store.class_facts('5B')[0]
    assert fact['extraction']['due_date'] == '2026-10-23'
    assert fact['extraction']['school_day_status'] == 'half_day'
    assert fact['extraction']['instructions'] == []
    assert 'Half-day classes.' in output(octo)
    assert 'Classes as usual.' not in output(octo) and 'No classes.' not in output(octo)


async def test_undated_event_is_preserved_but_date_is_clarified(octo):
    async def extract(*args):
        return Extraction(kind='event', summary='School Karate competition.', date_as_written=None, due_date='2099-01-01')
    octo.ai.extract_notice = extract
    await put(octo, notice(text='The school is hosting a Karate competition.'))
    fact = octo.store.class_facts('5B')[0]
    assert fact['extraction']['due_date'] is None
    assert 'What date is this event?' in output(octo)


@pytest.mark.parametrize('record', [
    Extraction(kind='unknown', summary='Did someone ask whether there is a competition?'),
    Extraction(kind='event'),
    Extraction(kind='event', summary='Karate competition cancelled.', status='cancelled'),
    Extraction(kind='event', summary='Karate competition moved.', replaces_source_ids=['old-notice']),
    Extraction(kind='school_day', school_day_status='half_day', subject='Science', date_as_written='tomorrow'),
])
async def test_unsupported_or_subject_only_notice_is_not_saved(octo, record):
    async def extract(*args):
        return record
    octo.ai.extract_notice = extract
    await put(octo, notice(text='A question or unclear subject-specific notice.'))
    assert octo.store.counts()['facts'] == 0
