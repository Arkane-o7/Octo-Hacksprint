"""Short links use synthetic events and mocked HTTP, never live providers."""
import asyncio
from urllib.parse import parse_qs

import httpx
import pytest

from octo.calendar_links import CalendarLinks
from octo.contracts import GroundedAnswer
from octo.storage import Store
from test_core import octo, notice, output, put, question

ORIGINAL = 'https://www.google.com/calendar/event?eid=example%2Bvalue&ctz=Asia%2FKolkata'
SHORT = 'https://is.gd/abc123'


def successful(request):
    if request.method == 'POST':
        assert str(request.url) == 'https://is.gd/create.php'
        assert parse_qs(request.content.decode()) == {'format': ['json'], 'url': [ORIGINAL]}
        return httpx.Response(200, text='{"shorturl":"' + SHORT + '"}',
                              headers={'Content-Type': 'text/javascript; charset=utf8'})
    assert str(request.url) == SHORT
    return httpx.Response(301, headers={'Location': ORIGINAL})


async def test_verified_links_survive_restart_without_more_network_calls(tmp_path):
    path = tmp_path / 'test.sqlite3'
    store = Store(path)
    calls = []
    def remote(request):
        calls.append(request)
        return successful(request)
    links = CalendarLinks(store, enabled=True, transport=httpx.MockTransport(remote))
    try:
        assert await links.shorten(ORIGINAL) == SHORT
        assert len(calls) == 2
    finally:
        store.close()
    store = Store(path)
    try:
        links = CalendarLinks(store, enabled=True, transport=httpx.MockTransport(remote))
        links._retry_at = float('inf')  # Cached links also work during an outage.
        assert await links.shorten(ORIGINAL) == SHORT
        assert len(calls) == 2
    finally:
        store.close()


@pytest.mark.parametrize('failure', ['database', 'json_error', 'timeout', 'rate_limit', 'bad_url', 'wrong_destination'])
async def test_service_failure_keeps_original_and_cools_down(octo, failure):
    calls = []
    def remote(request):
        calls.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('fixture')
        if failure == 'database':
            return httpx.Response(200, text='Error, database insert failed')
        if failure == 'json_error':
            return httpx.Response(200, json={'errorcode': 4, 'errormessage': 'Unavailable'})
        if failure == 'rate_limit':
            return httpx.Response(429)
        if failure == 'bad_url':
            return httpx.Response(200, json={'shorturl': 'https://is.gd.evil.example/abc123'})
        if request.method == 'GET':
            return httpx.Response(301, headers={'Location': 'https://example.com/wrong-event'})
        return successful(request)
    links = CalendarLinks(octo.store, enabled=True, transport=httpx.MockTransport(remote))
    assert await links.shorten(ORIGINAL) == ORIGINAL
    count = len(calls)
    assert await links.shorten(ORIGINAL) == ORIGINAL
    assert await links.shorten(ORIGINAL.replace('example', 'another')) != SHORT
    assert len(calls) == count
    assert octo.store.calendar_link(ORIGINAL) is None


async def test_disabled_or_unrelated_links_never_leave_the_app(octo):
    def remote(request):
        pytest.fail('No network call should occur')
    links = CalendarLinks(octo.store, transport=httpx.MockTransport(remote))
    octo.store.save_calendar_link(ORIGINAL, SHORT)
    assert await links.shorten(ORIGINAL) == ORIGINAL  # Explicitly disabled.
    links.enabled = True
    for url in ('https://example.com/calendar/event?eid=private',
                'https://www.google.com/calendar/event?eid=private&access_token=secret',
                'https://www.google.com.evil.example/calendar/event?eid=test',
                'https://secret@www.google.com/calendar/event?eid=test',
                'https://drive.google.com/file/d/example/view'):
        assert await links.shorten(url) == url


async def test_cancellation_propagates_without_caching(octo):
    async def remote(request):
        raise asyncio.CancelledError()
    links = CalendarLinks(octo.store, enabled=True, transport=httpx.MockTransport(remote))
    with pytest.raises(asyncio.CancelledError):
        await links.shorten(ORIGINAL)
    assert octo.store.calendar_link(ORIGINAL) is None


async def test_answer_shows_short_links_but_keeps_canonical_source(octo):
    await put(octo, notice())
    sid = octo.store.class_facts('5B')[0]['source_id']
    metadata = {'status': 'synced', 'url': ORIGINAL, 'event_id': 'fixture'}
    octo.store.calendar_result(sid, 'demo@group.calendar.google.com', metadata)
    octo.calendar_links = CalendarLinks(octo.store, enabled=True, transport=httpx.MockTransport(successful))
    octo.ai.answer_override = GroundedAnswer(language_code='en-IN',
        text='Bring crayons. Calendar: ' + ORIGINAL, source_ids=[sid])
    await put(octo, question())
    assert 'Calendar: ' + SHORT in output(octo)
    assert ORIGINAL not in output(octo)
    assert octo.store.class_facts('5B')[0]['source']['calendar'] == metadata


async def test_failed_shortening_still_delivers_answer(octo):
    await put(octo, notice())
    sid = octo.store.class_facts('5B')[0]['source_id']
    octo.store.calendar_result(sid, 'demo@group.calendar.google.com', {'status': 'synced', 'url': ORIGINAL})
    octo.calendar_links = CalendarLinks(octo.store, enabled=True,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text='Error, database insert failed')))
    octo.ai.answer_override = GroundedAnswer(language_code='en-IN', text='Bring crayons.', source_ids=[sid])
    await put(octo, question())
    assert 'Bring crayons.' in output(octo)
    assert 'Calendar: ' + ORIGINAL in output(octo)
    assert all(reply['status'] == 'fixture' for reply in octo.store.replies())
