import copy
import hashlib
import json
import re
from urllib.parse import parse_qs

import httpx
import pytest

from octo.calendar import CalendarError, GoogleCalendarClient


CALENDAR_ID = "demo_123@group.calendar.google.com"


@pytest.fixture
def credentials(tmp_path):
    path = tmp_path / "fake-oauth.json"
    path.write_text(json.dumps({"client_id": "fake-client", "client_secret": "fake-secret", "refresh_token": "fake-refresh"}))
    return path


@pytest.fixture
def fact():
    return {"source_id": "source-one", "class_id": "5B", "extraction": {
        "kind": "test", "subject": "Science", "summary": "Science test: Plants",
        "status": "active", "due_date": "2028-02-29"},
        "provenance": {"text": "PRIVATE-TEACHER-TEXT", "sender": "PRIVATE-PHONE", "media_path": "/private/source"}}


class FakeCalendar:
    def __init__(self):
        self.calls = []
        self.events = {}
        self.timeout_method = None
        self.apply_before_timeout = True
        self.token_status = 200
        self.api_status = None
        self.conflict_on_create = False
        self.web_link = "https://www.google.com/calendar/event?eid=actual-provider-link"

    def __call__(self, request):
        self.calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert request.url.path == "/token" and request.method == "POST"
            assert parse_qs(request.content.decode()) == {
                "client_id": ["fake-client"], "client_secret": ["fake-secret"],
                "refresh_token": ["fake-refresh"], "grant_type": ["refresh_token"]}
            assert "Authorization" not in request.headers
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "SECRET-PROVIDER-BODY"})
            return httpx.Response(200, json={"access_token": "fake-access", "expires_in": 3600})
        assert request.url.host == "www.googleapis.com"
        assert request.headers["Authorization"] == "Bearer fake-access"
        assert request.url.path.startswith("/calendar/v3/calendars/" + CALENDAR_ID + "/events")
        if self.api_status:
            return httpx.Response(self.api_status, json={"error": "SECRET-PROVIDER-BODY"})
        event_id = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            return httpx.Response(200, json=self.events[event_id]) if event_id in self.events else httpx.Response(404)
        assert request.url.params["sendUpdates"] == "none"
        if request.method in ("POST", "PUT"):
            body = json.loads(request.content)
            assert "attendees" not in body
            assert body["reminders"] == {"useDefault": False}
            assert "dateTime" not in body["start"] and "dateTime" not in body["end"]
            if request.method == "POST":
                event_id = body["id"]
            else:
                assert body["id"] == event_id
                assert request.headers["If-Match"] == self.events[event_id]["etag"]
            stored = {**body, "etag": '"version-1"', "htmlLink": self.web_link}
            if self.timeout_method != request.method or self.apply_before_timeout:
                self.events[event_id] = stored
            if self.timeout_method == request.method:
                raise httpx.ReadTimeout("SECRET-NETWORK-DETAILS", request=request)
            if self.conflict_on_create and request.method == "POST":
                return httpx.Response(409)
            return httpx.Response(200, json=stored)
        if request.method == "DELETE":
            existed = event_id in self.events
            if existed:
                assert request.headers["If-Match"] == self.events[event_id]["etag"]
            if self.timeout_method != "DELETE" or self.apply_before_timeout:
                self.events.pop(event_id, None)
            if self.timeout_method == "DELETE":
                raise httpx.ReadTimeout("SECRET-NETWORK-DETAILS", request=request)
            return httpx.Response(204 if existed else 404)
        pytest.fail(f"Unexpected operation {request.method}")


async def test_create_all_day_event_is_scoped_minimal_and_has_real_link(credentials, fact):
    backend = FakeCalendar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        calendar = GoogleCalendarClient(credentials, CALENDAR_ID, client=http)
        assert calendar.configured
        result = await calendar.sync_fact(fact)
        await calendar.close()
        assert not http.is_closed
    identifier = "octo" + hashlib.sha256(fact["source_id"].encode()).hexdigest()
    assert re.fullmatch(r"[a-v0-9]{5,1024}", identifier)
    assert result == {"status": "synced", "event_id": identifier, "url": backend.web_link}
    event = backend.events[identifier]
    assert event["start"] == {"date": "2028-02-29"}
    assert event["end"] == {"date": "2028-03-01"}
    assert event["summary"] == "Class 5B — Science test: Plants"
    assert event["description"] == "Octo source: source-one\nClass: 5B"
    assert "PRIVATE" not in json.dumps(event)
    assert sum(r.method == "POST" and r.url.host == "www.googleapis.com" for r in backend.calls) == 1


async def test_repeat_is_read_only_and_changed_fact_updates_same_event(credentials, fact):
    backend = FakeCalendar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        calendar = GoogleCalendarClient(credentials, CALENDAR_ID, client=http)
        first = await calendar.sync_fact(fact)
        assert await calendar.sync_fact(fact) == first
        fact["extraction"].update(due_date="2028-03-04", summary="Science test postponed")
        assert await calendar.sync_fact(fact) == first
    assert len(backend.events) == 1
    assert backend.events[first["event_id"]]["start"] == {"date": "2028-03-04"}
    assert sum(r.method == "PUT" for r in backend.calls) == 1
    assert sum(r.method == "POST" and r.url.host == "www.googleapis.com" for r in backend.calls) == 1
    assert sum(r.url.host == "oauth2.googleapis.com" for r in backend.calls) == 1


@pytest.mark.parametrize("method", ["POST", "PUT"])
@pytest.mark.parametrize("applied", [True, False])
async def test_uncertain_write_uses_one_get_never_a_blind_write_retry(credentials, fact, method, applied):
    backend = FakeCalendar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        calendar = GoogleCalendarClient(credentials, CALENDAR_ID, client=http)
        if method == "PUT":
            await calendar.sync_fact(fact)
            fact["extraction"]["due_date"] = "2028-03-05"
        backend.calls.clear()
        backend.timeout_method = method
        backend.apply_before_timeout = applied
        if applied:
            assert (await calendar.sync_fact(fact))["status"] == "synced"
        else:
            with pytest.raises(CalendarError, match="could not confirm") as caught:
                await calendar.sync_fact(fact)
            assert "SECRET" not in str(caught.value)
        assert sum(r.method == method and r.url.host == "www.googleapis.com" for r in backend.calls) == 1
        assert sum(r.method == "GET" for r in backend.calls) == 2
        backend.timeout_method = None
        assert (await calendar.sync_fact(fact))["status"] == "synced"
        assert len(backend.events) == 1


async def test_conflicting_insert_recovers_exact_same_event(credentials, fact):
    backend = FakeCalendar()
    backend.conflict_on_create = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        assert (await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).sync_fact(fact))["status"] == "synced"
    assert len(backend.events) == 1
    assert sum(r.method == "POST" and r.url.host == "www.googleapis.com" for r in backend.calls) == 1


@pytest.mark.parametrize("status", ["cancelled", "completed"])
async def test_inactive_fact_deletes_exact_event_without_creating(credentials, fact, status):
    backend = FakeCalendar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        calendar = GoogleCalendarClient(credentials, CALENDAR_ID, client=http)
        created = await calendar.sync_fact(fact)
        backend.calls.clear()
        fact["extraction"]["status"] = status
        assert await calendar.sync_fact(fact) == {"status": "deleted", "event_id": created["event_id"]}
        assert not backend.events
        assert (await calendar.sync_fact(fact))["status"] == "deleted"
    assert [r.method for r in backend.calls] == ["GET", "DELETE", "GET"]


@pytest.mark.parametrize("status", [404, 410])
async def test_delete_missing_event_is_success(credentials, status):
    backend = FakeCalendar()
    backend.api_status = status
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        result = await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).delete_fact("old-source")
    assert result["status"] == "deleted"
    assert [r.method for r in backend.calls] == ["POST", "GET"]


@pytest.mark.parametrize("applied", [True, False])
async def test_delete_timeout_recovery_checks_current_state(credentials, fact, applied):
    backend = FakeCalendar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        calendar = GoogleCalendarClient(credentials, CALENDAR_ID, client=http)
        await calendar.sync_fact(fact)
        backend.calls.clear()
        backend.timeout_method = "DELETE"
        backend.apply_before_timeout = applied
        if applied:
            assert (await calendar.delete_fact(fact["source_id"]))["status"] == "deleted"
        else:
            with pytest.raises(CalendarError):
                await calendar.delete_fact(fact["source_id"])
    assert [r.method for r in backend.calls] == ["GET", "DELETE", "GET"]


@pytest.mark.parametrize("calendar_id", ["", "primary", "PRIMARY", "personal@gmail.com", "demo@group.calendar.google.com/../../primary"])
async def test_primary_or_invalid_calendar_cannot_be_used(credentials, fact, calendar_id):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected network"))) as http:
        calendar = GoogleCalendarClient(credentials, calendar_id, client=http)
        assert not calendar.configured
        with pytest.raises(CalendarError, match="not configured"):
            await calendar.sync_fact(fact)


@pytest.mark.parametrize("content", [None, "invalid json", "[]", '{"client_id":"missing-other-fields"}'])
async def test_missing_or_bad_credentials_do_not_make_requests(tmp_path, fact, content):
    path = tmp_path / "fake.json"
    if content is not None:
        path.write_text(content)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected network"))) as http:
        calendar = GoogleCalendarClient(path if content is not None else None, CALENDAR_ID, client=http)
        assert not calendar.configured
        with pytest.raises(CalendarError, match="not configured"):
            await calendar.sync_fact(fact)
        with pytest.raises(CalendarError, match="not configured"):
            await calendar.delete_fact("old-source")


@pytest.mark.parametrize("due", ["2026-02-30", "20261017", "2026-10-17T10:00:00Z", "tomorrow", "", "9999-12-31", 123])
async def test_malformed_date_is_rejected_before_auth(credentials, fact, due):
    fact["extraction"]["due_date"] = due
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected network"))) as http:
        with pytest.raises(CalendarError, match="valid school date"):
            await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).sync_fact(fact)


async def test_undated_record_is_explicitly_skipped(credentials, fact):
    fact["extraction"]["due_date"] = None
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected network"))) as http:
        result = await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).sync_fact(fact)
    assert result["status"] == "skipped" and "url" not in result


@pytest.mark.parametrize("target,code", [("token", 400), ("token", 401), ("api", 401), ("api", 403)])
async def test_auth_errors_are_safe_and_do_not_write(credentials, fact, target, code):
    backend = FakeCalendar()
    if target == "token":
        backend.token_status = code
    else:
        backend.api_status = code
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        with pytest.raises(CalendarError) as caught:
            await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).sync_fact(fact)
    assert "SECRET" not in str(caught.value) and "fake-secret" not in str(caught.value)
    assert not any(r.method in ("POST", "PUT", "DELETE") and r.url.host == "www.googleapis.com" for r in backend.calls)


@pytest.mark.parametrize("change", ["owner", "attendees", "recurrence", "recurringEventId", "attendeesOmitted"])
@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_external_event_changes_are_not_overwritten_or_deleted(credentials, fact, change, operation):
    backend = FakeCalendar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        calendar = GoogleCalendarClient(credentials, CALENDAR_ID, client=http)
        result = await calendar.sync_fact(fact)
        stored = backend.events[result["event_id"]]
        if change == "owner":
            stored["extendedProperties"]["private"]["octo_source_id"] = "different-source"
        elif change == "attendees":
            stored["attendees"] = [{"email": "someone@example.invalid"}]
        elif change == "recurrence":
            stored["recurrence"] = ["RRULE:FREQ=DAILY"]
        else:
            stored[change] = "external"
        before = copy.deepcopy(stored)
        fact["extraction"]["summary"] = "Changed summary"
        with pytest.raises(CalendarError, match="changed outside Octo"):
            if operation == "delete":
                await calendar.delete_fact(fact["source_id"])
            else:
                await calendar.sync_fact(fact)
        assert stored == before
    assert not any(r.method in ("PUT", "DELETE") for r in backend.calls)


async def test_structured_description_is_useful_and_html_escaped(credentials, fact):
    fact["extraction"].update(items=["crayons & drawing book"],
        sections=[{"chapter": "Chapter <6>", "pages": "42–47", "topics": ["Roots", "Leaves & stems"]}],
        instructions=["Bring <only> the workbook."])
    backend = FakeCalendar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        result = await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).sync_fact(fact)
    description = backend.events[result["event_id"]]["description"]
    assert "Bring:\n• crayons &amp; drawing book" in description
    assert "Study checklist:\nChapter &lt;6&gt;\nPages: 42–47\n• Roots\n• Leaves &amp; stems" in description
    assert "Instructions:\n• Bring &lt;only&gt; the workbook." in description
    assert "PRIVATE" not in description and "source-one" in description


@pytest.mark.parametrize("status,title", [("no_classes", "No classes"), ("classes_scheduled", "Classes as usual")])
async def test_school_day_title_states_the_actual_status(credentials, fact, status, title):
    fact["extraction"].update(kind="school_day", school_day_status=status, summary="Teacher's school notice")
    backend = FakeCalendar()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        result = await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).sync_fact(fact)
    assert backend.events[result["event_id"]]["summary"] == "Class 5B — " + title


@pytest.mark.parametrize("code", [404, 410])
async def test_event_removed_between_get_and_delete_is_success(credentials, fact, code):
    backend = FakeCalendar()

    def handle(request):
        if request.method == "DELETE":
            backend.calls.append(request)
            return httpx.Response(code)
        return backend(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        calendar = GoogleCalendarClient(credentials, CALENDAR_ID, client=http)
        await calendar.sync_fact(fact)
        assert (await calendar.delete_fact(fact["source_id"]))["status"] == "deleted"
    assert sum(r.method == "DELETE" for r in backend.calls) == 1


async def test_redirect_never_forwards_credentials(credentials, fact):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.invalid/secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as http:
        with pytest.raises(CalendarError):
            await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).sync_fact(fact)
    assert len(calls) == 1 and calls[0].url.host == "oauth2.googleapis.com"


@pytest.mark.parametrize("link", [None, "https://evil.invalid/pretend-calendar", "javascript:alert(1)", "https://[bad-host"])
async def test_never_invents_or_returns_untrusted_event_link(credentials, fact, link):
    backend = FakeCalendar()
    backend.web_link = link
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        result = await GoogleCalendarClient(credentials, CALENDAR_ID, client=http).sync_fact(fact)
    assert result["status"] == "synced" and "url" not in result
