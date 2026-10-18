"""Optional is.gd presentation links; canonical Calendar URLs stay unchanged."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from urllib.parse import parse_qs, urlsplit

import httpx

logger = logging.getLogger(__name__)


class CalendarLinks:
    def __init__(self, store, *, enabled=False, transport=None):
        self.store = store
        self.enabled = enabled
        self.transport = transport
        self._retry_at = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _calendar_url(url):
        try:
            parsed = urlsplit(url)
            query = parse_qs(parsed.query, keep_blank_values=True)
            return (parsed.scheme == 'https'
                    and parsed.netloc in ('www.google.com', 'calendar.google.com')
                    and parsed.path == '/calendar/event' and not parsed.fragment
                    and bool(query.get('eid', [''])[0])
                    and set(query) <= {'eid', 'ctz', 'hl'} and len(url) <= 2048)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _short_url(url):
        return isinstance(url, str) and bool(re.fullmatch(r'https://is\.gd/[A-Za-z0-9_]{5,30}', url))

    async def shorten(self, url):
        if not self.enabled or not self._calendar_url(url):
            return url
        async with self._lock:
            try:
                cached = self.store.calendar_link(url)
                if self._short_url(cached):
                    return cached
                if time.monotonic() < self._retry_at:
                    return url
                # Bound the entire create + verification operation, not just
                # individual network reads. No automatic request retries.
                async with asyncio.timeout(3):
                    async with httpx.AsyncClient(timeout=2, follow_redirects=False,
                                                 transport=self.transport) as client:
                        result = await client.post('https://is.gd/create.php',
                                                   data={'format': 'json', 'url': url})
                        result.raise_for_status()
                        data = result.json()  # is.gd may label JSON as text/javascript.
                        short = data.get('shorturl') if isinstance(data, dict) else None
                        if not self._short_url(short):
                            raise ValueError('Short link unavailable')
                        redirect = await client.get(short)
                        if (redirect.status_code not in (301, 302, 307, 308)
                                or redirect.headers.get('location') != url):
                            raise ValueError('Short link destination not verified')
                self.store.save_calendar_link(url, short)
                return short
            except Exception as exc:
                # Do not log response bodies or private event URLs. A failed
                # shortener must never prevent delivery of the actual answer.
                self._retry_at = time.monotonic() + 60
                logger.warning('Calendar short link unavailable (%s); using original URL', type(exc).__name__)
                return url
