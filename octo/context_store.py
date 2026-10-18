"""Small persistence helper using the Store's existing encrypted connection."""
import json
import time

from .conversation import scope


class ContextStore:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS conversation_context (
            scope TEXT NOT NULL, kind TEXT NOT NULL, slot TEXT NOT NULL,
            payload TEXT NOT NULL, expires REAL NOT NULL,
            PRIMARY KEY(scope,kind,slot))''')
        self.db.commit()

    def put(self, event, caller, kind, payload, *, slot='', ttl=1800):
        if kind == 'teacher' and len(self.get(event, caller, kind)) >= 8:
            slot, payload = '__ambiguous__', {}
        payload = dict(payload, timestamp=event.timestamp.isoformat())
        with self.db:
            self.db.execute('DELETE FROM conversation_context WHERE expires<?', (time.time(),))
            if kind == 'answer_intent':
                self.db.execute('''DELETE FROM conversation_context WHERE scope=? AND kind=? AND slot NOT IN
                    (SELECT slot FROM conversation_context WHERE scope=? AND kind=? ORDER BY expires DESC LIMIT 7)''',
                    (json.dumps(scope(event, caller)), kind, json.dumps(scope(event, caller)), kind))
            self.db.execute('INSERT OR REPLACE INTO conversation_context VALUES(?,?,?,?,?)',
                            (json.dumps(scope(event, caller)), kind, slot, json.dumps(payload), time.time() + ttl))

    def get(self, event, caller, kind):
        rows = self.db.execute('SELECT slot,payload FROM conversation_context WHERE scope=? AND kind=? AND expires>?',
                               (json.dumps(scope(event, caller)), kind, time.time())).fetchall()
        result = []
        from datetime import datetime
        for row in rows:
            payload = json.loads(row['payload'])
            age = (event.timestamp - datetime.fromisoformat(payload['timestamp'])).total_seconds()
            if 0 <= age <= (1800 if kind == 'parent' else 86400):
                result.append((row['slot'], payload))
        return result

    def completed(self, source_id):
        return self.db.execute('SELECT 1 FROM applied_decisions WHERE source_key=?', ('clarified:' + source_id,)).fetchone() is not None

    def complete_date(self, slot, pending, record, event, caller):
        """Amend the SAME fact and consume pending state in one transaction."""
        from .contracts import IncomingMessage
        original = IncomingMessage.model_validate(pending['event'])
        with self.db:
            if self.completed(slot):
                return False
            row = self.db.execute('SELECT provenance FROM facts WHERE source_id=?', (slot,)).fetchone()
            source = json.loads(row[0]) if row else {
                'source_id': slot, 'sender': caller['name'], 'chat_id': original.chat_id,
                'message_id': original.message_id, 'timestamp': original.timestamp.isoformat(),
                'text': original.text, 'media_path': original.media.local_path if original.media else None,
            }
            source['clarifications'] = [{'message_id': event.message_id, 'timestamp': event.timestamp.isoformat(), 'text': event.text}]
            source['ocr_text'] = pending.get('ocr_text')
            self.db.execute('''INSERT INTO facts VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id)
                DO UPDATE SET extraction=excluded.extraction,provenance=excluded.provenance''',
                (slot, caller['class_id'], None, None, record.model_dump_json(), json.dumps(source), time.time()))
            self.db.execute('INSERT INTO applied_decisions VALUES(?,?)', ('clarified:' + slot, event.source_key))
            self.db.execute('INSERT OR IGNORE INTO applied_decisions VALUES(?,?)', ('date-reply:' + event.source_key, slot))
            self.db.execute('DELETE FROM conversation_context WHERE scope=? AND kind=? AND slot=?',
                            (json.dumps(scope(event, caller)), 'teacher', slot))
        return True
