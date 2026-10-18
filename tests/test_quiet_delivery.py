"""Durable delivery policies exercised only with synthetic transports."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from octo.config import Settings
from octo.contracts import IncomingMessage, Media
from octo.core import Octo, Roster
from octo.delivery import should_speak
from octo.offline import OfflineAI, OfflineTransport
from octo.storage import Store


@pytest.fixture
def app(tmp_path):
    instance = Octo(Settings(mode='offline', data_dir=tmp_path),
                    Store(tmp_path / 'queue.sqlite3'),
                    Roster(Path('roster.example.json')), OfflineAI(), OfflineTransport())
    yield instance
    instance.store.close()


def incoming(**changes):
    return IncomingMessage(**(dict(session='default', message_id='incoming',
        chat_id='demo-parent-a', sender_id='demo-parent-a',
        timestamp=datetime.now(timezone.utc), text='Question') | changes))


@pytest.mark.parametrize('group', [True, False])
@pytest.mark.parametrize('kind', ['text', 'voice'])
@pytest.mark.parametrize('preference', [None, False, True])
def test_automatic_audio_matrix(group, kind, preference):
    assert should_speak(incoming(is_group=group, kind=kind),
                        {'voice_replies': preference}) == (
        not group and (kind == 'voice' or preference is True))


async def test_quote_survives_restart_and_targets_incoming_not_its_quote(app):
    event = incoming(quoted_message_id='older-message', is_quoted=True)
    app.accept(event)
    sid = app.store.message(event.source_key)['source_id']
    app.reply(sid, event, 'Answer')
    app.store.close()
    app.store = Store(app.settings.data_dir / 'queue.sqlite3')
    await app.deliver_one()
    assert len(app.transport.sent) == 1
    assert app.transport.sent[0]['chat_id'] == event.chat_id
    assert app.transport.sent[0]['reply_to'] == event.message_id
    assert app.transport.sent[0]['text'].startswith('[OFFLINE DEMO — synthetic fixture responses; no live delivery]\nAnswer')
    assert app.transport.sent[0]['text'].count('Hi! I’m Octo') == 1


def test_legacy_queue_migration_preserves_pending_reply(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE outbox (
        id INTEGER PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL,
        chat_id TEXT NOT NULL, text TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'text',
        path TEXT, status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        remote_id TEXT, error TEXT)""")
    db.execute("INSERT INTO outbox(dedupe_key,chat_id,text) VALUES('legacy','chat','Saved')")
    db.commit()
    db.close()
    store = Store(path)
    try:
        assert store.next_reply()['text'] == 'Saved'
        assert store.next_reply()['reply_to'] is None
    finally:
        store.close()


async def test_quote_cannot_cross_chats_even_after_queue_mutation(app):
    event = incoming()
    app.accept(event)
    sid = app.store.message(event.source_key)['source_id']
    with pytest.raises(ValueError, match='destination chat'):
        app.store.reply('bad', 'demo-parent-b', 'Answer',
                        reply_to=event.message_id, reply_chat_id=event.chat_id)
    app.reply(sid, event, 'Answer')
    with app.store.db:
        app.store.db.execute("UPDATE outbox SET chat_id='demo-parent-b', reply_chat_id='demo-parent-b'")
    await app.deliver_one()
    assert not app.transport.sent
    assert app.store.replies()[0]['status'] == 'cancelled'


async def test_uncertain_quoted_send_is_never_retried_unquoted(app):
    event = incoming()
    app.accept(event)
    app.reply(app.store.message(event.source_key)['source_id'], event, 'Answer')
    calls = []
    async def uncertain(chat, text, reply_to=None):
        calls.append(reply_to)
        raise TimeoutError()
    app.transport.send_text = uncertain
    await app.deliver_one()
    app.store.close()
    app.store = Store(app.settings.data_dir / 'queue.sqlite3')
    assert not await app.deliver_one()
    assert calls == [event.message_id]
    assert app.store.replies()[0]['status'] == 'uncertain'


async def test_voice_ack_precedes_stt_with_backlog_and_is_durable_under_retry(app):
    event = incoming(kind='voice', media=Media(url='fixture://parent-hindi', mime_type='audio/ogg'))
    app.store.reply('older:answer', event.chat_id, 'Earlier queued reply')
    await app.ingest(event)
    row = app.store.next_message()
    calls = []
    async def slow_stt(path, names):
        calls.append('stt')
        assert app.transport.sent[0]['reply_to'] == event.message_id
        assert 'वॉइस संदेश' in app.transport.sent[0]['text']
        raise TimeoutError()
    app.ai.transcribe = slow_stt
    await app.process(row)
    app.store.close()
    app.store = Store(app.settings.data_dir / 'queue.sqlite3')
    await app.process(app.store.message(event.source_key))
    assert calls == ['stt', 'stt']
    assert len([r for r in app.store.replies() if r['dedupe_key'].endswith(':voice-ack')]) == 1
    assert len([r for r in app.transport.sent if 'वॉइस संदेश' in r['text']]) == 1


def test_new_verified_member_defaults_to_text(app):
    group = next(iter(app.roster.data['groups']))
    app.roster.set_group_members(group, [['919999999999@c.us']])
    parent = app.roster.resolve(incoming(sender_id='919999999999@c.us', chat_id='919999999999@c.us'))
    assert parent['voice_replies'] is False
