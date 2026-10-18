"""Text-only WhatsApp menus: scoped choices, preferences and offline UX flows."""
import json
import re
import time

import pytest

from octo.cart import CartService
from octo.contracts import Extraction, GroundedAnswer
from octo.menu_copy import COPY
from octo.storage import Store
from test_core import octo, notice, question, put, output


def replies(app, event):
    sid = app.store.message(event.source_key)['source_id']
    return [r for r in app.store.replies() if r['dedupe_key'].startswith(sid + ':')]


async def ask(app, text, **changes):
    identifier = str(app.store.counts()['inbox'] + 1)
    event = question(identifier, text=text, **changes)
    await put(app, event)
    return event


async def test_main_menu_then_question_then_sources(octo):
    await put(octo, notice())
    event = await ask(octo, 'menu')
    text = replies(octo, event)[0]['text']
    assert '1 · Today' in text and '4 · Settings' in text
    assert not octo.ai.answer_calls
    event = await ask(octo, '2')
    assert 'crayons' in replies(octo, event)[0]['text']
    assert '1 · Read aloud' in replies(octo, event)[0]['text']
    count = len(octo.ai.answer_calls)
    event = await ask(octo, '2')
    assert 'Saved sources' in replies(octo, event)[0]['text']
    assert len(octo.ai.answer_calls) == count
    assert replies(octo, event)[0]['reply_to'] == event.message_id


async def test_language_and_audio_settings_persist_after_restart(octo):
    await ask(octo, 'menu')
    await ask(octo, '4')
    await ask(octo, '1')
    event = await ask(octo, '2')
    assert 'पसंद सेव' in replies(octo, event)[0]['text']
    await ask(octo, '4')
    await ask(octo, '2')
    await ask(octo, '1')
    octo.store.close()
    octo.store = Store(octo.settings.data_dir / 'test.sqlite3')
    parent = octo.menus.preferences(question(), octo.roster.resolve(question()))
    assert parent['language'] == 'hi-IN'
    assert parent['voice_replies'] is False
    other = question(sender_id='demo-parent-b', chat_id='demo-parent-b')
    assert octo.menus.preferences(other, octo.roster.resolve(other))['language'] == 'ta-IN'
    await put(octo, notice())
    event = await ask(octo, 'What does Aarav need?')
    assert not any(r['dedupe_key'].endswith(':audio-status') for r in replies(octo, event))


async def test_preferences_opt_in_is_explicit_and_groups_still_quiet(octo):
    octo.roster.identities['demo-parent-a']['voice_replies'] = False
    await ask(octo, 'menu')
    await ask(octo, '4')
    await ask(octo, '2')
    await ask(octo, '2')
    parent = octo.menus.preferences(question(), octo.roster.resolve(question()))
    assert parent['voice_replies'] is True
    await put(octo, notice())
    event = await ask(octo, 'What does Aarav need?')
    assert any(r['dedupe_key'].endswith(':audio-status') for r in replies(octo, event))
    event = await ask(octo, 'What does the class need?', chat_id='demo-class-5b@g.us', is_group=True)
    assert all(r['kind'] == 'text' for r in replies(octo, event))
    assert not any('Read aloud' in r['text'] for r in replies(octo, event))


async def test_multiple_children_choose_only_current_linked_child(octo):
    await put(octo, notice())
    changes = dict(sender_id='demo-parent-b', chat_id='demo-parent-b')
    event = await ask(octo, 'What does my child need?', **changes)
    assert '1 · Meera' in replies(octo, event)[0]['text']
    assert '2 · Kabir' in replies(octo, event)[0]['text']
    assert not octo.ai.answer_calls
    await ask(octo, '1', **changes)
    assert octo.ai.answer_calls[-1][1] == ['Meera']
    assert all(f['class_id'] == '5B' for f in octo.ai.answer_calls[-1][0])


async def test_child_selection_invalidates_when_roster_scope_changes(octo):
    await ask(octo, 'What does my child need?', sender_id='demo-parent-b', chat_id='demo-parent-b')
    octo.roster.identities['demo-parent-b']['student_ids'] = ['kabir']
    event = await ask(octo, '1', sender_id='demo-parent-b', chat_id='demo-parent-b')
    assert not octo.ai.answer_calls
    assert not any('Meera' in r['text'] for r in replies(octo, event))


async def test_choice_is_scoped_to_person_and_chat(octo):
    await ask(octo, 'menu')
    event = await ask(octo, '1', sender_id='demo-parent-b', chat_id='demo-parent-b')
    assert not octo.ai.answer_calls
    assert '1 · இன்று' in replies(octo, event)[0]['text']
    event = await ask(octo, '1', chat_id='demo-class-5b@g.us', is_group=True)
    assert 'private chat' in replies(octo, event)[0]['text'] or 'निजी चैट' in replies(octo, event)[0]['text']
    assert not octo.ai.answer_calls


@pytest.mark.parametrize('change', ['expired', 'uncertain'])
async def test_expired_or_unconfirmed_menu_never_executes_choice(octo, change):
    await ask(octo, 'menu')
    with octo.store.db:
        if change == 'expired':
            octo.store.db.execute('UPDATE ux_menus SET expires=?', (time.time() - 1,))
        else:
            octo.store.db.execute("UPDATE outbox SET status='uncertain'")
    event = await ask(octo, '1')
    assert not octo.ai.answer_calls
    assert '1 ·' in replies(octo, event)[0]['text']


async def test_number_choice_survives_restart_without_reinterpretation(octo):
    await ask(octo, 'menu')
    event = await ask(octo, '4')
    row = octo.store.message(event.source_key)
    original = replies(octo, event)
    octo.store.close()
    octo.store = Store(octo.settings.data_dir / 'test.sqlite3')
    await octo.process(row)
    assert replies(octo, event) == original
    event = await ask(octo, '1')
    assert 'Menu language' in replies(octo, event)[0]['text']


async def test_stale_or_forwarded_quote_cannot_change_preferences(octo):
    await ask(octo, 'menu')
    await ask(octo, '4')
    await ask(octo, '2')
    await ask(octo, '1', quoted_message_id='unrelated-message', is_quoted=True)
    await ask(octo, '1', forwarded=True)
    assert octo.store.db.execute('SELECT COUNT(*) FROM ux_preferences').fetchone()[0] == 0


async def test_reply_quoting_current_confirmed_menu_works(octo):
    event = await ask(octo, 'menu')
    reply = replies(octo, event)[0]
    with octo.store.db:
        octo.store.db.execute("UPDATE outbox SET remote_id='current-menu' WHERE id=?", (reply['id'],))
    event = await ask(octo, '4', quoted_message_id='current-menu', is_quoted=True)
    assert '*Settings*' in replies(octo, event)[0]['text']


async def test_read_aloud_uses_saved_answer_no_new_model_call_or_duplicate_audio(octo):
    await put(octo, notice())
    await ask(octo, 'What does Aarav need tomorrow?')
    octo.settings.mode = 'live'  # Synthetic injected AI and transport only.
    calls = []
    async def synthesize(text, language, path):
        calls.append(text)
        path.write_text('synthetic audio fixture')
        return path
    octo.ai.synthesize = synthesize
    event = question('read', text='1')
    assert octo.accept(event) == 'queued'
    row = octo.store.next_message()
    await octo.process(row)
    await octo.process(row)
    assert len(calls) == 1
    assert 'crayons' in calls[0] and 'Read aloud' not in calls[0]
    assert len(octo.ai.answer_calls) == 1
    assert len(replies(octo, event)) == 1
    assert replies(octo, event)[0]['kind'] == 'voice'


async def test_changed_fact_blocks_old_sources_and_audio(octo):
    await put(octo, notice())
    await ask(octo, 'What does Aarav need tomorrow?')
    with octo.store.db:
        extraction = json.loads(octo.store.db.execute('SELECT extraction FROM facts').fetchone()[0])
        extraction['items'] = ['pencils']
        octo.store.db.execute('UPDATE facts SET extraction=?', (json.dumps(extraction),))
    event = await ask(octo, '1')
    assert 'no longer current' in replies(octo, event)[0]['text']
    assert not any(r['kind'] == 'voice' for r in replies(octo, event))


async def test_show_sources_only_reveals_saved_verified_links_on_request(octo):
    await put(octo, notice())
    row = octo.store.db.execute('SELECT source_id,provenance FROM facts').fetchone()
    source = json.loads(row['provenance'])
    source['calendar'] = {'status': 'synced', 'url': 'https://calendar.google.com/calendar/event?eid=synthetic'}
    with octo.store.db:
        octo.store.db.execute('UPDATE facts SET provenance=?', (json.dumps(source),))
    event = await ask(octo, 'What does Aarav need tomorrow?')
    assert source['calendar']['url'] not in replies(octo, event)[0]['text']
    event = await ask(octo, '2')
    assert source['calendar']['url'] in replies(octo, event)[0]['text']


async def test_number_cannot_approve_cart_or_create_one_from_model_proposal(octo):
    service = CartService(octo.store.db)
    proposal = service.propose('parent-a', 'demo-parent-a', ['crayons'])
    code = re.search(r'APPROVE ([A-F0-9]{10})', proposal)[1]
    await put(octo, notice())
    source = octo.store.db.execute('SELECT source_id FROM facts').fetchone()[0]
    octo.ai.answer_override = GroundedAnswer(text='Bring crayons', language_code='en-IN',
        source_ids=[source], proposed_items=['crayons'], cart_request_quote='saved school notices')
    await ask(octo, 'menu')
    await ask(octo, '1')
    assert octo.store.db.execute('SELECT COUNT(*) FROM carts').fetchone()[0] == 1
    assert octo.store.db.execute('SELECT status FROM carts WHERE code=?', (code,)).fetchone()[0] == 'pending'


async def test_revoked_member_menu_choice_is_ignored(octo):
    await ask(octo, 'menu')
    octo.roster.memberships.clear()
    assert await octo.ingest(question('revoked', text='1')) == 'ignored'
    assert not octo.ai.answer_calls


async def test_freeform_question_exits_previous_menu(octo):
    await put(octo, notice())
    await ask(octo, 'menu')
    await ask(octo, '4')
    event = await ask(octo, 'What does Aarav need tomorrow?')
    assert 'crayons' in replies(octo, event)[0]['text']
    assert octo.ai.answer_calls


def test_menu_copy_has_matching_keys_and_no_purchase_action():
    assert all(set(value) == set(COPY['en']) for value in COPY.values())
    assert 'APPROVE' not in json.dumps(COPY)


async def test_read_aloud_failure_preserves_answer_and_does_not_claim_success(octo):
    await put(octo, notice())
    previous = await ask(octo, 'What does Aarav need tomorrow?')
    original = replies(octo, previous)
    octo.settings.mode = 'live'
    octo.ai.tts_fails = True
    event = await ask(octo, '1')
    assert replies(octo, previous) == original
    assert 'audio is unavailable' in replies(octo, event)[0]['text']
    assert all(r['kind'] == 'text' for r in replies(octo, event))


async def test_notes_menu_requests_saved_document_link_without_model_hint(octo):
    await put(octo, notice())
    source = json.loads(octo.store.db.execute('SELECT provenance FROM facts').fetchone()[0])
    source['document'] = {'status': 'uploaded', 'url': 'https://drive.google.com/file/d/synthetic/view'}
    with octo.store.db:
        octo.store.db.execute('UPDATE facts SET provenance=?', (json.dumps(source),))
    await ask(octo, 'வணக்கம்')
    event = await ask(octo, '3')
    assert source['document']['url'] in replies(octo, event)[0]['text']


async def test_voice_number_does_not_change_preference(octo):
    from octo.contracts import Media
    await ask(octo, 'menu')
    await ask(octo, '4')
    await ask(octo, '2')
    event = question('spoken-choice', kind='voice', text='1', media=Media(url='fixture://parent-hindi', mime_type='audio/ogg'))
    assert await octo.ingest(event) == 'queued'
    sid = octo.store.message(event.source_key)['source_id']
    octo.store.update(sid, transcript='1')
    await octo.process(octo.store.next_message())
    assert octo.store.db.execute('SELECT COUNT(*) FROM ux_preferences').fetchone()[0] == 0


async def test_menu_data_uses_existing_encrypted_database(octo):
    path = octo.settings.data_dir / 'encrypted.sqlite3'
    octo.store.close()
    octo.store = Store(path, key='ab' * 32)
    from octo.menus import Menus
    octo.menus = Menus(octo)
    await ask(octo, 'menu')
    await ask(octo, '4')
    await ask(octo, '2')
    await ask(octo, '1')
    for file in path.parent.glob('encrypted.sqlite3*'):
        assert b'voice_replies' not in file.read_bytes()
        assert b'ux_menu_inputs' not in file.read_bytes()
    octo.store.close()
    octo.store = Store(path, key='ab' * 32)
    assert octo.menus.preferences(question(), octo.roster.resolve(question()))['voice_replies'] is False
