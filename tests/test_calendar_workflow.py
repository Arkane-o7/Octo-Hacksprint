"""Calendar workflow uses captured calls, no Google/WhatsApp delivery."""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from octo.config import Settings
from octo.contracts import Extraction, IncomingMessage, NoticeDecision
from octo.core import Octo, Roster
from octo.offline import OfflineAI, OfflineTransport
from octo.storage import Store


CALENDAR = 'demo@group.calendar.google.com'
FUTURE = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()


class Calendar:
    configured = True
    def __init__(self):
        self.calls=[]
        self.fail=False
    async def sync_fact(self,fact):
        self.calls.append(('upsert',fact['source_id']))
        if self.fail: raise TimeoutError()
        return {'status':'synced','event_id':fact['source_id'], 'url':'https://calendar.google.com/calendar/event?eid=test'}
    async def delete_fact(self,sid):
        self.calls.append(('delete',sid))
        if self.fail: raise TimeoutError()
        return {'status':'deleted','event_id':sid}


@pytest.fixture
def app(tmp_path):
    obj=Octo(Settings(mode='live',data_dir=tmp_path,calendar_id=CALENDAR),Store(tmp_path/'test.sqlite3'),
             Roster(Path('roster.example.json')),OfflineAI(),OfflineTransport(),calendar=Calendar())
    yield obj
    obj.store.close()


def save(app,sid='source',**changes):
    record=Extraction(kind='requirement',items=['crayons'],due_date=FUTURE,date_as_written=FUTURE,**changes)
    event=IncomingMessage(session='default',message_id=sid,chat_id='demo-class-5b@g.us',sender_id='demo-teacher',
                          is_group=True,timestamp=datetime.now(timezone.utc))
    app.store.save_fact(sid,app.roster.resolve(event),record,event)
    return event


async def test_calendar_sync_persists_real_adapter_metadata_and_deduplicates(app):
    save(app)
    app.queue_calendar_sync()
    assert await app.calendar_one()
    app.queue_calendar_sync()
    assert not await app.calendar_one()
    assert app.calendar.calls==[('upsert','source')]
    fact=app.store.class_facts('5B')[0]
    assert fact['source']['calendar']['status']=='synced'
    assert 'all-day' in app.store.replies()[0]['text']


async def test_missing_oauth_offline_unclear_private_past_and_undated_do_not_sync(app):
    save(app,'unclear',unclear=['Which date?'])
    save(app,'student',student_id='aarav')
    save(app,'past')
    record=json.loads(app.store.db.execute("SELECT extraction FROM facts WHERE source_id='past'").fetchone()[0])
    record['due_date']='2020-01-01'
    app.store.db.execute("UPDATE facts SET extraction=? WHERE source_id='past'",(json.dumps(record),))
    app.store.db.commit()
    app.queue_calendar_sync()
    assert not await app.calendar_one() and not app.calendar.calls
    save(app,'valid')
    app.calendar.configured=False
    app.queue_calendar_sync()
    assert not await app.calendar_one()
    app.calendar.configured=True
    app.settings.mode='offline'
    app.queue_calendar_sync()
    assert not await app.calendar_one()


async def test_replacement_deletes_old_before_new_and_never_creates_cancelled_record(app):
    save(app,'old')
    app.queue_calendar_sync()
    event=save(app,'dummy')
    record=Extraction(kind='requirement',items=['pencils'],due_date=FUTURE,replaces_source_ids=['old'])
    app.store.save_decision([('new',record)],app.roster.resolve(event),event,NoticeDecision(records=[record]))
    app.queue_calendar_sync()
    await app.calendar_one()
    assert app.calendar.calls[0]==('delete','old')
    while await app.calendar_one(): pass
    assert ('upsert','old') not in app.calendar.calls and ('upsert','new') in app.calendar.calls


async def test_unconfirmed_calendar_keeps_school_record_and_retries_are_bounded(app):
    save(app)
    app.calendar.fail=True
    app.queue_calendar_sync()
    for _ in range(3):
        app.store.db.execute('UPDATE calendar_jobs SET next_attempt=0')
        app.store.db.commit()
        assert await app.calendar_one()
    assert not await app.calendar_one()
    assert len(app.store.class_facts('5B'))==1
    assert app.store.db.execute('SELECT status FROM calendar_jobs').fetchone()[0]=='failed'
    assert 'unconfirmed' in app.store.replies()[0]['text']
    assert 'Added' not in app.store.replies()[0]['text']


async def test_restart_recovers_calendar_intent_without_duplicating_completed_job(app):
    save(app)
    app.queue_calendar_sync()
    app.store.db.execute("UPDATE calendar_jobs SET status='syncing'")
    app.store.db.commit()
    app.store.close()
    app.store=Store(app.settings.data_dir/'test.sqlite3')
    assert await app.calendar_one()
    app.store.close()
    app.store=Store(app.settings.data_dir/'test.sqlite3')
    app.queue_calendar_sync()
    assert not await app.calendar_one()


async def test_replaced_entry_failure_blocks_new_calendar_entry(app):
    event=save(app,'old')
    record=Extraction(kind='requirement',items=['pencils'],due_date=FUTURE,replaces_source_ids=['old'])
    app.store.save_decision([('new',record)],app.roster.resolve(event),event,NoticeDecision(records=[record]))
    app.queue_calendar_sync()
    app.store.db.execute("UPDATE calendar_jobs SET status='failed' WHERE source_id='old'")
    app.store.db.commit()
    assert not await app.calendar_one()
    assert not app.calendar.calls


async def test_obsolete_calendar_success_is_not_delivered(app):
    event=save(app,'old')
    app.queue_calendar_sync()
    await app.calendar_one()
    reply=app.store.next_reply()
    assert app._delivery_allowed(reply)
    record=Extraction(kind='requirement',items=['pencils'],due_date=FUTURE,replaces_source_ids=['old'])
    app.store.save_decision([('new',record)],app.roster.resolve(event),event,NoticeDecision(records=[record]))
    assert not app._delivery_allowed(reply)
    assert app.store.replies()[0]['status']=='cancelled'


async def test_saved_reply_is_delivered_before_calendar_network_work(app):
    save(app)
    app.queue_calendar_sync()
    app.store.reply('source:answer','demo-class-5b@g.us','Saved school notice')
    order=[]
    async def send(*args):
        order.append('whatsapp')
        return 'message-id'
    original=app.calendar.sync_fact
    async def sync(fact):
        order.append('calendar')
        return await original(fact)
    app.transport.send_text=send
    app.calendar.sync_fact=sync
    await app.tick()
    assert order==['whatsapp','calendar']
