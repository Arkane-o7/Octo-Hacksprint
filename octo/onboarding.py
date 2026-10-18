"""Authenticated group-join onboarding, kept separate from user messages/facts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import time

from .contracts import IncomingMessage
from .menus import scope
from .waha import _jid, _mapping, _person, _string

JOIN_EVENT = 'group.v2.participants'
MAX_JOIN_AGE = 24 * 60 * 60
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class GroupJoin:
    session: str
    group_id: str
    participant_ids: tuple[str, ...]
    bot_id: str
    timestamp: float


def normalize_join(envelope: dict) -> GroupJoin | None:
    """WAHA v2 participant joins, never requests, promotions or bot-group joins.

    Call only after HMAC verification. Current membership remains authoritative.
    Official contract: https://waha.devlike.pro/docs/how-to/events/#groupv2participants
    """
    if not isinstance(envelope, dict) or envelope.get('event') != JOIN_EVENT:
        return None
    payload = _mapping(envelope.get('payload'))
    if payload.get('type') != 'join':
        return None
    session = _string(envelope.get('session'))
    group = _jid(_mapping(payload.get('group')).get('id'))
    bot_id = _jid(_mapping(envelope.get('me')).get('id'))
    participants = payload.get('participants')
    stamp = payload.get('timestamp')
    if (not session or not group.endswith('@g.us') or not _person(bot_id)
            or not isinstance(participants, list) or not participants
            or isinstance(stamp, bool) or not isinstance(stamp, (float, int)) or not math.isfinite(stamp)):
        raise ValueError('Invalid group join event')
    stamp = stamp / 1000 if stamp >= 1_000_000_000_000 else stamp
    try:
        datetime.fromtimestamp(stamp, timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise ValueError('Invalid group join timestamp') from None
    ids = []
    for participant in participants:
        identifier = _jid(_mapping(participant).get('id'))
        if not _person(identifier):
            raise ValueError('Invalid joining participant')
        if identifier != bot_id and identifier not in ids:
            ids.append(identifier)
    return GroupJoin(session, group, tuple(ids), bot_id, stamp)


class Onboarding:
    def __init__(self, app):
        self.app = app
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS ux_join_jobs (
                id TEXT PRIMARY KEY, session TEXT NOT NULL, group_id TEXT NOT NULL,
                member_id TEXT NOT NULL, bot_id TEXT NOT NULL, joined_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt REAL NOT NULL DEFAULT 0, person_id TEXT, destination TEXT,
                scope TEXT, error TEXT,
                UNIQUE(session,group_id,person_id)
            );
        ''')

    @property
    def db(self):
        return self.app.store.db

    def accept(self, event: GroupJoin) -> str:
        if (event.session != self.app.settings.waha_session or event.group_id not in self.app.roster.data['groups']
                or not event.participant_ids or not -300 <= time.time() - event.timestamp <= MAX_JOIN_AGE):
            return 'ignored'
        added = 0
        with self.db:
            for member in event.participant_ids:
                key = hashlib.sha256(json.dumps([event.session, event.group_id, member]).encode()).hexdigest()[:32]
                added += self.db.execute('INSERT OR IGNORE INTO ux_join_jobs(id,session,group_id,member_id,bot_id,joined_at) VALUES(?,?,?,?,?,?)',
                    (key, event.session, event.group_id, member, event.bot_id, event.timestamp)).rowcount
        return 'queued' if added else 'duplicate'

    @staticmethod
    def event(row, *, destination=None, group=False):
        # Routing-only envelope. Never inserted into inbox, quoted, transcribed,
        # sent to the LLM, or treated as a user instruction or cart approval.
        return IncomingMessage(session=row['session'], message_id='join:' + row['id'],
            sender_id=destination or row['member_id'],
            chat_id=row['group_id'] if group else destination or row['member_id'],
            is_group=group, timestamp=datetime.fromtimestamp(row['joined_at'], timezone.utc))

    def _finish(self, row, status, error=None):
        with self.db:
            self.db.execute('UPDATE ux_join_jobs SET status=?,error=? WHERE id=?', (status, error, row['id']))

    def _retry(self, row):
        attempts = row['attempts'] + 1
        with self.db:
            self.db.execute('UPDATE ux_join_jobs SET attempts=?,status=?,next_attempt=?,error=? WHERE id=?',
                (attempts, 'failed' if attempts >= MAX_ATTEMPTS else 'pending', time.time() + 15 * attempts,
                 'Current group membership could not be verified.', row['id']))

    async def process_one(self):
        row = self.db.execute("SELECT * FROM ux_join_jobs WHERE status='pending' AND next_attempt<=? ORDER BY joined_at,id LIMIT 1", (time.time(),)).fetchone()
        if not row:
            return False
        if (row['session'] != self.app.settings.waha_session or row['group_id'] not in self.app.roster.data['groups']
                or time.time() - row['joined_at'] > MAX_JOIN_AGE):
            self._finish(row, 'ignored')
            return True
        await self.app.refresh_memberships()
        members = self.app.roster.memberships.get(row['group_id'], {})
        aliases = members.get(row['member_id'], ())
        if not aliases:
            self._retry(row)  # Allow membership API lag without ever trusting the event alone.
            return True
        if row['bot_id'] in aliases:
            self._finish(row, 'ignored')
            return True
        group_caller = self.app.roster.resolve(self.event(row, group=True))
        if not group_caller or group_caller['role'] != 'parent':
            self._finish(row, 'ignored')
            return True
        destination = min(aliases, key=lambda value: (not value.endswith('@c.us'), value))
        event = self.event(row, destination=destination)
        parent = self.app.roster.resolve(event)
        if not parent or parent['role'] != 'parent' or parent['id'] != group_caller['id']:
            self._finish(row, 'ignored')
            return True
        existing = self.db.execute('SELECT id FROM ux_join_jobs WHERE session=? AND group_id=? AND person_id=?',
                                   (row['session'], row['group_id'], parent['id'])).fetchone()
        # Do not replace an existing conversation/menu with a late welcome.
        menu = self.db.execute('SELECT 1 FROM ux_menus WHERE session=? AND chat=? AND person=?',
                               (row['session'], destination, parent['id'])).fetchone()
        if (existing and existing['id'] != row['id']) or menu:
            self._finish(row, 'duplicate' if existing else 'engaged')
            return True
        parent = self.app.menus.preferences(event, parent)
        # One transaction binds recipient/scope, queues an unquoted welcome and
        # registers its menu. A restart can never leave a half-queued welcome.
        with self.db:
            self.db.execute("UPDATE ux_join_jobs SET status='queued',person_id=?,destination=?,scope=?,error=NULL WHERE id=?",
                            (parent['id'], destination, scope(parent), row['id']))
            self.app.menus.welcome('join:' + row['id'], event, parent)
        return True

    def delivery_allowed(self, reply):
        parts = reply['dedupe_key'].split(':')
        if len(parts) != 3 or parts[0] != 'join' or parts[2] != 'answer':
            return False
        row = self.db.execute('SELECT * FROM ux_join_jobs WHERE id=?', (parts[1],)).fetchone()
        if (not row or row['status'] != 'queued' or row['session'] != self.app.settings.waha_session
                or row['destination'] != reply['chat_id'] or reply.get('reply_to')
                or time.time() - row['joined_at'] > MAX_JOIN_AGE
                or row['group_id'] not in self.app.roster.data['groups']):
            return False
        if row['destination'] not in self.app.roster.memberships.get(row['group_id'], {}):
            return False
        parent = self.app.roster.resolve(self.event(row, destination=row['destination']))
        return bool(parent and parent['role'] == 'parent' and parent['id'] == row['person_id'] and scope(parent) == row['scope'])
