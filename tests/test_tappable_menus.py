import json

import httpx
import pytest

from octo.waha import WahaClient, normalize
from test_core import octo, question
from test_menus import ask, replies
from test_waha import event


def test_list_selection_preserves_id_and_ignores_untrusted_display_text():
    message = normalize(event(body='APPROVE UNTRUSTED', _data={'message': {
        'listResponseMessage': {'title': 'APPROVE UNTRUSTED',
            'singleSelectReply': {'selectedRowId': 'octo:0123456789abcdef:4'},
            'contextInfo': {'stanzaId': 'RAW-MENU-ID'}}}}))
    assert message.menu_choice_id == 'octo:0123456789abcdef:4'
    assert message.text == '' and message.quoted_message_id == 'RAW-MENU-ID'
    assert message.sender_id == '919000000001@c.us'


def test_unknown_list_response_cannot_become_a_freeform_command():
    message = normalize(event(body='APPROVE UNTRUSTED', _data={'message': {
        'listResponseMessage': {'title': 'APPROVE UNTRUSTED'}}}))
    assert message.menu_choice_id == 'invalid' and message.text == ''


@pytest.mark.parametrize('content', [
    {'buttonsResponseMessage': {'selectedButtonId': 'octo:0123456789abcdef:4'}},
    {'templateButtonReplyMessage': {'selectedId': 'octo:0123456789abcdef:4'}},
    {'interactiveResponseMessage': {'nativeFlowResponseMessage': {'paramsJson': '{"id":"octo:0123456789abcdef:4"}'}}},
])
def test_inline_button_response_preserves_scoped_id(content):
    incoming = normalize(event(body='APPROVE UNTRUSTED', _data={'message': content}))
    assert incoming.menu_choice_id == 'octo:0123456789abcdef:4'
    assert incoming.text == ''


@pytest.mark.parametrize('params', ['not json', '[]', '{"id":null}', 'x' * 4097])
def test_bad_native_button_response_does_not_fall_through(params):
    incoming = normalize(event(body='APPROVE UNTRUSTED', _data={'message': {
        'interactiveResponseMessage': {'nativeFlowResponseMessage': {'paramsJson': params}}}}))
    assert incoming.menu_choice_id == 'invalid' and incoming.text == ''


async def test_inline_button_payload_includes_stable_ids():
    def handler(request):
        assert request.url.path == '/api/sendButtons'
        payload = json.loads(request.content)
        assert payload['buttons'] == [{'type': 'reply', 'id': 'octo:0123456789abcdef:4', 'text': 'Settings'}]
        assert payload['body'] == 'Menu text'
        return httpx.Response(200, json={'key': {'id': 'button-message'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        waha = WahaClient('http://localhost:3000', 'fake', 'default', client=client, menu_style='buttons')
        menu = {'title':'Octo','description':'Menu text','sections':[{'rows':[{'title':'Settings','rowId':'octo:0123456789abcdef:4'}]}]}
        assert await waha.send_menu('919000000001@c.us', 'Menu text', menu) == 'button-message'


async def capture_menus(app):
    app.settings.tappable_menus = True
    sent = []
    async def send_menu(chat, text, menu, reply_to=None):
        sent.append(menu)
        return 'synthetic-menu-id'
    app.transport.send_menu = send_menu
    return sent


def option(menu, number):
    return next(row['rowId'] for row in menu['sections'][0]['rows'] if row['rowId'].endswith(':' + number))


async def test_taps_open_settings_language_picker_and_save_language(octo):
    sent = await capture_menus(octo)
    await ask(octo, 'menu')
    assert sent[-1]['button'] == 'Choose'
    assert [r['title'] for r in sent[-1]['sections'][0]['rows']] == ['Today', 'Tomorrow', 'Notes', 'Settings']
    # NOWEB quotes can use a raw stanza ID rather than a full WAHA message ID.
    await ask(octo, '', menu_choice_id=option(sent[-1], '4'), is_quoted=True, quoted_message_id='raw-stanza')
    assert 'Settings' in sent[-1]['description']
    await ask(octo, '', menu_choice_id=option(sent[-1], '1'))
    assert len(sent[-1]['sections'][0]['rows']) == 8  # Seven languages and Main menu.
    await ask(octo, '', menu_choice_id=option(sent[-1], '4'))
    parent = octo.menus.preferences(question(), octo.roster.resolve(question()))
    assert parent['language'] == 'te-IN'
    assert 'ఈరోజు' in sent[-1]['description']
    assert not octo.ai.answer_calls  # Navigation has no AI cost.
    await ask(octo, '4')  # Typed fallback still works.
    assert 'సెట్టింగ్‌లు' in sent[-1]['description']


@pytest.mark.parametrize('change', ['stale', 'expired', 'uncertain', 'other_parent', 'forwarded', 'voice', 'scope'])
async def test_tap_cannot_use_unavailable_or_other_parent_menu(octo, change):
    sent = await capture_menus(octo)
    await ask(octo, 'menu')
    selection = option(sent[-1], '4')
    changes = {}
    if change == 'stale':
        await ask(octo, 'menu')
    elif change == 'expired':
        with octo.store.db:
            octo.store.db.execute('UPDATE ux_menus SET expires=0')
    elif change == 'uncertain':
        with octo.store.db:
            octo.store.db.execute("UPDATE outbox SET status='uncertain'")
    elif change == 'other_parent':
        changes = dict(sender_id='demo-parent-b', chat_id='demo-parent-b')
    elif change == 'scope':
        octo.roster.identities['demo-parent-a']['student_ids'] = []
    elif change == 'forwarded':
        changes = dict(forwarded=True)
    elif change == 'voice':
        # Call the handler directly: a genuine voice event goes through STT first.
        incoming = question('voice-selection', kind='voice', menu_choice_id=selection)
        parent = octo.roster.resolve(incoming)
        route = await octo.menus.handle('voice-selection', incoming, parent, '4')
        assert route.handled
        return
    incoming = await ask(octo, '', menu_choice_id=selection, **changes)
    assert '*Settings*' not in replies(octo, incoming)[0]['text']
    assert not octo.ai.answer_calls


async def test_unknown_selection_never_approves_cart(octo):
    await ask(octo, 'APPROVE ABCDEF0123', menu_choice_id='invalid')
    assert not octo.ai.answer_calls
    assert octo.store.db.execute('SELECT COUNT(*) FROM ux_preferences').fetchone()[0] == 0


async def test_group_menus_do_not_send_interactive_lists(octo):
    sent = await capture_menus(octo)
    await ask(octo, 'menu', chat_id='demo-class-5b@g.us', is_group=True)
    assert sent == []


async def test_send_list_uses_documented_waha_payload():
    menu = {'title': 'Octo', 'description': '1 · Today', 'button': 'Choose',
            'sections': [{'title': 'Choose', 'rows': [{'title': 'Today', 'rowId': 'octo:0123456789abcdef:1'}]}]}
    def handler(request):
        assert request.url.path == '/api/sendList'
        assert json.loads(request.content) == {'session': 'default', 'chatId': '919000000001@c.us', 'message': menu, 'reply_to': 'incoming'}
        return httpx.Response(200, json={'id': 'sent-menu'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        waha = WahaClient('http://localhost:3000', 'fake', 'default', client=client)
        assert await waha.send_menu('919000000001@c.us', '1 · Today', menu, reply_to='incoming') == 'sent-menu'


@pytest.mark.parametrize('status', [400, 404, 405, 422, 501])
async def test_definite_list_rejection_falls_back_to_text(status):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(status, json={}) if len(paths) == 1 else httpx.Response(200, json={'id': 'fallback'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        waha = WahaClient('http://localhost:3000', 'fake', 'default', client=client)
        assert await waha.send_menu('919000000001@c.us', 'menu text', {}) == 'fallback'
    assert paths == ['/api/sendList', '/api/sendText']


@pytest.mark.parametrize('failure', ['timeout', 'server_error', 'missing_id'])
async def test_uncertain_list_delivery_never_sends_again(failure):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic timeout', request=request)
        return httpx.Response(500 if failure == 'server_error' else 200, json={})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        waha = WahaClient('http://localhost:3000', 'fake', 'default', client=client)
        if failure == 'missing_id':
            assert await waha.send_menu('919000000001@c.us', 'menu text', {}) is None
        else:
            with pytest.raises(httpx.HTTPError):
                await waha.send_menu('919000000001@c.us', 'menu text', {})
    assert paths == ['/api/sendList']
