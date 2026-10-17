"""PDF workflow checks use fake OCR/Drive and temporary storage only."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from octo.config import Settings
from octo.contracts import Extraction, StudySection, NoticeDecision, IncomingMessage, Media, GroundedAnswer
from octo.core import Octo, Roster
from octo.offline import OfflineAI, OfflineTransport
from octo.storage import Store


class Brain(OfflineAI):
    async def understand(self, *args, **kwargs):
        return NoticeDecision(records=[Extraction(kind='notes', subject='Science',
            summary='Science Chapter 6 notes', sections=[StudySection(chapter='Chapter 6', topics=['Roots'])])])

    async def answer(self, question, facts, *args):
        self.facts_seen = facts
        return GroundedAnswer(text='Science Chapter 6 notes are saved.', source_ids=[facts[0]['source_id']])


class Drive:
    configured = True
    def __init__(self):
        self.calls = []
    async def file_pdf(self, path, subject, chapter):
        self.calls.append((path, subject, chapter))
        return {'id': 'mockFile', 'url': 'https://drive.google.com/file/d/mockFile/view'}


@pytest.fixture
def app(tmp_path):
    obj = Octo(Settings(mode='live', data_dir=tmp_path, poll_seconds=0, general_brain=True), Store(tmp_path/'test.sqlite3'),
               Roster(Path('roster.example.json')), Brain(), OfflineTransport(), drive=Drive())
    yield obj
    obj.store.close()


async def pdf(app, identifier='pdf', content=b'%PDF-1.4 MOCK PDF BYTES'):
    path = app.settings.data_dir / 'science.pdf'
    path.write_bytes(content)
    msg = IncomingMessage(session='default', message_id=identifier, chat_id='demo-class-5b@g.us',
        sender_id='demo-teacher', timestamp=datetime.now(timezone.utc), is_group=True, kind='document',
        media=Media(local_path=str(path), mime_type='application/pdf', filename='Science Chapter 6.pdf'))
    assert await app.ingest(msg) == 'queued'
    row = app.store.next_message()
    await app.process(row)
    job = app.store.due_job()
    if job:
        await app.poll_job(job)
    return msg


async def test_pdf_ocr_files_clear_notes_and_returns_verified_adapter_link(app):
    msg = await pdf(app)
    assert len(app.drive.calls) == 1
    assert app.drive.calls[0][1:] == ('Science', 'Chapter 6')
    metadata = app.store.document(msg.source_key)
    assert metadata['status'] == 'uploaded'
    assert metadata['url'] in app.store.replies()[-1]['text']
    assert await app.ingest(msg) == 'duplicate'
    parent = app.roster.data['parents'][0]
    facts = app.store.facts_for(parent, app.roster.permitted_students(parent))
    assert facts[0]['source']['document']['url'] == metadata['url']
    assert 'media_path' not in facts[0]['source']


async def test_unconfigured_drive_retains_file_and_never_fabricates_a_link(app):
    app.drive.configured = False
    msg = await pdf(app)
    doc = app.store.document(msg.source_key)
    assert doc['status'] == 'local' and doc['url'] is None and not app.drive.calls
    assert 'not configured' in app.store.replies()[-1]['text']
    assert 'https://' not in app.store.replies()[-1]['text']
    assert len(app.store.class_facts('5B')) == 1


async def test_ambiguous_or_student_specific_document_does_not_upload(app):
    async def individual(*args, **kwargs):
        return NoticeDecision(records=[Extraction(kind='notes', subject='Science', summary='Aarav notes', student_id='aarav')])
    app.ai.understand = individual
    msg = await pdf(app)
    assert not app.drive.calls and app.store.document(msg.source_key)['url'] is None
    assert 'class-wide' in app.store.replies()[-1]['text']


async def test_restart_after_upload_intent_does_not_retry_uncertain_write(app):
    msg = await pdf(app)
    metadata = app.store.document(msg.source_key)
    metadata.update(status='uploading', url=None, message='Check Drive before retrying.')
    app.store.save_document(msg.source_key, [], metadata)
    sid = app.store.message(msg.source_key)['source_id']
    before = len(app.drive.calls)
    decision = NoticeDecision.model_validate_json(app.store.applied_decision(msg.source_key))
    await app._file_pdf(sid, msg, decision)
    assert len(app.drive.calls) == before


async def test_non_pdf_document_rejected_before_ocr(app):
    msg = await pdf(app, content=b'not a PDF')
    assert app.store.message(msg.source_key)['status'] == 'failed'
    assert not app.drive.calls and not app.store.class_facts('5B')


async def test_established_syllabus_path_also_reports_unconfigured_drive_honestly(app):
    app.settings.general_brain=False
    app.drive.configured=False
    msg=await pdf(app)
    assert app.store.document(msg.source_key)['status']=='local'
    assert 'not configured' in app.store.replies()[-1]['text']
    assert not app.drive.calls
