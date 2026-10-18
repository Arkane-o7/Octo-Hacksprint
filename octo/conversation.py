"""Chat-scoped reference memory. Current school facts remain authoritative."""
from __future__ import annotations

import hashlib
import json
import re

from .contracts import IncomingMessage
from .waha import _jid

HISTORY_LIMIT = 12
TEXT_LIMIT = 1600
CONTEXT_LIMIT = 16000


def scope(person):
    return (person['id'], person['role'], person.get('class_id'),
            tuple(sorted(person.get('student_ids', []))), tuple(sorted(person.get('classes', []))),
            person.get('class_wide_only', False))


def version(fact):
    return hashlib.sha256(json.dumps(fact['extraction'], sort_keys=True).encode()).hexdigest()


def message_token(value, chats):
    """WAHA serialized IDs and NOWEB raw stanza IDs refer to the same message."""
    if not value:
        return None
    if value.startswith(('true_', 'false_')):
        parts = value.split('_', 3)
        if len(parts) < 3 or _jid(parts[1]) not in chats:
            return None
        return parts[2]
    return value


def chat_aliases(event):
    # Only transport-verified aliases of this account may identify the same DM.
    # Other numbers assigned to a roster parent are still separate conversations.
    return {_jid(event.chat_id), *(_jid(x) for x in event.sender_aliases if not event.is_group)}


class Conversation:
    def __init__(self, app):
        self.app = app
        self.db.execute('''CREATE TABLE IF NOT EXISTS chat_answers (
            source_id TEXT PRIMARY KEY, text TEXT NOT NULL, source_ids TEXT NOT NULL,
            versions TEXT NOT NULL, student_ids TEXT NOT NULL, basis TEXT NOT NULL
        )''')
        self.db.commit()

    @property
    def db(self):
        return self.app.store.db

    def save(self, sid, answer, facts, students):
        cited = {f['source_id']: version(f) for f in facts if f['source_id'] in answer.source_ids}
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO chat_answers VALUES(?,?,?,?,?,?)',
                            (sid, answer.text, json.dumps(answer.source_ids), json.dumps(cited),
                             json.dumps([s['id'] for s in students]), answer.basis))

    def _valid_answer(self, row, facts):
        versions = json.loads(row['versions'])
        return all(sid in facts and version(facts[sid]) == digest for sid, digest in versions.items())

    def delivery_allowed(self, reply, person):
        row = self.db.execute('SELECT * FROM chat_answers WHERE source_id=?',
                              (reply['dedupe_key'].split(':')[0],)).fetchone()
        if not row:
            return True
        facts = self.app.store.facts_for(person, self.app.roster.permitted_students(person))
        return self._valid_answer(row, {f['source_id']: f for f in facts})

    def _rows(self, event, person):
        # Filter in SQL before imposing a limit so other chats cannot evict this
        # parent's history. JSON is existing encrypted inbox data, not SQL input.
        chats = sorted(chat_aliases(event))
        return self.db.execute('''SELECT * FROM inbox WHERE status='done'
            AND json_extract(event,'$.session')=? AND json_extract(event,'$.chat_id') IN ('''
            + ','.join('?' for _ in chats) + ''')
            AND json_extract(context,'$.id')=? ORDER BY created DESC, rowid DESC''',
            (event.session, *chats, person['id']))

    def _eligible(self, row, event, person):
        previous = IncomingMessage.model_validate_json(row['event'])
        return (previous.source_key != event.source_key and previous.timestamp <= event.timestamp
                and scope(json.loads(row['context'])) == scope(person))

    def _user_entry(self, row):
        event = IncomingMessage.model_validate_json(row['event'])
        text = row['transcript'] or event.text
        return {'id': 'message:' + row['source_id'], 'kind': 'your_message',
                'timestamp': event.timestamp.isoformat(), 'text': text[:TEXT_LIMIT]}

    def _answer_entry(self, row, reply, facts):
        timestamp = IncomingMessage.model_validate_json(row['event']).timestamp.isoformat()
        saved = self.db.execute('SELECT * FROM chat_answers WHERE source_id=?', (row['source_id'],)).fetchone()
        if saved:
            if not self._valid_answer(saved, facts):
                return None
            return {'id': 'reply:' + str(reply['id']), 'kind': 'assistant_reply',
                    'basis': saved['basis'], 'timestamp': timestamp,
                    'text': saved['text'][:TEXT_LIMIT], 'source_ids': json.loads(saved['source_ids']),
                    'student_ids': json.loads(saved['student_ids'])}
        # Legacy replies still need their actual text to resolve "explain this".
        # All citations must remain accessible, but their versions are unknown:
        # the text identifies the historical message, not current school truth.
        ids = list(dict.fromkeys(re.findall(r'\[([0-9a-f]{16}(?:-\d+)?)\]', reply['text'])))
        if not ids or any(sid not in facts for sid in ids):
            return None
        return {'id': 'reply:' + str(reply['id']), 'kind': 'assistant_reference',
                'timestamp': timestamp, 'source_versions_verified': False,
                'text': reply['text'].split('\n\nSources:\n', 1)[0][:TEXT_LIMIT],
                'previous_question': self._user_entry(row)['text'], 'source_ids': ids}

    def build(self, event, person, facts, text):
        current = {f['source_id']: f for f in facts}
        history = []
        for row in self._rows(event, person):
            if not self._eligible(row, event, person):
                continue
            entry = self._user_entry(row)
            if not entry['text']:
                continue
            reply = self.db.execute("SELECT * FROM outbox WHERE dedupe_key=? AND status IN ('sent','fixture')",
                                    (row['source_id'] + ':answer',)).fetchone()
            if reply:
                answer = self._answer_entry(row, reply, current)
                if answer:
                    entry['assistant'] = answer
            history.append(entry)
            if len(history) == HISTORY_LIMIT:
                break
        history.reverse()
        quoted = None
        if event.quoted_message_id or event.is_quoted:
            quoted = self._quote(event, person, current)
        result = {'history': history, 'quoted': quoted,
                  'current_message': {'id': 'current', 'kind': 'your_message',
                                      'timestamp': event.timestamp.isoformat(), 'text': text[:TEXT_LIMIT]}}
        # The selected quote wins over old chat history when the budget is tight.
        while history and len(json.dumps(result, ensure_ascii=False)) > CONTEXT_LIMIT:
            history.pop(0)
        return result

    def _quote(self, event, person, facts):
        chats = chat_aliases(event)
        if event.quoted_chat_id and _jid(event.quoted_chat_id) not in chats:
            return None
        wanted = message_token(event.quoted_message_id, chats)
        if not wanted:
            return None
        matches = []
        for row in self._rows(event, person):
            if not self._eligible(row, event, person):
                continue
            previous = IncomingMessage.model_validate_json(row['event'])
            if message_token(previous.message_id, chats) == wanted:
                entry = self._user_entry(row)
                if entry['text']:
                    matches.append(entry)
            for reply in self.db.execute("SELECT * FROM outbox WHERE dedupe_key LIKE ? AND kind='text' AND status IN ('sent','fixture')",
                                         (row['source_id'] + ':%',)):
                if _jid(reply['chat_id']) in chats and message_token(reply['remote_id'], chats) == wanted:
                    # Only the actual answer is referenceable as an answer;
                    # acknowledgements/cart notices do not inherit its metadata.
                    if reply['dedupe_key'] == row['source_id'] + ':answer':
                        entry = self._answer_entry(row, reply, facts)
                        if entry:
                            matches.append(entry)
        # A teacher notice in this group is represented only by the caller's
        # authorized extracted facts, never its unfiltered original body.
        ids = []
        for sid, fact in facts.items():
            if message_token(fact['source'].get('message_id'), chats) != wanted:
                continue
            raw = self.db.execute('SELECT provenance FROM facts WHERE source_id=?', (sid,)).fetchone()
            origin = self.db.execute('SELECT event FROM inbox WHERE source_id=?', (sid.split('-')[0],)).fetchone()
            if (raw and origin and json.loads(origin[0]).get('session') == event.session
                    and json.loads(raw[0]).get('chat_id') == event.chat_id):
                ids.append(sid)
        if ids:
            matches.append({'id': 'quoted_notice', 'kind': 'school_notice', 'source_ids': ids})
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def references(context):
        result = {'current': context['current_message']}
        for item in context['history']:
            result[item['id']] = item
            if item.get('assistant'):
                result[item['assistant']['id']] = item['assistant']
        if context['quoted']:
            result[context['quoted']['id']] = context['quoted']
        return result
