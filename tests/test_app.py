"""Signed webhook through real adapters using mock remote HTTP responses only."""
import asyncio
import base64
import hashlib
import hmac
import json

import httpx
import pytest

from octo.app import create_app
from octo.config import Settings
from octo.contracts import Extraction, GroundedAnswer, StudySection, NoticeDecision
from octo.offline import OfflineAI, OfflineTransport
from octo.replay import drain
from octo.sarvam import SarvamClient
from octo.waha import WahaClient


class MemberTransport(OfflineTransport):
    def __init__(self):
        super().__init__()
        self.members = [[f'91900000000{n}@c.us'] for n in (1, 2, 3)]
        self.membership_error = False

    async def group_members(self, group_id):
        if self.membership_error:
            raise httpx.ConnectError('Fixture membership failure')
        return self.members

    async def send_text(self, chat_id, text, reply_to=None):
        await super().send_text(chat_id, text, reply_to)
        return f'fixture-sent-{len(self.sent)}'


def live_config(tmp_path):
    roster = json.loads(open('roster.example.json').read())
    roster['groups'] = {'120363000000001@g.us': '5B'}
    roster['teachers'][0]['whatsapp_ids'] = ['919000000001@c.us']
    roster['parents'][0]['whatsapp_ids'] = ['919000000002@c.us']
    roster['parents'][1]['whatsapp_ids'] = ['919000000003@c.us']
    path = tmp_path / 'roster.json'
    path.write_text(json.dumps(roster))
    return Settings(mode='live', data_dir=tmp_path, roster_path=path, poll_seconds=0, general_brain=True,
                    db_key='ab' * 32, sarvam_api_key='fake-sarvam', waha_api_key='fake-waha', webhook_secret='fake-hook')


def envelope(message_id, *, parent=False, media=None, body='Bring crayons and a drawing book tomorrow.'):
    payload = {'id': message_id, 'from': '919000000002@c.us' if parent else '120363000000001@g.us',
               'fromMe': False, 'timestamp': 1792267200, 'body': body}
    if not parent:
        payload['participant'] = '919000000001@c.us'
    if media:
        payload.update(hasMedia=True, media=media)
    return {'event': 'message', 'session': 'default', 'payload': payload}


async def send(client, event, secret='fake-hook', algorithm='sha512'):
    body = json.dumps(event, ensure_ascii=False).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    return await client.post('/webhooks/waha', content=body, headers={
        'X-Webhook-Hmac': signature, 'X-Webhook-Hmac-Algorithm': algorithm,
        'Content-Type': 'application/json',
    })


async def test_full_signed_text_photo_voice_flow_with_real_adapters(tmp_path):
    outgoing = []
    requests = []

    def remote(request):
        requests.append(request)
        path = request.url.path
        if request.url.host in ('localhost', '127.0.0.1'):
            assert request.headers['x-api-key'] == 'fake-waha'
            if path.endswith('/participants'):
                return httpx.Response(200, json=[{'id': f'91900000000{n}@c.us'} for n in (1, 2, 3)])
            if path.startswith('/api/files/'):
                return httpx.Response(200, content=b'EXPLICIT MOCK MEDIA BYTES')
            data = json.loads(request.content)
            outgoing.append((path, data))
            return httpx.Response(200, json={'id': f'fake-sent-{len(outgoing)}'})
        assert request.headers['api-subscription-key'] == 'fake-sarvam'
        if path == '/v1/chat/completions':
            source = json.loads(json.loads(request.content)['messages'][1]['content'])
            if 'facts' in source:
                assert source['student_names'] == ['Aarav']
                assert len(source['facts']) == 2
                result = GroundedAnswer(language_code='hi-IN', text='आरव को क्रेयॉन और ड्रॉइंग बुक लानी है। विज्ञान: पौधे के भाग, जड़ें और तने।',
                                        spoken_text='आरव को क्रेयॉन और ड्रॉइंग बुक लानी है। पौधे के भाग पढ़ने हैं।',
                                        source_ids=[f['source_id'] for f in source['facts']])
            elif source.get('CURRENT_OCR'):
                assert 'Science Chapter 6' in source['CURRENT_OCR']
                result = Extraction(kind='syllabus', subject='Science', sections=[
                    StudySection(chapter='Chapter 6', topics=['Parts of a plant', 'Roots and stems'], pages='42–47')])
            else:
                result = Extraction(kind='requirement', items=['crayons', 'drawing book'], date_as_written='tomorrow', due_date='2099-01-01')
            if isinstance(result, Extraction):
                result = NoticeDecision(records=[result])
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': result.model_dump_json()}}]})
        if path == '/doc-ai/v1/job/digitise':
            assert b'.jpg"' in request.content
            assert b'Content-Type: image/jpeg' in request.content
            return httpx.Response(200, json={'job_id': 'mock-job'})
        if path == '/doc-ai/v1/job/mock-job/status':
            return httpx.Response(200, json={'status': 'completed'})
        if path == '/doc-ai/v1/job/mock-job/results':
            return httpx.Response(200, json={'status': 'completed', 'type': 'digitise', 'documents': [{'pages': [{
                'page_number': 1, 'content': '<p>Science Chapter 6: Parts of a plant; Roots and stems. Pages 42–47.</p>',
            }]}]})
        if path == '/speech-to-text':
            assert b'Content-Type: audio/ogg' in request.content
            assert b'Aarav' in request.content and b'Meera' not in request.content
            return httpx.Response(200, json={'transcript': 'आरव को कल क्या लाना और पढ़ना है?', 'language_code': 'hi-IN'})
        if path == '/text-to-speech':
            assert any('आरव' in d.get('text', '') for _, d in outgoing)
            return httpx.Response(200, json={'audios': [base64.b64encode(b'MOCK MP3 BYTES').decode()]})
        raise AssertionError(f'Unexpected request: {request.method} {path}')

    settings = live_config(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as remote_client:
        ai = SarvamClient(settings.sarvam_api_key, client=remote_client)
        transport = WahaClient(settings.waha_base_url, settings.waha_api_key, 'default', client=remote_client)
        app = create_app(settings, ai=ai, transport=transport, worker=False)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app') as client:
            for event in [
                envelope('TXT'),
                envelope('IMG', body='Science test', media={'url': 'http://localhost:3000/api/files/image.jpg', 'mimetype': 'image/jpeg'}),
                envelope('VOICE', parent=True, body='', media={'url': 'http://localhost:3000/api/files/voice.ogg', 'mimetype': 'audio/ogg; codecs=opus'}),
            ]:
                response = await send(client, event)
                assert response.status_code == 200 and response.json()['status'] == 'queued'
                await drain(app.state.octo)
            assert app.state.octo.store.counts()['facts'] == 2
            assert (await send(client, envelope('TXT'))).json()['status'] == 'duplicate'
            saved = [json.loads(r[0]) for r in app.state.octo.store.db.execute('SELECT extraction FROM facts')]
            assert next(r for r in saved if r['kind'] == 'requirement')['due_date'] != '2099-01-01'
            voice = [data for path, data in outgoing if path == '/api/sendVoice']
            assert len(voice) == 1 and voice[0]['convert'] is True
            assert voice[0]['chatId'] == '919000000002@c.us'
            assert voice[0]['file']['mimetype'] == 'audio/mpeg'
            assert any('Sources:' in data.get('text', '') for _, data in outgoing)
            assert all(r['status'] == 'sent' for r in app.state.octo.store.replies())


async def test_webhook_auth_required_and_only_group_members_are_parents(tmp_path):
    transport = MemberTransport()
    app = create_app(live_config(tmp_path), ai=OfflineAI(), transport=transport, worker=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app') as client:
        assert (await send(client, envelope('T1'), secret='wrong')).status_code == 401
        assert (await send(client, envelope('T1'), algorithm='sha256')).status_code == 401
        event = envelope('T1')
        event['payload']['participant'] = '919999999999@c.us'
        assert app.state.octo.store.counts()['inbox'] == 0
        assert (await send(client, event)).json()['status'] == 'ignored'
        assert app.state.octo.store.counts()['inbox'] == 0
        assert not transport.sent
        transport.members.append(['919999999999@c.us'])
        assert (await send(client, event)).json()['status'] == 'queued'
        context = json.loads(app.state.octo.store.db.execute('SELECT context FROM inbox').fetchone()[0])
        assert context['role'] == 'parent'
        await drain(app.state.octo)
        assert app.state.octo.store.counts()['facts'] == 0
        assert app.state.octo.transport.sent
        assert (await send(client, {'event': 'message', 'payload': {}})).status_code == 400


async def test_live_member_can_dm_without_posting_in_group_and_loses_access_on_leave(tmp_path):
    transport = MemberTransport()
    app = create_app(live_config(tmp_path), ai=OfflineAI(), transport=transport, worker=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app') as client:
        event = envelope('MEMBER-DM', parent=True, body='What should we bring tomorrow?')
        event['payload']['from'] = '123456@lid'
        assert (await send(client, event)).json()['status'] == 'ignored'
        transport.members.append(['123456@lid', '919000000010@c.us'])
        assert (await send(client, event)).json()['status'] == 'queued'
        row = app.state.octo.store.db.execute('SELECT context FROM inbox').fetchone()
        assert json.loads(row[0])['role'] == 'parent'
        await drain(app.state.octo)
        assert len(transport.sent) == 1 and transport.sent[0]['chat_id'] == '123456@lid'
        transport.members.pop()
        event['payload']['id'] = 'LEFT-DM'
        assert (await send(client, event)).json()['status'] == 'ignored'
        assert len(transport.sent) == 1


@pytest.mark.parametrize('failure', ['left_group', 'lookup_failed'])
@pytest.mark.parametrize('stage', ['ingestion', 'processing', 'delivery', 'unlinked_reply'])
async def test_membership_required_even_for_configured_parent_and_queued_replies(tmp_path, failure, stage):
    transport = MemberTransport()
    app = create_app(live_config(tmp_path), ai=OfflineAI(), transport=transport, worker=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app') as client:
        event = envelope('PARENT', parent=True)
        core = app.state.octo
        if stage != 'ingestion':
            assert (await send(client, event)).json()['status'] == 'queued'
        else:
            # First populate a valid snapshot, then prove it is not reused.
            await core.refresh_memberships()
        if failure == 'left_group':
            transport.members = [['919000000001@c.us']]
        else:
            transport.membership_error = True
        if stage == 'ingestion':
            event['payload']['hasMedia'] = True
            event['payload']['media'] = {'url': 'fixture://parent-hindi', 'mimetype': 'audio/ogg'}
            assert (await send(client, event)).json()['status'] == 'ignored'
            assert core.store.counts()['inbox'] == 0
        elif stage == 'processing':
            await core.process(core.store.next_message())
            assert core.store.db.execute('SELECT status FROM inbox').fetchone()[0] == 'ignored'
        else:
            sid = core.store.db.execute('SELECT source_id FROM inbox').fetchone()[0]
            key = sid + ':answer' if stage == 'delivery' else 'previous-queued-reply'
            core.store.reply(key, '919000000002@c.us', 'A queued reply')
            await core.deliver_one()
            assert core.store.replies()[0]['status'] == 'cancelled'
        assert not transport.sent


async def test_offline_http_cannot_accept_live_whatsapp_events(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), worker=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app') as client:
        health = (await client.get('/health')).json()
        assert health['mode'] == 'offline' and health['external_integrations_verified'] is False
        assert (await send(client, envelope('T1'))).status_code == 409


async def test_background_worker_processes_signed_message_without_manual_tick(tmp_path):
    delivered = asyncio.Event()

    class RecordingTransport(MemberTransport):
        async def send_text(self, chat_id, text, reply_to=None):
            await super().send_text(chat_id, text, reply_to)
            delivered.set()

    transport = RecordingTransport()
    app = create_app(live_config(tmp_path), ai=OfflineAI(), transport=transport)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app') as client:
        assert (await send(client, envelope('WORKER'))).json()['status'] == 'queued'
        await asyncio.wait_for(delivered.wait(), timeout=2)
        assert app.state.octo.store.counts()['facts'] == 1
        assert 'crayons' in transport.sent[0]['text']


async def test_live_startup_rejects_missing_credentials_and_fictional_roster(tmp_path):
    app = create_app(Settings(mode='live', data_dir=tmp_path))
    with pytest.raises(ValueError, match='requires local configuration'):
        async with app.router.lifespan_context(app):
            pass
    settings = live_config(tmp_path)
    settings.roster_path = Settings().roster_path
    app = create_app(settings)
    with pytest.raises(ValueError, match='real designated WhatsApp IDs'):
        async with app.router.lifespan_context(app):
            pass
