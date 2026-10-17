"""SQLite persistence for a single demo process; no external queue."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from .contracts import IncomingMessage, Extraction


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS inbox (
                source_key TEXT PRIMARY KEY, source_id TEXT UNIQUE NOT NULL,
                event TEXT NOT NULL, context TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                job_id TEXT, next_poll REAL NOT NULL DEFAULT 0,
                created REAL NOT NULL, transcript TEXT, ocr_text TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS facts (
                source_id TEXT PRIMARY KEY, class_id TEXT NOT NULL,
                owner_id TEXT, student_id TEXT, extraction TEXT NOT NULL,
                provenance TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL,
                chat_id TEXT NOT NULL, text TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'text',
                path TEXT, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                remote_id TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS fact_replacements (
                old_source_id TEXT NOT NULL, new_source_id TEXT NOT NULL,
                PRIMARY KEY(old_source_id,new_source_id)
            );
            CREATE TABLE IF NOT EXISTS applied_decisions (
                source_key TEXT PRIMARY KEY, decision TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL, parent_id TEXT NOT NULL,
                chat_id TEXT NOT NULL, due_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS documents (
                source_key TEXT PRIMARY KEY, metadata TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS calendar_jobs (
                source_id TEXT NOT NULL, calendar_id TEXT NOT NULL,
                operation TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                metadata TEXT, error TEXT,
                PRIMARY KEY(source_id,calendar_id)
            );
        """)
        keys = [row[1] for row in self.db.execute('PRAGMA table_info(fact_replacements)') if row[5]]
        if keys == ['old_source_id']:
            self.db.executescript('''
                ALTER TABLE fact_replacements RENAME TO previous_fact_replacements;
                CREATE TABLE fact_replacements (old_source_id TEXT NOT NULL, new_source_id TEXT NOT NULL, PRIMARY KEY(old_source_id,new_source_id));
                INSERT INTO fact_replacements SELECT * FROM previous_fact_replacements;
                DROP TABLE previous_fact_replacements;
            ''')
        # A process may stop during extraction. Re-run idempotent ingest, retaining job IDs.
        self.db.execute("UPDATE inbox SET status='pending' WHERE status IN ('processing','downloading')")
        # Delivery might have succeeded immediately before a crash; don't blindly resend.
        self.db.execute("UPDATE outbox SET status='uncertain', error='Interrupted during send; verify delivery before retrying.' WHERE status='sending'")
        # Calendar event IDs are deterministic; adapter reads before any write.
        self.db.execute("UPDATE calendar_jobs SET status='pending' WHERE status='syncing'")
        self.db.commit()

    def close(self):
        self.db.close()

    def enqueue(self, event: IncomingMessage, context: dict, *, status='pending') -> bool:
        sid = hashlib.sha256(event.source_key.encode()).hexdigest()[:16]
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO inbox(source_key,source_id,event,context,created,status) VALUES(?,?,?,?,?,?)",
                (event.source_key, sid, event.model_dump_json(), json.dumps(context), time.time(), status),
            )
        return bool(cur.rowcount)

    def message(self, source_key: str):
        row = self.db.execute('SELECT * FROM inbox WHERE source_key=?', (source_key,)).fetchone()
        return dict(row) if row else None

    def next_message(self):
        row = self.db.execute("SELECT * FROM inbox WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
        if row:
            with self.db:
                self.db.execute("UPDATE inbox SET status='processing',attempts=attempts+1 WHERE source_id=?", (row['source_id'],))
            return dict(row)

    def update(self, sid: str, **fields):
        allowed = {'status', 'event', 'job_id', 'next_poll', 'transcript', 'ocr_text', 'error'}
        if not fields or not set(fields) <= allowed:
            raise ValueError("Unknown inbox update")
        with self.db:
            self.db.execute("UPDATE inbox SET " + ','.join(f'{key}=?' for key in fields) + " WHERE source_id=?", [*fields.values(), sid])

    def due_job(self):
        row = self.db.execute("SELECT * FROM inbox WHERE status='waiting_ocr' AND next_poll<=? ORDER BY next_poll LIMIT 1", (time.time(),)).fetchone()
        return dict(row) if row else None

    def save_fact(self, sid: str, context: dict, extraction: Extraction, event: IncomingMessage):
        provenance = {
            'source_id': sid, 'sender': context['name'], 'chat_id': event.chat_id,
            'message_id': event.message_id, 'timestamp': event.timestamp.isoformat(),
            'text': event.text, 'media_path': event.media.local_path if event.media else None,
        }
        with self.db:
            self.db.execute("""INSERT INTO facts VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET extraction=excluded.extraction,provenance=excluded.provenance""",
                (sid, context['class_id'], None, extraction.student_id, extraction.model_dump_json(), json.dumps(provenance), time.time()))

    def class_facts(self, class_id: str) -> list[dict]:
        return [self._fact(row) for row in self.db.execute(
            "SELECT * FROM facts WHERE class_id=? AND owner_id IS NULL AND source_id NOT IN (SELECT old_source_id FROM fact_replacements) ORDER BY created DESC LIMIT 100", (class_id,))]

    @staticmethod
    def _fact(row):
        return {'source_id': row['source_id'], 'class_id': row['class_id'],
                'extraction': json.loads(row['extraction']), 'source': json.loads(row['provenance'])}

    @staticmethod
    def _parent_source(source):
        # One teacher message can contain facts for different children. Keep
        # the full source locally, but never send its unfiltered body to a parent.
        result = {key: source[key] for key in ('source_id', 'sender', 'timestamp', 'message_id') if key in source}
        if source.get('document'):
            result['document'] = source['document']
        if source.get('calendar'):
            result['calendar'] = source['calendar']
        if source.get('previous_sources'):
            result['previous_sources'] = [Store._parent_source(previous) for previous in source['previous_sources']]
        return result

    def history(self, event: IncomingMessage, person_id: str, limit=8) -> list[dict]:
        history = []
        for row in self.db.execute("SELECT * FROM inbox WHERE status='done' ORDER BY created DESC LIMIT 80"):
            previous = IncomingMessage.model_validate_json(row['event'])
            if (previous.session != event.session or previous.chat_id != event.chat_id
                    or previous.source_key == event.source_key or previous.timestamp > event.timestamp
                    or json.loads(row['context']).get('id') != person_id):
                continue
            replies = [r[0] for r in self.db.execute("SELECT text FROM outbox WHERE dedupe_key LIKE ? AND status IN ('sent','fixture') ORDER BY id", (row['source_id'] + ':%',))]
            history.append({'timestamp': previous.timestamp.isoformat(), 'message': row['transcript'] or previous.text,
                            'reply': '\n'.join(replies)})
            if len(history) >= limit:
                break
        return list(reversed(history))

    def applied_decision(self, source_key):
        row = self.db.execute('SELECT decision FROM applied_decisions WHERE source_key=?', (source_key,)).fetchone()
        return row[0] if row else None

    def document(self, source_key):
        row = self.db.execute('SELECT metadata FROM documents WHERE source_key=?', (source_key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_document(self, source_key, source_ids, metadata):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO documents VALUES(?,?)', (source_key, json.dumps(metadata)))
            for sid in source_ids:
                row = self.db.execute('SELECT provenance FROM facts WHERE source_id=?', (sid,)).fetchone()
                if row:
                    source = json.loads(row[0])
                    source['document'] = metadata
                    self.db.execute('UPDATE facts SET provenance=? WHERE source_id=?', (json.dumps(source), sid))

    def save_decision(self, records: list[tuple[str, Extraction]], context: dict, event: IncomingMessage, decision):
        """Write a validated set atomically, retaining old source records."""
        original = self.message(event.source_key) or {}
        with self.db:
            for sid, record in records:
                previous = [self._fact(row) for target in record.replaces_source_ids
                            if (row := self.db.execute('SELECT * FROM facts WHERE source_id=?', (target,)).fetchone())]
                source = {'source_id': sid, 'sender': context['name'], 'chat_id': event.chat_id,
                          'message_id': event.message_id, 'timestamp': event.timestamp.isoformat(),
                          'text': event.text, 'transcript': original.get('transcript'),
                          'media_path': event.media.local_path if event.media else None,
                          'previous_sources': [f['source'] for f in previous]}
                self.db.execute('INSERT OR REPLACE INTO facts VALUES(?,?,?,?,?,?,?)',
                                (sid, context['class_id'], None, record.student_id,
                                 record.model_dump_json(), json.dumps(source), time.time()))
                for target in record.replaces_source_ids:
                    self.db.execute('INSERT INTO fact_replacements VALUES(?,?)', (target, sid))
                    self.db.execute("UPDATE reminders SET status='cancelled' WHERE source_id=? AND status='pending'", (target,))
                    # A queued reminder must also stop if its record is replaced.
                    self.db.execute("UPDATE outbox SET status='cancelled' WHERE dedupe_key LIKE ? AND status='pending'", ('reminder:' + target + ':%',))
                    self.db.execute("UPDATE outbox SET status='cancelled' WHERE dedupe_key LIKE ? AND status='pending'", (target + ':calendar:%',))
            self.db.execute('INSERT INTO applied_decisions VALUES(?,?)', (event.source_key, decision.model_dump_json()))

    def schedule_reminder(self, source_id, parent_id, chat_id, due_at):
        key = f'{source_id}:{parent_id}'
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO reminders(id,source_id,parent_id,chat_id,due_at) VALUES(?,?,?,?,?)',
                            (key, source_id, parent_id, chat_id, due_at))

    def queue_calendar(self, source_id, calendar_id, operation):
        with self.db:
            self.db.execute('''INSERT INTO calendar_jobs(source_id,calendar_id,operation) VALUES(?,?,?)
                ON CONFLICT(source_id,calendar_id) DO UPDATE SET operation=excluded.operation,
                status='pending',attempts=0,next_attempt=0,metadata=NULL,error=NULL
                WHERE calendar_jobs.operation != excluded.operation''', (source_id, calendar_id, operation))

    def calendar_result(self, source_id, calendar_id, metadata):
        with self.db:
            self.db.execute("UPDATE calendar_jobs SET status='done',metadata=?,error=NULL WHERE source_id=? AND calendar_id=?",
                            (json.dumps(metadata), source_id, calendar_id))
            row = self.db.execute('SELECT provenance FROM facts WHERE source_id=?', (source_id,)).fetchone()
            if row:
                source = json.loads(row[0])
                source['calendar'] = metadata
                self.db.execute('UPDATE facts SET provenance=? WHERE source_id=?', (json.dumps(source), source_id))

    def due_reminder(self, now):
        row = self.db.execute("SELECT * FROM reminders WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT 1", (now,)).fetchone()
        return dict(row) if row else None

    def finish_reminder(self, identifier, status):
        with self.db:
            self.db.execute('UPDATE reminders SET status=? WHERE id=?', (status, identifier))

    def facts_for(self, parent: dict, students: list[dict]) -> list[dict]:
        classes = {student['class_id'] for student in students} if students else set(parent.get('classes', []))
        student_ids = {student['id'] for student in students}
        results = []
        # Tiny demo data set; filtering still happens before any facts reach Sarvam.
        for row in self.db.execute("SELECT * FROM facts WHERE source_id NOT IN (SELECT old_source_id FROM fact_replacements) ORDER BY created DESC LIMIT 200"):
            if parent.get('class_wide_only') and (row['owner_id'] is not None or row['student_id'] is not None):
                continue
            shared = row['owner_id'] is None and row['class_id'] in classes and (row['student_id'] is None or row['student_id'] in student_ids)
            private = row['owner_id'] == parent['id'] and (row['student_id'] is None or row['student_id'] in student_ids)
            if shared or private:
                fact = self._fact(row)
                fact['source'] = self._parent_source(fact['source'])
                results.append(fact)
        return results

    def reply(self, key: str, chat: str, text: str, *, kind='text', path: str | None = None):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO outbox(dedupe_key,chat_id,text,kind,path) VALUES(?,?,?,?,?)", (key, chat, text, kind, path))

    def next_reply(self):
        row = self.db.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        return dict(row) if row else None

    def delivery(self, reply_id: int, status: str, remote_id=None, error=None):
        with self.db:
            self.db.execute("UPDATE outbox SET status=?,remote_id=?,error=?,attempts=attempts+? WHERE id=?", (status, remote_id, error, int(status == 'sending'), reply_id))

    def replies(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM outbox ORDER BY id")]

    def counts(self) -> dict:
        return {table: self.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('inbox', 'facts', 'outbox')}

