"""Queued delivery and quoted approval authorization boundaries."""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from octo.cart import CartService
from octo.config import Settings
from octo.contracts import Extraction, IncomingMessage
from octo.core import Octo, Roster
from octo.offline import OfflineAI, OfflineTransport
from octo.storage import Store
from octo.waha import normalize


def app_at(tmp_path):
    return Octo(Settings(mode='live',data_dir=tmp_path),Store(tmp_path/'db.sqlite3'),
        Roster(Path('roster.example.json')),OfflineAI(),OfflineTransport())


def reminder(app, due):
    teacher=app.roster.data['teachers'][0] | {'class_id':'5B'}
    event=IncomingMessage(session='default',message_id='n',chat_id='demo-class-5b@g.us',sender_id='demo-teacher',is_group=True,timestamp=datetime.now(timezone.utc))
    app.store.save_fact('source',teacher,Extraction(kind='requirement',items=['crayons'],due_date=due),event)
    app.store.schedule_reminder('source','parent-a','demo-parent-a',time.time()-1)


async def test_pending_reminder_is_cancelled_if_parent_revoked_before_send(tmp_path):
    app=app_at(tmp_path)
    try:
        reminder(app,(datetime.now(timezone.utc)+timedelta(days=1)).date().isoformat())
        await app.remind_one()
        app.roster.data['parents'][0]['whatsapp_ids']=[]
        assert await app.deliver_one()
        assert not app.transport.sent
        assert app.store.replies()[0]['status']=='cancelled'
    finally: app.store.close()


async def test_past_date_reminder_is_not_sent_after_late_restart(tmp_path):
    app=app_at(tmp_path)
    try:
        reminder(app,'2020-01-01')
        assert await app.remind_one()
        assert not app.store.replies()
        assert app.store.db.execute('SELECT status FROM reminders').fetchone()[0]=='cancelled'
    finally: app.store.close()


async def test_queued_parent_reply_cancelled_if_linked_student_changes(tmp_path):
    app=app_at(tmp_path)
    try:
        event=IncomingMessage(session='default',message_id='q',chat_id='demo-parent-a',sender_id='demo-parent-a',timestamp=datetime.now(timezone.utc))
        app.accept(event)
        sid=app.store.message(event.source_key)['source_id']
        app.reply(sid,event,'Aarav private detail')
        app.roster.identities['demo-parent-a']['student_ids']=['meera']
        assert await app.deliver_one()
        assert not app.transport.sent
    finally: app.store.close()


async def test_quote_without_message_id_cannot_approve(tmp_path):
    app=app_at(tmp_path)
    try:
        service=CartService(app.store.db)
        quote=service.propose('parent-a','demo-parent-a',['crayons'])
        code=re.search(r'APPROVE ([A-F0-9]{10})',quote)[1]
        raw={'event':'message','session':'default','payload':{
            'id':'quoted','from':'919000000002@c.us','timestamp':datetime.now(timezone.utc).timestamp(),
            'body':'APPROVE '+code,'replyTo':{'body':'old quote without ID'}}}
        message=normalize(raw)
        assert message.is_quoted and message.quoted_message_id is None
        message.chat_id=message.sender_id='demo-parent-a'
        app.accept(message)
        await app.process(app.store.next_message())
        assert app.store.db.execute('SELECT status FROM carts WHERE code=?',(code,)).fetchone()[0]=='pending'
        assert 'new, typed' in app.store.replies()[0]['text']
    finally: app.store.close()
