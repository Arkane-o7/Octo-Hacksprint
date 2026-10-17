from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from .contracts import Extraction, IncomingMessage, NoticeDecision
from .storage import Store
from .sarvam import SarvamError

logger = logging.getLogger(__name__)
OFFLINE = "[OFFLINE DEMO — synthetic fixture responses; no live delivery]\n"


class Roster:
    def __init__(self, path: Path, *, live=False):
        self.data = json.loads(path.read_text())
        self.students = {s['id']: s for s in self.data['students']}
        self.identities = {}
        for role, entries in [('teacher', self.data['teachers']), ('parent', self.data['parents'])]:
            for entry in entries:
                for wid in entry['whatsapp_ids']:
                    if wid in self.identities:
                        raise ValueError('WhatsApp ID assigned to multiple roster identities')
                    if live and (wid.startswith('demo-') or '@' not in wid):
                        raise ValueError('Live mode requires real designated WhatsApp IDs in roster.local.json')
                    self.identities[wid] = {**entry, 'role': role}
        if live and any(g.startswith('demo-') for g in self.data['groups']):
            raise ValueError('Live mode requires a designated test-group ID')
        # Explicit demo-only role mapping: the same verified teacher stays a
        # teacher in the group and can play one fictional parent in direct chat.
        # Never select this role from message text or a display name.
        self.demo_parents = {}
        parents = {p['id']: p for p in self.data['parents']}
        for teacher in self.data['teachers']:
            target = teacher.get('demo_parent_id')
            if not target:
                continue
            if target not in parents or target in self.demo_parents.values():
                raise ValueError('Each demo teacher must map to a distinct existing parent')
            parent = parents[target]
            if parent['whatsapp_ids']:
                raise ValueError('Remove the teacher demo mapping when configuring the real parent')
            self.demo_parents[teacher['id']] = target
            parent['whatsapp_ids'] = list(teacher['whatsapp_ids'])

    def resolve(self, event: IncomingMessage) -> dict | None:
        matches = [self.identities[x] for x in [event.sender_id, *event.sender_aliases] if x in self.identities]
        if not matches or len({x['id'] for x in matches}) != 1:
            return None
        person = dict(matches[0])
        if event.is_group:
            class_id = self.data['groups'].get(event.chat_id)
            if person['role'] != 'teacher' or class_id not in person['classes']:
                return None
            person['class_id'] = class_id
        elif person['role'] != 'parent':
            target = self.demo_parents.get(person['id'])
            if not target:
                return None
            person = dict(next(p for p in self.data['parents'] if p['id'] == target))
            person['role'] = 'parent'
        return person

    def permitted_students(self, parent: dict) -> list[dict]:
        return [self.students[s] for s in parent['student_ids']]

    def mentions_other_student(self, text: str, parent: dict) -> bool:
        for student in self.students.values():
            if student['id'] in parent['student_ids']:
                continue
            for name in [student['name'], *student.get('aliases', [])]:
                if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.IGNORECASE):
                    return True
        return False

    def names_student(self, text: str) -> bool:
        return any(re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I)
                   for student in self.students.values()
                   for name in [student['name'], *student.get('aliases', [])])


class Octo:
    def __init__(self, settings: Settings, store: Store, roster: Roster, ai, transport, *, drive=None, calendar=None):
        self.settings, self.store, self.roster = settings, store, roster
        self.ai, self.transport = ai, transport
        self.drive = drive
        self.calendar = calendar
        self.media_dir = settings.data_dir / 'media'
        self.media_dir.mkdir(parents=True, exist_ok=True)

    @property
    def general_brain(self):
        return self.settings.general_brain and hasattr(self.ai, 'understand')

    def accept(self, event: IncomingMessage) -> str:
        if event.session != self.settings.waha_session:
            return 'ignored'
        caller = self.roster.resolve(event)
        if not caller:
            return 'ignored'
        return 'queued' if self.store.enqueue(event, caller) else 'duplicate'

    async def ingest(self, event: IncomingMessage) -> str:
        """Copy short-lived WAHA media at ingress, before slow model work."""
        if event.session != self.settings.waha_session:
            return 'ignored'
        caller = self.roster.resolve(event)
        if not caller:
            return 'ignored'
        if not event.media:
            return self.accept(event)
        if not self.store.enqueue(event, caller, status='downloading'):
            return 'duplicate'
        row = self.store.message(event.source_key)
        try:
            await self._media(row['source_id'], event)
            self.store.update(row['source_id'], status='pending')
        except Exception as exc:
            await self.fail(row, event, exc)
        return 'queued'

    def reply(self, sid: str, event: IncomingMessage, text: str, suffix='answer'):
        if self.settings.mode == 'offline':
            text = OFFLINE + text
        self.store.reply(f'{sid}:{suffix}', event.chat_id, text)

    async def _media(self, sid: str, event: IncomingMessage) -> Path:
        if not event.media:
            raise ValueError('This message has no downloadable media. Please resend it.')
        if event.media.local_path:
            path = Path(event.media.local_path).resolve()
            if not path.is_relative_to(self.settings.data_dir.resolve()) or not path.is_file():
                raise ValueError('Saved media is unavailable. Please resend it.')
            return path
        mime = event.media.mime_type.split(';')[0].strip().lower()
        suffix = {'image/jpeg': '.jpg', 'image/png': '.png', 'audio/ogg': '.ogg',
                  'audio/opus': '.ogg'}.get(mime) or mimetypes.guess_extension(mime) or '.bin'
        destination = self.media_dir / (sid + suffix)
        path = await self.transport.download_media(event.media, destination)
        event.media.local_path = str(path.resolve())
        self.store.update(sid, event=event.model_dump_json())
        return path

    async def process(self, row: dict):
        sid = row['source_id']
        event = IncomingMessage.model_validate_json(row['event'])
        # Re-resolve on processing/restart: a changed roster cannot retain old access.
        caller = self.roster.resolve(event)
        if not caller:
            self.store.update(sid, status='ignored')
            return
        try:
            text = row.get('transcript') or event.text
            if event.kind == 'voice' and not row.get('transcript'):
                path = await self._media(sid, event)
                names = ([s['name'] for s in self.roster.permitted_students(caller)]
                         if caller['role'] == 'parent' else [s['name'] for s in self.roster.students.values() if s['class_id'] in caller['classes']])
                transcript = await self.ai.transcribe(path, names)
                text = transcript.text
                if not text.strip():
                    raise ValueError('I could not hear the message. Please send a clearer short voice note.')
                self.store.update(sid, transcript=text)

            if caller['role'] == 'teacher':
                if event.forwarded:
                    self.reply(sid, event, 'Please confirm this forwarded notice in a fresh class message with the relevant date. I have not changed the class records.')
                elif event.kind in ('image', 'document'):
                    path = await self._media(sid, event)
                    if event.kind == 'document' and (path.suffix.lower() != '.pdf' or not path.read_bytes().startswith(b'%PDF-')):
                        raise ValueError('Please send a PDF document, or a JPEG/PNG board photo.')
                    self.reply(sid, event, 'Reading the PDF…' if event.kind == 'document' else 'Reading the photo…', 'ack')
                    # Keep the acknowledgement ahead of a potentially slow submission.
                    await self.deliver_one()
                    job_id = row.get('job_id') or await self.ai.submit_document(path)
                    self.store.update(sid, status='waiting_ocr', job_id=job_id, next_poll=time.time() + self.settings.poll_seconds)
                    return
                elif event.kind in ('text', 'voice'):
                    if self.general_brain:
                        await self._understand(sid, event, caller, text)
                    elif self.roster.names_student(text):
                        self.reply(sid, event, 'This demo saves class-wide notices only. Please send a class-wide requirement without individual student details.')
                    else:
                        result = await self.ai.extract_notice(text, event.timestamp, caller['class_id'])
                        await self._save_extraction(sid, event, caller, result)
                else:
                    self.reply(sid, event, 'Please send text, a short voice note, a board photo or a PDF.')
            else:
                if event.kind in ('image', 'document'):
                    self.reply(sid, event, 'Please ask the teacher to post the syllabus photo in the demo class group. You can ask me about saved school information here.')
                else:
                    await self._answer(sid, event, caller, text)
            self.store.update(sid, status='done')
        except Exception as exc:
            await self.fail(row, event, exc)

    async def fail(self, row: dict, event: IncomingMessage, exc: Exception):
        logger.warning('Message %s failed (%s)', row['source_id'], type(exc).__name__)
        # Do not send raw provider errors, URLs, bodies or credentials to a parent.
        safe = str(exc) if isinstance(exc, (ValueError, SarvamError)) else 'The service could not finish that request. Please try again shortly.'
        if len(safe) > 250:
            safe = 'The service could not finish that request. Please try again shortly.'
        self.store.update(row['source_id'], status='failed', error=type(exc).__name__)
        self.reply(row['source_id'], event, safe, 'error')

    async def _save_extraction(self, sid: str, event: IncomingMessage, caller: dict, result: Extraction):
        if result.kind == 'unknown' or (result.kind != 'school_day' and not (result.items or result.sections)):
            if event.kind in ('image', 'document'):
                self.reply(sid, event, 'I could not identify school requirements, syllabus topics or lesson notes in this attachment. Please send the actual school notice or a clearer photo of the notes; nothing was saved.')
            else:
                self.reply(sid, event, 'I have not saved this notice. I can save supplies, syllabus topics, or a dated whole-class holiday/class-day notice. Specific lesson, test or practice changes are not supported yet.')
            return
        if result.class_as_written:
            normalize = lambda x: re.sub(r'[^a-z0-9]', '', x.lower().replace('class', '').replace('grade', ''))
            if normalize(result.class_as_written) != normalize(caller['class_id']):
                self.reply(sid, event, 'The class written in this notice differs from this group. Please confirm the correct class before I save it.')
                return
        if result.due_date:
            try:
                date.fromisoformat(result.due_date)
            except ValueError:
                result.due_date = None
                result.unclear.append('Date could not be resolved; please confirm it.')
        if not result.date_as_written and result.due_date:
            result.due_date = None
            result.unclear.append('No date was supplied in the source.')
        if result.date_as_written:
            relative = result.date_as_written.strip().lower().rstrip('.')
            if relative in ('today', 'tomorrow', 'day after tomorrow'):
                offset = {'today': 0, 'tomorrow': 1, 'day after tomorrow': 2}[relative]
                result.due_date = (event.timestamp.astimezone(ZoneInfo('Asia/Kolkata')).date() + timedelta(days=offset)).isoformat()
            else:
                # Do not depend on model date arithmetic for an explicit full
                # English date. Ambiguous numeric dates and missing years stay
                # unresolved unless the model established an unambiguous date.
                for format_string in ('%Y-%m-%d', '%d %B %Y', '%d %b %Y'):
                    try:
                        result.due_date = datetime.strptime(result.date_as_written.strip(), format_string).date().isoformat()
                        break
                    except ValueError:
                        pass
        if result.kind == 'school_day':
            if not result.school_day_status or result.subject or result.items or result.sections or result.unclear:
                self.reply(sid, event, 'I have not changed the class-day record. Please confirm whether the whole class has no classes or classes as usual, and give the date. Send any supplies or syllabus in a separate notice.')
                return
            if not result.due_date:
                self.reply(sid, event, 'Which date does this class-day notice apply to? Please resend the full notice with the date; I have not changed the class-day record.')
                return
        else:
            result.school_day_status = None
        if result.kind == 'requirement' and not result.due_date:
            result.unclear.append('When should students bring these items?')
        self.store.save_fact(sid, caller, result, event)
        self.queue_calendar_sync()
        lines = [f"Saved for Class {caller['class_id']}" + (f" — {result.subject}" if result.subject else '')]
        if self._schedule_reminders(sid, result, event.timestamp):
            lines.append('Parent reminder scheduled.')
        if result.due_date:
            lines.append(f'Date: {result.due_date}')
        if result.kind == 'school_day':
            lines.append('No classes.' if result.school_day_status == 'no_classes' else 'Classes as usual.')
        lines.extend('• ' + item for item in result.items)
        for section in result.sections:
            if section.chapter:
                lines.append(section.chapter)
            lines.extend('☐ ' + topic for topic in section.topics)
            if section.pages:
                lines.append('Pages: ' + section.pages)
        lines.extend('Instruction: ' + item for item in result.instructions)
        lines.extend('Please clarify: ' + item for item in dict.fromkeys(result.unclear))
        lines.append(f"Source: {caller['name']}, {event.timestamp.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %H:%M')} [{sid}]")
        self.reply(sid, event, '\n'.join(lines))

    async def _understand(self, sid, event, caller, text, *, ocr_text=None):
        applied = self.store.applied_decision(event.source_key)
        if applied:
            decision = NoticeDecision.model_validate_json(applied)
            self._finish_decision(sid, event, caller, decision)
            return decision
        context = self.store.class_facts(caller['class_id'])
        students = [s for s in self.roster.students.values() if s['class_id'] == caller['class_id']]
        decision = await self.ai.understand(text, event.timestamp, caller['class_id'], context,
                                           self.store.history(event, caller['id']), students, ocr_text=ocr_text)
        await self._apply_decision(sid, event, caller, decision, context, text + '\n' + (ocr_text or ''))
        return decision

    async def _apply_decision(self, sid, event, caller, decision: NoticeDecision, context, source_text):
        """The LLM proposes meaning; code owns scope, references and writes."""
        by_id = {f['source_id']: f for f in context}
        if any(ref not in by_id for ref in decision.source_ids):
            raise ValueError('I could not verify the cited school information. Please clarify the notice.')
        validated = []
        explicit_dates = set(re.findall(r'\b\d{4}-\d{2}-\d{2}\b', source_text))
        represented_dates = {r.due_date for r in decision.records}
        represented_dates.update(by_id[ref]['extraction'].get('due_date')
                                 for r in decision.records for ref in r.replaces_source_ids if ref in by_id)
        if decision.records and len(explicit_dates) > 1 and not explicit_dates <= represented_dates:
            raise ValueError('I could not keep the different dates separate. Please send each dated notice separately; nothing was changed.')
        new_ids = {sid if index == 0 else f'{sid}-{index + 1}' for index in range(len(decision.records))}
        for index, record in enumerate(decision.records):
            if not (record.summary or record.items or record.sections or record.instructions):
                raise ValueError('Please include the missing school information; nothing was saved.')
            if record.student_id:
                student = self.roster.students.get(record.student_id)
                if not student or student['class_id'] != caller['class_id']:
                    raise ValueError('That student is not in this demo class; nothing was changed.')
            if record.class_as_written:
                clean = lambda value: re.sub(r'[^a-z0-9]', '', value.lower().replace('class', '').replace('grade', ''))
                if clean(record.class_as_written) != clean(caller['class_id']):
                    raise ValueError('This notice names a different class. Please confirm the class; nothing was changed.')
            targets = record.replaces_source_ids
            if len(targets) != len(set(targets)) or any(ref not in by_id or ref in new_ids for ref in targets):
                raise ValueError('The update does not identify a unique saved notice in this class. Please clarify; nothing was changed.')
            for ref in targets:
                previous = by_id[ref]
                if previous['extraction'].get('student_id') != record.student_id:
                    raise ValueError('An update cannot change which student a notice belongs to. Please send a separate notice.')
                if datetime.fromisoformat(previous['source']['timestamp']) > event.timestamp:
                    raise ValueError('A newer notice already exists. Please confirm the latest information.')
            if len(targets) == 1:
                previous_record = Extraction.model_validate(by_id[targets[0]]['extraction'])
                siblings = [r for r in decision.records if targets[0] in r.replaces_source_ids]
                # JSON-mode proposals can omit unchanged optional fields. Treat
                # omission as preservation, not erasure of an existing syllabus.
                for field in ('subject', 'items', 'sections', 'instructions', 'school_day_status'):
                    if field not in record.model_fields_set:
                        if len(siblings) > 1 and field in ('items', 'sections', 'instructions') and getattr(previous_record, field):
                            raise ValueError('Please spell out the cancelled and remaining items/topics separately; nothing was changed.')
                        setattr(record, field, getattr(previous_record.model_copy(deep=True), field))
                if previous_record.sections and not record.sections and not any(r.sections for r in siblings):
                    raise ValueError('This update would remove the saved syllabus. Please include the intended topics; nothing was changed.')
            if record.status in ('cancelled', 'completed') and not targets:
                raise ValueError('Which saved activity or requirement does this change apply to? Please include its name and date.')
            if targets and record.unclear:
                raise ValueError('Please clarify this change before I update the saved record: ' + '; '.join(record.unclear)[:130])
            if record.due_date:
                try:
                    date.fromisoformat(record.due_date)
                except ValueError:
                    raise ValueError('The date is unclear. Please give an explicit date; nothing was changed.') from None
            proposed_date = record.due_date
            written = (record.date_as_written or '').strip()
            if targets and not record.date_changed:
                inherited = {by_id[ref]['extraction'].get('due_date') for ref in targets}
                if len(inherited) != 1:
                    raise ValueError('These saved notices have different dates. Please clarify which date applies.')
                record.due_date = next(iter(inherited))
            elif not written:
                inherited = {by_id[ref]['extraction'].get('due_date') for ref in targets}
                record.due_date = next(iter(inherited)) if len(inherited) == 1 else None
            elif written.casefold().rstrip('.') in ('today', 'tomorrow', 'day after tomorrow'):
                # Only apply current-message date arithmetic to words in this
                # source; follow-up corrections may inherit an older date.
                if written.casefold().rstrip('.') in source_text.casefold():
                    days = {'today': 0, 'tomorrow': 1, 'day after tomorrow': 2}[written.casefold().rstrip('.')]
                    record.due_date = (event.timestamp.astimezone(ZoneInfo('Asia/Kolkata')).date() + timedelta(days=days)).isoformat()
                elif not targets:
                    record.due_date = None
            else:
                for pattern in ('%Y-%m-%d', '%d %B %Y', '%d %b %Y'):
                    try:
                        record.due_date = datetime.strptime(written, pattern).date().isoformat()
                        break
                    except ValueError:
                        pass
            if targets and record.date_changed and (not written or not proposed_date or proposed_date != record.due_date):
                raise ValueError('The new date is inconsistent. Please confirm the event and its new date; nothing was changed.')
            if record.status != 'active' and not record.due_date:
                raise ValueError('Please confirm the date of the activity being changed; nothing was changed.')
            validated.append((sid if index == 0 else f'{sid}-{index + 1}', record))
        self.store.save_decision(validated, caller, event, decision)
        self._finish_decision(sid, event, caller, decision)

    def _finish_decision(self, sid, event, caller, decision):
        self.queue_calendar_sync()
        validated = [(sid if index == 0 else f'{sid}-{index + 1}', record) for index, record in enumerate(decision.records)]
        if validated:
            lines = [f"Saved for Class {caller['class_id']}"]
            for source_id, record in validated:
                if record.summary:
                    lines.append(record.summary)
                if record.status != 'active':
                    lines.append('Status: ' + record.status)
                if record.due_date:
                    lines.append('Date: ' + record.due_date)
                lines.extend('• ' + item for item in record.items)
                for section in record.sections:
                    if section.chapter:
                        lines.append(section.chapter)
                    lines.extend('☐ ' + topic for topic in section.topics)
                    if section.pages:
                        lines.append('Pages: ' + section.pages)
                lines.extend('Instruction: ' + instruction for instruction in record.instructions)
                lines.extend('Please clarify: ' + unclear for unclear in record.unclear)
                if self._schedule_reminders(source_id, record, event.timestamp):
                    lines.append('Parent reminder scheduled.')
                lines.append(f"Source: {caller['name']}, {event.timestamp.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %H:%M')} [{source_id}]")
            if decision.reply:
                lines.append(decision.reply)
            self.reply(sid, event, '\n'.join(lines))
        elif decision.reply:
            reply = decision.reply
            if decision.source_ids:
                reply += '\nSources: ' + ', '.join(f'[{ref}]' for ref in decision.source_ids)
            self.reply(sid, event, reply)

    def queue_calendar_sync(self):
        """Reconcile small structured demo state, never raw source instructions."""
        if self.settings.mode != 'live' or not self.calendar or not self.calendar.configured:
            return
        today = datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
        replaced = {r[0] for r in self.store.db.execute('SELECT old_source_id FROM fact_replacements')}
        allowed_classes = set(self.roster.data['groups'].values())
        for row in self.store.db.execute('SELECT * FROM facts'):
            # This is a shared demo-school calendar, not a private student feed.
            if row['owner_id'] or row['student_id'] or row['class_id'] not in allowed_classes:
                continue
            record = json.loads(row['extraction'])
            operation = 'delete' if row['source_id'] in replaced or record.get('status', 'active') != 'active' else 'upsert'
            if operation == 'upsert' and (not record.get('due_date') or record['due_date'] < today or record.get('unclear')):
                continue
            self.store.queue_calendar(row['source_id'], self.settings.calendar_id, operation)

    async def calendar_one(self):
        if self.settings.mode != 'live' or not self.calendar or not self.calendar.configured:
            return False
        jobs = self.store.db.execute("""SELECT * FROM calendar_jobs WHERE calendar_id=?
            AND status='pending' AND next_attempt<=? ORDER BY operation='delete' DESC,source_id""",
            (self.settings.calendar_id, time.time())).fetchall()
        for job in jobs:
            source = self.store.db.execute('SELECT * FROM facts WHERE source_id=?', (job['source_id'],)).fetchone()
            if not source or source['owner_id'] or source['student_id'] or source['class_id'] not in self.roster.data['groups'].values():
                self.store.calendar_result(job['source_id'], job['calendar_id'], {'status': 'skipped'})
                return True
            fact = self.store._fact(source)
            operation = job['operation']
            # A replacement can arrive while an older create is still queued.
            replaced = self.store.db.execute('SELECT 1 FROM fact_replacements WHERE old_source_id=?', (job['source_id'],)).fetchone()
            if replaced or fact['extraction'].get('status', 'active') != 'active':
                operation = 'delete'
            if operation == 'upsert':
                old_ids = fact['extraction'].get('replaces_source_ids', [])
                pending_old = any(self.store.db.execute("SELECT 1 FROM calendar_jobs WHERE source_id=? AND calendar_id=? AND status!='done'",
                    (old, job['calendar_id'])).fetchone() for old in old_ids)
                if pending_old:
                    continue  # Remove the obsolete entry before creating its replacement.
                today = datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
                if not fact['extraction'].get('due_date') or fact['extraction']['due_date'] < today or fact['extraction'].get('unclear'):
                    self.store.calendar_result(job['source_id'], job['calendar_id'], {'status': 'skipped'})
                    return True
            with self.store.db:
                self.store.db.execute("UPDATE calendar_jobs SET status='syncing',attempts=attempts+1 WHERE source_id=? AND calendar_id=?", (job['source_id'],job['calendar_id']))
            try:
                result = await self.calendar.delete_fact(job['source_id']) if operation == 'delete' else await self.calendar.sync_fact(fact)
                self.store.calendar_result(job['source_id'], job['calendar_id'], result)
                if result.get('url') and result.get('status') == 'synced':
                    chat = fact['source'].get('chat_id')
                    if chat in self.roster.data['groups']:
                        self.store.reply(f"{job['source_id']}:calendar:{job['calendar_id']}", chat,
                            'Added to the demo Google Calendar (all-day): ' + result['url'])
            except Exception:
                attempts = job['attempts'] + 1
                with self.store.db:
                    self.store.db.execute("UPDATE calendar_jobs SET status=?,next_attempt=?,error=? WHERE source_id=? AND calendar_id=?",
                        ('failed' if attempts >= 3 else 'pending', time.time() + 30 * attempts,
                         'Calendar sync unconfirmed; check OAuth and the demo calendar.', job['source_id'],job['calendar_id']))
                if attempts >= 3 and fact['source'].get('chat_id') in self.roster.data['groups']:
                    self.store.reply(f"{job['source_id']}:calendar-error:{job['calendar_id']}", fact['source']['chat_id'],
                        'The school record is saved, but Google Calendar synchronization is unconfirmed. Check the demo calendar and OAuth setup.')
            return True
        return False

    def _schedule_reminders(self, source_id, record, message_time):
        if self.settings.mode != 'live' or record.status != 'active' or not record.due_date or record.kind == 'school_day':
            return 0
        due = date.fromisoformat(record.due_date)
        hour, minute = [int(part) for part in self.settings.reminder_time.split(':')]
        reminder = datetime.combine(due - timedelta(days=1), datetime.min.time(), ZoneInfo('Asia/Kolkata')).replace(hour=hour, minute=minute)
        if reminder <= message_time:
            reminder = datetime.combine(due, datetime.min.time(), ZoneInfo('Asia/Kolkata')).replace(hour=7)
        if reminder <= message_time:
            return 0
        fact = self.store.db.execute('SELECT class_id FROM facts WHERE source_id=?', (source_id,)).fetchone()
        count = 0
        for parent in self.roster.data['parents']:
            students = self.roster.permitted_students(parent)
            if not parent['whatsapp_ids'] or not any(s['class_id'] == fact['class_id'] and (record.student_id is None or s['id'] == record.student_id) for s in students):
                continue
            self.store.schedule_reminder(source_id, parent['id'], parent['whatsapp_ids'][0], reminder.timestamp())
            count += 1
        return count

    async def remind_one(self):
        row = self.store.due_reminder(time.time())
        if not row:
            return False
        parent = next((p for p in self.roster.data['parents'] if p['id'] == row['parent_id'] and row['chat_id'] in p['whatsapp_ids']), None)
        if not parent:
            self.store.finish_reminder(row['id'], 'cancelled')
            return True
        facts = self.store.facts_for(parent, self.roster.permitted_students(parent))
        fact = next((f for f in facts if f['source_id'] == row['source_id']), None)
        if not fact or fact['extraction'].get('status', 'active') != 'active':
            self.store.finish_reminder(row['id'], 'cancelled')
            return True
        record = fact['extraction']
        if not record.get('due_date') or record['due_date'] < datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat():
            self.store.finish_reminder(row['id'], 'cancelled')
            return True
        # Send the saved requirement as a reminder, not a fresh assertion that
        # a conflicting school-day notice has been resolved.
        lines = ['Reminder for ' + str(record.get('due_date')), record.get('summary') or 'Saved school notice:']
        lines.extend('• ' + item for item in record.get('items', []))
        for section in record.get('sections', []):
            if section.get('chapter'):
                lines.append(section['chapter'])
            lines.extend('☐ ' + topic for topic in section.get('topics', []))
        lines.extend('Instruction: ' + item for item in record.get('instructions', []))
        if any(f['class_id'] == fact['class_id'] and f['extraction'].get('due_date') == record.get('due_date') and f['extraction'].get('school_day_status') == 'no_classes' for f in facts):
            lines.append('A no-classes notice also exists for this date. Please confirm with the teacher when these supplies are needed.')
        lines.append('Source: [' + fact['source_id'] + ']')
        self.store.reply('reminder:' + row['id'], row['chat_id'], '\n'.join(lines))
        self.store.finish_reminder(row['id'], 'queued')
        return True

    async def _answer(self, sid: str, event: IncomingMessage, parent: dict, text: str):
        if re.match(r'^\s*(APPROVE|CHANGE|CANCEL)\b', text, re.I):
            from .cart import CartService
            result = CartService(self.store.db).handle(parent['id'], event.chat_id, text,
                is_fresh_text=event.kind == 'text' and not event.forwarded and not event.quoted_message_id and not event.is_quoted)
            if result is not None:
                self.reply(sid, event, result, 'cart-action')
                return
        if self.roster.mentions_other_student(text, parent):
            self.reply(sid, event, 'I can only answer about students linked to your demo parent account.')
            return
        students = self.roster.permitted_students(parent)
        named = [student for student in students if any(
            re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I)
            for name in [student['name'], *student.get('aliases', [])])]
        if named:
            students = named
        elif len(students) > 1:
            self.reply(sid, event, 'Which student do you mean: ' + ', '.join(s['name'] for s in students) + '? Please include the name in your question.')
            return
        facts = self.store.facts_for(parent, students)
        if not facts:
            self.reply(sid, event, 'I do not have saved school information for your students yet. Ask the teacher to post a notice in the demo group.')
            return
        question = f"Current date in Asia/Kolkata: {event.timestamp.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()}\nParent question: {text}"
        answer = await self.ai.answer(question, facts, [s['name'] for s in students], parent['language'])
        by_id = {f['source_id']: f for f in facts}
        if not answer.source_ids or any(s not in by_id for s in answer.source_ids):
            self.reply(sid, event, 'I could not verify an answer against the saved notices. Please ask again or ask the teacher to clarify.')
            return
        citations = []
        for source_id in dict.fromkeys(answer.source_ids):
            source = by_id[source_id]['source']
            citations.append(f"{source['sender']}, {source['timestamp']} [{source_id}]")
            document = source.get('document') or {}
            if document.get('url'):
                citations.append('Document: ' + document['url'])
            calendar = source.get('calendar') or {}
            if calendar.get('status') == 'synced' and calendar.get('url'):
                citations.append('Calendar: ' + calendar['url'])
        self.reply(sid, event, answer.text + '\n\nSources:\n' + '\n'.join(citations))
        if answer.proposed_items and answer.cart_request_quote and answer.cart_request_quote.casefold() in text.casefold():
            from .cart import CartService
            self.reply(sid, event, CartService(self.store.db).propose(parent['id'], event.chat_id, answer.proposed_items), 'cart')
        # Text delivery is independent of TTS failure/latency.
        await self.deliver_one()
        if parent.get('voice_replies') or event.kind == 'voice':
            if self.settings.mode == 'offline':
                self.reply(sid, event, 'Audio is skipped in offline mode; no Sarvam speech was generated.', 'audio-status')
                return
            try:
                speech = answer.spoken_text or answer.text
                path = await self.ai.synthesize(speech, parent['language'], self.media_dir / f'{sid}-answer.mp3')
                self.store.reply(f'{sid}:audio', event.chat_id, '', kind='voice', path=str(path))
            except Exception:
                self.reply(sid, event, 'The written answer is ready, but audio is unavailable right now.', 'audio-status')

    async def poll_job(self, row: dict):
        sid = row['source_id']
        event = IncomingMessage.model_validate_json(row['event'])
        caller = self.roster.resolve(event)
        if not caller or caller['role'] != 'teacher':
            self.store.update(sid, status='ignored')
            return
        try:
            status = await self.ai.document_status(row['job_id'])
            if status in ('pending', 'running', 'processing', 'queued'):
                self.store.update(sid, next_poll=time.time() + self.settings.poll_seconds)
                if time.time() - row['created'] > 60:
                    self.reply(sid, event, 'The syllabus photo is still processing. I will send the result when it is ready.', 'processing')
                if time.time() - row['created'] > 900:
                    raise ValueError('The document service is taking too long. The photo is retained; please retry later.')
                return
            if status in ('failed', 'rejected'):
                raise ValueError('The document service could not process this photo. Please try again or send a clearer photo.')
            if status not in ('completed', 'partially_completed'):
                raise ValueError('The document service returned an unexpected status. Please retry later.')
            ocr = await self.ai.document_text(row['job_id'])
            self.store.update(sid, ocr_text=ocr)
            if not self.general_brain and self.roster.names_student(ocr + '\n' + event.text):
                self.reply(sid, event, 'This photo contains an individual student name. This demo saves class-wide syllabus notices only; please send a class-wide notice without individual details.')
                self.store.update(sid, status='done')
                return
            if self.general_brain:
                if status == 'partially_completed':
                    ocr += '\n[Only part of the image was processed. Missing content must stay unresolved.]'
                decision = await self._understand(sid, event, caller, event.text, ocr_text=ocr)
                if event.kind == 'document':
                    await self._file_pdf(sid, event, decision)
                self.store.update(sid, status='done')
                return
            result = await self.ai.extract_syllabus(ocr, event.text, event.timestamp, caller['class_id'])
            if status == 'partially_completed':
                result.unclear.append('Only part of the source image was processed. This checklist is incomplete.')
            await self._save_extraction(sid, event, caller, result)
            if event.kind == 'document' and self.store.db.execute('SELECT 1 FROM facts WHERE source_id=?', (sid,)).fetchone():
                await self._file_pdf(sid, event, NoticeDecision(records=[result]))
            self.store.update(sid, status='done')
        except Exception as exc:
            await self.fail(row, event, exc)

    async def _file_pdf(self, sid, event, decision):
        """Only clear class-wide notes can enter the explicitly configured folder."""
        from .drive import DriveError, NOT_CONFIGURED
        source_ids = [sid if i == 0 else f'{sid}-{i+1}' for i in range(len(decision.records))]
        saved = self.store.document(event.source_key)
        if saved:
            self.reply(sid, event, saved['message'], 'document')
            return
        subjects = {r.subject for r in decision.records if r.subject}
        chapters = {s.chapter for r in decision.records for s in r.sections if s.chapter}
        metadata = {'filename': event.media.filename, 'status': 'local', 'url': None}
        if not decision.records or len(subjects) != 1 or len(chapters) > 1 or any(r.student_id or r.unclear for r in decision.records):
            metadata['message'] = 'The PDF is retained locally; no Drive link was created. Please resend it with one subject/chapter and confirm these are class-wide notes before Drive filing.'
        elif self.settings.mode != 'live' or not self.drive or not self.drive.configured:
            metadata['message'] = NOT_CONFIGURED + ' After setup, resend the PDF to file it.'
        else:
            # Persist intent before a network write. An interrupted upload is not
            # blindly retried; operator checks Drive before a manual retry.
            metadata['status'] = 'uploading'
            metadata['message'] = 'Drive upload was interrupted or remains unconfirmed. The PDF is retained locally; check Drive before retrying.'
            self.store.save_document(event.source_key, source_ids, metadata)
            try:
                result = await self.drive.file_pdf(Path(event.media.local_path), next(iter(subjects)), next(iter(chapters), None))
                metadata.update(status='uploaded', url=result['url'], drive_id=result['id'],
                                message='Filed in Google Drive: ' + result['url'] + '\nThe link uses the demo folder’s existing permissions.')
            except DriveError as exc:
                metadata.update(status='unconfirmed', message=str(exc))
        self.store.save_document(event.source_key, source_ids, metadata)
        self.reply(sid, event, metadata['message'], 'document')

    async def deliver_one(self):
        reply = self.store.next_reply()
        if not reply:
            return False
        if not self._delivery_allowed(reply):
            self.store.delivery(reply['id'], 'cancelled', error='Recipient access changed or reminder is no longer current.')
            return True
        self.store.delivery(reply['id'], 'sending')
        try:
            if reply['kind'] == 'voice':
                remote = await self.transport.send_voice(reply['chat_id'], Path(reply['path']))
            else:
                remote = await self.transport.send_text(reply['chat_id'], reply['text'])
            if self.settings.mode == 'live' and not remote:
                raise ValueError('WhatsApp did not return a message ID.')
            self.store.delivery(reply['id'], 'fixture' if self.settings.mode == 'offline' else 'sent', remote_id=remote)
        except Exception:
            self.store.delivery(reply['id'], 'uncertain', error='Delivery was not confirmed; check WhatsApp before resending.')
            if reply['kind'] == 'voice':
                self.store.reply(reply['dedupe_key'] + ':delivery-status', reply['chat_id'],
                                 'The written answer is ready, but audio delivery was not confirmed. Please check the chat before retrying.')
        return True

    def _delivery_allowed(self, reply):
        # Re-check at send time too: a queued response can outlive a roster edit.
        if ':calendar:' in reply['dedupe_key']:
            source_id, calendar_id = reply['dedupe_key'].split(':calendar:', 1)
            if calendar_id != self.settings.calendar_id or self.store.db.execute('SELECT 1 FROM fact_replacements WHERE old_source_id=?', (source_id,)).fetchone():
                return False
            source = self.store.db.execute('SELECT provenance FROM facts WHERE source_id=?', (source_id,)).fetchone()
            if not source or json.loads(source[0]).get('calendar', {}).get('status') != 'synced':
                return False
        if reply['dedupe_key'].startswith('reminder:'):
            key = reply['dedupe_key'].removeprefix('reminder:')
            row = self.store.db.execute('SELECT * FROM reminders WHERE id=?', (key,)).fetchone()
            if not row or row['status'] == 'cancelled':
                return False
            parent = next((p for p in self.roster.data['parents'] if p['id'] == row['parent_id'] and reply['chat_id'] in p['whatsapp_ids']), None)
            if not parent:
                return False
            facts = self.store.facts_for(parent, self.roster.permitted_students(parent))
            fact = next((f for f in facts if f['source_id'] == row['source_id']), None)
            today = datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
            return bool(fact and fact['extraction'].get('status', 'active') == 'active' and (fact['extraction'].get('due_date') or '') >= today)
        row = self.store.db.execute('SELECT event,context FROM inbox WHERE source_id=?', (reply['dedupe_key'].split(':')[0],)).fetchone()
        if row:
            caller = self.roster.resolve(IncomingMessage.model_validate_json(row['event']))
            if not caller:
                return False
            before = json.loads(row['context'])
            return caller['role'] != 'parent' or set(before['student_ids']) == set(caller['student_ids'])
        return reply['chat_id'] in self.roster.data['groups'] or any(reply['chat_id'] in p['whatsapp_ids'] for p in self.roster.data['parents'])

    async def tick(self) -> bool:
        work = False
        row = self.store.next_message()
        if row:
            await self.process(row)
            work = True
        job = self.store.due_job()
        if job:
            await self.poll_job(job)
            work = True
        if await self.remind_one():
            work = True
        delivered = await self.deliver_one()
        # Optional Google work must not hold the saved WhatsApp acknowledgement.
        if await self.calendar_one():
            work = True
        return work or delivered

    async def run(self):
        while True:
            try:
                if not await self.tick():
                    await asyncio.sleep(.25)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Background worker error')
                await asyncio.sleep(1)
