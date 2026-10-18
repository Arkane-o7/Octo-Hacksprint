"""Verified join events create exactly one private welcome, never school facts."""
import time

import httpx
import pytest

from octo.app import create_app
from octo.offline import OfflineAI
from octo.onboarding import normalize_join
from octo.replay import drain
from octo.storage import Store
from test_app import MemberTransport, live_config, send, envelope

GROUP = '120363000000001@g.us'
MEMBER = '919000000010@c.us'
BOT = '919000000099@c.us'


def joined(members=(MEMBER,), **changes):
    return {'event': 'group.v2.participants', 'session': 'default', 'me': {'id': BOT},
            'payload': {'type': 'join', 'timestamp': time.time(), 'group': {'id': GROUP},
                        'participants': [{'id': member, 'role': 'participant'} for member in members], **changes}}


@pytest.fixture
async def app(tmp_path):
    settings = live_config(tmp_path)
    settings.general_brain = False
    transport = MemberTransport()
    transport.members += [[MEMBER], [BOT]]
    app = create_app(settings, ai=OfflineAI(), transport=transport, worker=False)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app') as client:
        yield client


async def test_join_requires_hmac_and_does_not_trust_payload_membership(app, client):
    assert (await send(client, joined(), secret='wrong')).status_code == 401
    assert app.state.octo.store.db.execute('SELECT count(*) FROM ux_join_jobs').fetchone()[0] == 0
    unknown = '919000001234@c.us'
    assert (await send(client, joined((unknown,)))).json()['status'] == 'queued'
    await drain(app.state.octo)
    assert not app.state.octo.transport.sent
    assert app.state.octo.store.db.execute('SELECT attempts FROM ux_join_jobs').fetchone()[0] == 1


async def test_new_member_receives_one_unquoted_private_menu_and_can_select(app, client):
    octo = app.state.octo
    event = joined()
    assert (await send(client, event)).json()['status'] == 'queued'
    await drain(octo)
    assert len(octo.transport.sent) == 1
    welcome = octo.transport.sent[0]
    assert welcome['chat_id'] == MEMBER and welcome['reply_to'] is None
    assert 'Octo' in welcome['text'] and '1 ·' in welcome['text'] and '4 ·' in welcome['text']
    assert octo.store.counts()['facts'] == octo.store.counts()['inbox'] == 0
    # Numbered choices work immediately, without making the new member type menu.
    choice = envelope('choice', parent=True, body='4')
    choice['payload']['from'] = MEMBER
    assert (await send(client, choice)).json()['status'] == 'queued'
    await drain(octo)
    assert '1 · भाषा' in octo.transport.sent[-1]['text']
    assert octo.transport.sent[-1]['reply_to'] == 'choice'
    assert (await send(client, event)).json()['status'] == 'duplicate'
    await drain(octo)
    assert len(octo.transport.sent) == 2


async def test_restart_recovers_pending_welcome_without_duplicates(app, client):
    octo = app.state.octo
    assert (await send(client, joined())).json()['status'] == 'queued'
    path = octo.settings.data_dir / 'live' / 'octo.sqlite3'
    octo.store.close()
    octo.store = Store(path, key=octo.settings.db_key)
    assert await octo.onboarding.process_one()
    assert octo.store.next_reply()['reply_to'] is None
    octo.store.close()
    octo.store = Store(path, key=octo.settings.db_key)
    await drain(octo)
    assert len(octo.transport.sent) == 1
    assert (await send(client, joined())).json()['status'] == 'duplicate'
    await drain(octo)
    assert len(octo.transport.sent) == 1


@pytest.mark.parametrize('stage', ['processing', 'delivery'])
async def test_departed_member_is_never_welcomed(app, client, stage):
    octo = app.state.octo
    await send(client, joined())
    if stage == 'delivery':
        await octo.onboarding.process_one()
    octo.transport.members = [m for m in octo.transport.members if MEMBER not in m]
    await drain(octo)
    assert not octo.transport.sent
    if stage == 'delivery':
        assert octo.store.replies()[0]['status'] == 'cancelled'


async def test_group_lookup_failure_is_bounded_and_recovers_safely(app, client, monkeypatch):
    from types import SimpleNamespace
    clock = [100.0]
    monkeypatch.setattr('octo.core.time', SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    octo = app.state.octo
    await send(client, joined())
    octo.transport.membership_error = True
    await drain(octo)
    assert not octo.transport.sent
    octo.transport.membership_error = False
    clock[0] += 31
    with octo.store.db:
        octo.store.db.execute('UPDATE ux_join_jobs SET next_attempt=0')
    await drain(octo)
    assert len(octo.transport.sent) == 1


async def test_phone_and_lid_duplicate_join_events_share_one_welcome(app, client):
    octo = app.state.octo
    lid = '123456789@lid'
    octo.transport.members[-2] = [MEMBER, lid]
    await send(client, joined((MEMBER, lid)))
    await drain(octo)
    assert len(octo.transport.sent) == 1
    assert octo.transport.sent[0]['chat_id'] == MEMBER


@pytest.mark.parametrize('change', ['group', 'session', 'old', 'future', 'leave', 'promote', 'request', 'bot_join', 'self'])
async def test_unrelated_or_ineligible_join_events_do_not_send(app, client, change):
    event = joined()
    if change == 'group': event['payload']['group']['id'] = '999999999@g.us'
    elif change == 'session': event['session'] = 'other'
    elif change == 'old': event['payload']['timestamp'] = time.time() - 90000
    elif change == 'future': event['payload']['timestamp'] = time.time() + 3600
    elif change in ('leave', 'promote'): event['payload']['type'] = change
    elif change == 'request': event['event'] = 'group.v2.participants.join-request'
    elif change == 'bot_join': event['event'] = 'group.v2.join'
    elif change == 'self': event = joined((BOT,))
    assert (await send(client, event)).json()['status'] == 'ignored'
    await drain(app.state.octo)
    assert not app.state.octo.transport.sent


async def test_bot_alias_and_configured_teacher_are_not_parent_onboarding(app, client):
    octo = app.state.octo
    bot_lid = '999123456@lid'
    octo.transport.members[-1] = [BOT, bot_lid]
    await send(client, joined((bot_lid, '919000000001@c.us')))
    await drain(octo)
    assert not octo.transport.sent


async def test_uncertain_welcome_is_not_retried_after_restart(app, client):
    octo = app.state.octo
    calls = []
    async def timeout(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()
    octo.transport.send_text = timeout
    await send(client, joined())
    await drain(octo)
    assert octo.store.replies()[0]['status'] == 'uncertain'
    path = octo.settings.data_dir / 'live' / 'octo.sqlite3'
    octo.store.close()
    octo.store = Store(path, key=octo.settings.db_key)
    await send(client, joined())
    await drain(octo)
    assert calls == [1]


async def test_menu_and_outbox_are_atomic_when_welcome_queue_fails(app, client, monkeypatch):
    octo = app.state.octo
    await send(client, joined())
    original = octo.menus.welcome
    def broken(*args):
        original(*args)
        raise RuntimeError('simulated crash before commit')
    monkeypatch.setattr(octo.menus, 'welcome', broken)
    with pytest.raises(RuntimeError):
        await octo.onboarding.process_one()
    assert not octo.store.replies()
    assert octo.store.db.execute('SELECT status FROM ux_join_jobs').fetchone()[0] == 'pending'
    assert octo.store.db.execute('SELECT count(*) FROM ux_menus').fetchone()[0] == 0
    monkeypatch.setattr(octo.menus, 'welcome', original)
    await drain(octo)
    assert len(octo.transport.sent) == 1


async def test_delayed_join_does_not_reset_existing_menu(app, client):
    octo = app.state.octo
    event = envelope('menu', parent=True, body='menu')
    event['payload']['from'] = MEMBER
    await send(client, event)
    await drain(octo)
    before = [dict(row) for row in octo.store.db.execute('SELECT * FROM ux_menus')]
    await send(client, joined())
    await drain(octo)
    assert len(octo.transport.sent) == 1
    assert [dict(row) for row in octo.store.db.execute('SELECT * FROM ux_menus')] == before


@pytest.mark.parametrize('field,value', [('timestamp', True), ('timestamp', float('nan')), ('participants', []), ('participants', [{'id': 'bad'}])])
def test_invalid_join_payload_is_rejected(field, value):
    event = joined(**{field: value})
    with pytest.raises(ValueError): normalize_join(event)


def test_join_parser_handles_milliseconds_and_deduplicates():
    event = joined((MEMBER, MEMBER, BOT), timestamp=1792310400000)
    parsed = normalize_join(event)
    assert parsed.participant_ids == (MEMBER,)
    assert parsed.timestamp == 1792310400
