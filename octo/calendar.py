"""All-day events on one explicit demo calendar; no invitations or reminders.

Only local authorized-user JSON is read. Deterministic event IDs and read-only
recovery make an interrupted write safe to reconcile on a later run.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx


TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDARS_URL = "https://www.googleapis.com/calendar/v3/calendars"
NOT_CONFIGURED = "Google Calendar is not configured; the school record remains saved locally. Configure local OAuth and an explicit secondary demo calendar."


class CalendarError(RuntimeError):
    """Safe message: never includes credentials, provider bodies or local paths."""

    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


def _event_id(source_id: str) -> str:
    if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 200:
        raise CalendarError("The school source reference is invalid; Calendar was not changed.")
    # Hex is a subset of Google's base32hex alphabet (a-v, 0-9).
    return "octo" + hashlib.sha256(source_id.encode()).hexdigest()


def _description(source_id: str, class_id: str, extraction: dict) -> str:
    # Only scoped structured fields, never original message/transcript/provenance.
    lines = ["Octo source: " + source_id, "Class: " + class_id]
    if extraction.get('summary'):
        lines.extend(['', extraction['summary']])
    if extraction.get("items"):
        lines.extend(["", "Bring:", *("• " + item for item in extraction["items"])])
    if extraction.get("sections"):
        lines.extend(["", "Study checklist:"])
        for section in extraction["sections"]:
            if section.get("chapter"):
                lines.append(section["chapter"])
            if section.get("pages"):
                lines.append("Pages: " + section["pages"])
            lines.extend("• " + topic for topic in section.get("topics", []))
    if extraction.get("instructions"):
        lines.extend(["", "Instructions:", *("• " + item for item in extraction["instructions"])])
    return html.escape("\n".join(lines))


class GoogleCalendarClient:
    def __init__(self, credentials_path: Path | None, calendar_id: str, *, client: httpx.AsyncClient | None = None):
        self.calendar_id = calendar_id.strip()
        self._credentials: dict | None = None
        # Secondary calendars have this suffix. Reject primary aliases AND the
        # personal email ID rather than accidentally writing to a personal calendar.
        valid_calendar = re.fullmatch(r"[A-Za-z0-9_.+-]+@group\.calendar\.google\.com", self.calendar_id)
        if credentials_path is not None and valid_calendar:
            try:
                data = json.loads(Path(credentials_path).read_text())
                keys = ("client_id", "client_secret", "refresh_token")
                if isinstance(data, dict) and all(isinstance(data.get(key), str) and data[key].strip() for key in keys):
                    self._credentials = {key: data[key] for key in keys}
            except (OSError, ValueError):
                pass
        self._events_url = CALENDARS_URL + "/" + quote(self.calendar_id, safe="") + "/events"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False)
        self._access_token = ""
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        """Local configuration only; not proof of consent or calendar access."""
        return self._credentials is not None

    async def close(self):
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method, url, *, allow=(), **kwargs):
        try:
            response = await self._client.request(method, url, follow_redirects=False, timeout=30, **kwargs)
        except httpx.RequestError:
            raise CalendarError("Google Calendar could not confirm this request. The school record remains saved locally; retry Calendar sync to reconcile it.", uncertain=True) from None
        if 200 <= response.status_code < 300 or response.status_code in allow:
            return response
        if url == TOKEN_URL:
            raise CalendarError("Google Calendar OAuth refresh failed. Reconnect the demo credentials locally; the school record remains saved.")
        if response.status_code in (401, 403):
            self._access_token = ""
            raise CalendarError("Google Calendar access was denied. Check OAuth consent and access to the demo calendar; the school record remains saved.")
        raise CalendarError("Google Calendar did not confirm the operation. The school record remains saved locally; retry Calendar sync to reconcile it.", uncertain=response.status_code >= 500 or response.status_code == 429)

    @staticmethod
    def _json(response):
        try:
            data = response.json()
        except ValueError:
            raise CalendarError("Google Calendar returned an unreadable response; sync was not confirmed.", uncertain=True) from None
        if not isinstance(data, dict):
            raise CalendarError("Google Calendar returned an unexpected response; sync was not confirmed.", uncertain=True)
        return data

    async def _auth(self):
        if not self.configured:
            raise CalendarError(NOT_CONFIGURED)
        if not self._access_token or time.monotonic() >= self._expires_at:
            response = await self._request("POST", TOKEN_URL, data={**self._credentials, "grant_type": "refresh_token"})
            data = self._json(response)
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                raise CalendarError("Google Calendar OAuth did not return an access token; the school record remains saved locally.")
            try:
                lifetime = max(0, min(float(data.get("expires_in", 3600)) - 60, 3600))
            except (TypeError, ValueError):
                lifetime = 0
            self._access_token = token
            self._expires_at = time.monotonic() + lifetime
        return {"Authorization": "Bearer " + self._access_token}

    async def _get(self, event_id):
        response = await self._request("GET", self._events_url + "/" + event_id, headers=await self._auth(), allow=(404, 410))
        if response.status_code in (404, 410):
            return None
        data = self._json(response)
        if data.get("id") != event_id:
            raise CalendarError("Google Calendar returned a different event reference; sync was not confirmed.")
        return data

    @staticmethod
    def _matches(data, body):
        return bool(data and all(data.get(key) == value for key, value in body.items()) and not data.get("attendees"))

    @staticmethod
    def _check_owned(existing, source_id):
        extended = existing.get("extendedProperties")
        properties = extended.get("private") if isinstance(extended, dict) else None
        if (not isinstance(properties, dict) or properties.get("octo_source_id") != source_id
                or existing.get("attendees") or existing.get("attendeesOmitted")
                or existing.get("recurrence") or existing.get("recurringEventId")):
            raise CalendarError("The matching Calendar event was changed outside Octo. Check the demo calendar before syncing.")

    @staticmethod
    def _result(data, event_id):
        if data.get("id") != event_id or data.get("status") == "cancelled":
            raise CalendarError("Google Calendar did not confirm the expected event; sync was not confirmed.", uncertain=True)
        result = {"status": "synced", "event_id": event_id}
        url = data.get("htmlLink")
        if isinstance(url, str):
            try:
                parsed = urlsplit(url)
                if (parsed.scheme == "https" and not parsed.username and not parsed.password
                        and (parsed.hostname == "calendar.google.com" or (parsed.hostname == "www.google.com" and parsed.path.startswith("/calendar/")))):
                    result["url"] = url
            except ValueError:
                pass
        return result

    async def sync_fact(self, fact: dict) -> dict:
        source_id = fact.get("source_id")
        event_id = _event_id(source_id)
        extraction = fact.get("extraction")
        if not isinstance(extraction, dict):
            raise CalendarError("The school record is invalid; Calendar was not changed.")
        status = extraction.get("status", "active")
        if status in ("cancelled", "completed"):
            return await self.delete_fact(source_id)
        if status != "active":
            raise CalendarError("The school record status is invalid; Calendar was not changed.")
        due = extraction.get("due_date")
        if due is None:
            return {"status": "skipped", "event_id": event_id}
        try:
            if not isinstance(due, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
                raise ValueError
            end = (date.fromisoformat(due) + timedelta(days=1)).isoformat()
        except (ValueError, OverflowError):
            raise CalendarError("Please confirm a valid school date; Calendar was not changed.") from None
        if not self.configured:
            raise CalendarError(NOT_CONFIGURED)
        title = extraction.get("summary") or " ".join(str(extraction.get(key) or "") for key in ("subject", "kind"))
        if extraction.get("kind") == "school_day":
            title = {"no_classes": "No classes", "classes_scheduled": "Classes as usual", "half_day": "Half-day classes"}.get(extraction.get("school_day_status"), title)
        class_id = str(fact.get("class_id", ""))
        title = "Class " + " ".join(class_id.split()) + " — " + (" ".join(str(title).split()) or "School notice")
        body = {
            "id": event_id, "status": "confirmed", "summary": title[:250],
            "description": _description(source_id, class_id, extraction),
            "start": {"date": due}, "end": {"date": end},
            "reminders": {"useDefault": False}, "transparency": "transparent",
            "extendedProperties": {"private": {"octo_source_id": source_id}},
        }
        existing = await self._get(event_id)
        if existing and existing.get("status") != "cancelled":
            self._check_owned(existing, source_id)
            if self._matches(existing, body):
                return self._result(existing, event_id)
        headers = await self._auth()
        if existing and existing.get("etag"):
            headers["If-Match"] = existing["etag"]
        try:
            response = await self._request("PUT" if existing else "POST",
                self._events_url + ("/" + event_id if existing else ""),
                headers=headers, params={"sendUpdates": "none"}, json=body, allow=(409,))
            if response.status_code == 409:
                raise CalendarError("Google Calendar already has this event, but sync was not confirmed. Retry Calendar sync to reconcile it.", uncertain=True)
            return self._result(self._json(response), event_id)
        except CalendarError as original:
            if original.uncertain:
                # Never repeat a write after an ambiguous result. Exact GET can
                # prove it applied; a later sync uses the same deterministic ID.
                try:
                    recovered = await self._get(event_id)
                    if self._matches(recovered, body):
                        return self._result(recovered, event_id)
                except CalendarError:
                    pass
            raise original from None

    async def delete_fact(self, source_id: str) -> dict:
        event_id = _event_id(source_id)
        result = {"status": "deleted", "event_id": event_id}
        existing = await self._get(event_id)
        if existing is None or existing.get("status") == "cancelled":
            return result
        self._check_owned(existing, source_id)
        headers = await self._auth()
        if existing.get("etag"):
            headers["If-Match"] = existing["etag"]
        try:
            await self._request("DELETE", self._events_url + "/" + event_id,
                headers=headers, params={"sendUpdates": "none"}, allow=(404, 410))
            return result
        except CalendarError as original:
            if original.uncertain:
                try:
                    remaining = await self._get(event_id)
                    if remaining is None or remaining.get("status") == "cancelled":
                        return result
                except CalendarError:
                    pass
            raise original from None
