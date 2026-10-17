"""Explicit live Sarvam checks with synthetic inputs and LOCAL captured delivery.

Run: uv run python scripts/live_acceptance.py --live-apis
Never sends WhatsApp, uploads to Google, or touches the live SQLite database.
"""
import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from octo.config import Settings
from octo.contracts import IncomingMessage, Media
from octo.core import Octo, Roster
from octo.sarvam import SarvamClient
from octo.storage import Store


class Capture:
    def __init__(self): self.messages = []
    async def send_text(self, chat_id, text, reply_to=None):
        self.messages.append({'chat': chat_id, 'text': text})
        return 'LOCAL-CAPTURE-NOT-WHATSAPP'
    async def send_voice(self, chat_id, path):
        self.messages.append({'chat': chat_id, 'audio_bytes': path.stat().st_size})
        return 'LOCAL-CAPTURE-NOT-WHATSAPP'


async def main():
    config = Settings.from_env()
    if not config.sarvam_api_key: raise SystemExit('Configure SARVAM_API_KEY locally.')
    output = Path('data/validation') / datetime.now().date().isoformat() / 'integrated-live-api.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'mode': 'REAL SARVAM APIs; synthetic school inputs; isolated temporary DB; no WhatsApp/Google calls', 'checks': []}
    output.write_text(json.dumps(report, indent=2))
    ai = SarvamClient(config.sarvam_api_key, chat_model=config.chat_model, stt_model=config.stt_model, tts_model=config.tts_model)
    try:
        with tempfile.TemporaryDirectory(prefix='octo-live-api-check-') as temp:
            root = Path(temp)
            app = Octo(Settings(mode='live', data_dir=root, poll_seconds=0, general_brain=True), Store(root/'check.sqlite3'), Roster(Path('roster.example.json')), ai, Capture())
            now = datetime.now(timezone.utc)
            first = (now + timedelta(days=2)).date().isoformat()
            later = (now + timedelta(days=3)).date().isoformat()
            async def message(identifier, text='', *, parent=False, voice=None):
                event = IncomingMessage(session='default', message_id=identifier,
                    chat_id='demo-parent-a' if parent else 'demo-class-5b@g.us',
                    sender_id='demo-parent-a' if parent else 'demo-teacher', is_group=not parent,
                    timestamp=datetime.now(timezone.utc), text=text,
                    kind='voice' if voice else 'text', media=Media(local_path=str(voice), mime_type='audio/ogg') if voice else None)
                before = len(app.transport.messages)
                await app.ingest(event)
                row = app.store.next_message()
                await app.process(row)
                while await app.deliver_one(): pass
                saved = app.store.message(event.source_key)
                if saved['status'] != 'done': raise AssertionError({'status':saved['status'], 'error':saved.get('error'), 'replies':app.transport.messages[before:]})
                return saved['source_id'], app.transport.messages[before:]
            def facts(): return app.store.class_facts('5B')
            async def check(name, action):
                started = time.monotonic()
                try:
                    detail = await action()
                    result = {'name':name, 'pass':True, 'detail':detail}
                except Exception as exc:
                    result = {'name':name, 'pass':False, 'error':str(exc)[:1500], 'type':type(exc).__name__}
                result['seconds'] = round(time.monotonic()-started, 2)
                report['checks'].append(result)
                report['captured_replies'] = app.transport.messages
                report['current_facts'] = facts()
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                print(('PASS' if result['pass'] else 'FAIL'), name, result['seconds'], flush=True)
            async def greeting():
                _, replies = await message('greeting','hi')
                assert not facts() and replies
                return replies
            async def requirement():
                sid, replies = await message('supplies',f'Please bring crayons and a drawing book on {first}.')
                saved = next(f for f in facts() if f['source_id']==sid)['extraction']
                assert 'crayon' in str(saved['items']).lower() and 'drawing' in str(saved['items']).lower()
                assert saved['due_date']==first
                assert app.store.db.execute('SELECT count(*) FROM reminders').fetchone()[0] >= 2
                return replies
            async def cancellation():
                old, _ = await message('football',f'Football practice on {first} at 4 pm on the school field.')
                assert any(f['source_id']==old for f in facts()), 'Activity not saved'
                sid, replies = await message('cancel',f'{first} wali football practice cancel hai.')
                current = next(f for f in facts() if f['source_id']==sid)['extraction']
                assert current['status']=='cancelled' and current['replaces_source_ids']==[old]
                assert all(r[0]=='cancelled' for r in app.store.db.execute('SELECT status FROM reminders WHERE source_id=?',(old,)))
                assert not any(f['source_id']==old for f in facts())
                return replies
            async def postponement():
                old, _ = await message('science',f'Science test on {first}. Study Chapter 6, roots and stems, pages 42 to 47.')
                before = [f for f in facts() if f['source']['message_id']=='science']
                assert before
                sid, replies = await message('postpone',f'The Science test scheduled for {first} is postponed to {later}. Syllabus stays the same.')
                current = [f for f in facts() if f['extraction'].get('subject')=='Science']
                assert any(f['extraction']['due_date']==later and f['extraction']['replaces_source_ids'] for f in current)
                assert 'roots' in json.dumps([f['extraction'] for f in current]).lower() and '42' in json.dumps([f['extraction'] for f in current]), 'Updated syllabus content was lost'
                assert not any(f['extraction']['due_date']==first and f['extraction']['status']=='active' and f['extraction'].get('kind')=='test' for f in current)
                return replies
            async def ambiguity():
                await message('two-practices',f'Cricket practice on {later} at 4 pm. Football practice on {later} at 5 pm.')
                before = facts()
                _, replies = await message('ambiguous','Cancel practice.')
                assert facts()==before, 'Ambiguous update changed records'
                assert any('?' in r.get('text','') or 'clarif' in r.get('text','').lower() for r in replies), 'No clarification offered'
                return replies
            async def grounded():
                _, replies = await message('question',f'What must Aarav bring on {first}, and what should he study for the next Science test?', parent=True)
                result = '\n'.join(r.get('text','') for r in replies)
                assert 'Sources:' in result and '[' in result
                return replies
            async def cart():
                _, replies = await message('cart','Prepare a simulated stationery cart for the crayons and drawing book Aarav needs.', parent=True)
                text = '\n'.join(r.get('text','') for r in replies)
                match = re.search(r'APPROVE ([A-F0-9]{10})',text)
                assert match and 'INR 140.00' in text, 'No exact-price cart offered'
                code = match[1]
                _, answer = await message('approve','APPROVE '+code,parent=True)
                assert 'No order was placed' in str(answer)
                _, repeated = await message('replay-approval','APPROVE '+code,parent=True)
                assert 'unavailable' in str(repeated)
                return {'proposal':replies,'approval':answer,'replay':repeated}
            async def reminder():
                # Accelerated timer in isolated DB; nothing delivered to WhatsApp.
                with app.store.db: app.store.db.execute("UPDATE reminders SET due_at=? WHERE status='pending'",(time.time()-1,))
                count=0
                while await app.remind_one(): count+=1
                assert count>0
                pending=[r for r in app.store.replies() if r['dedupe_key'].startswith('reminder:')]
                assert pending and all('cancelled' not in r['text'].lower() for r in pending)
                assert not await app.remind_one()
                return {'local_reminders':count,'no_whatsapp':True}
            async def speech():
                # Machine-generated Hindi speech is explicitly not a human voice-note test.
                src=await ai.synthesize('आरव को विज्ञान के अगले टेस्ट के लिए क्या पढ़ना है?', 'hi-IN',root/'question.mp3')
                ogg=root/'question.ogg'
                subprocess.run(['ffmpeg','-v','error','-i',str(src),'-c:a','libopus',str(ogg)],check=True,capture_output=True)
                _, replies=await message('voice-question',parent=True,voice=ogg)
                assert any(r.get('audio_bytes',0)>1000 for r in replies), 'No synthesized response'
                return {'generated_input':True,'captured_replies':replies}
            async def document():
                source = Path('data/validation/2026-10-17/printed-syllabus-api-test.pdf')
                if not source.exists(): raise AssertionError('Labelled printed PDF sample unavailable')
                target = root/'printed-synthetic.pdf'
                target.write_bytes(source.read_bytes())
                event = IncomingMessage(session='default', message_id='synthetic-pdf',
                    chat_id='demo-class-5b@g.us', sender_id='demo-teacher', is_group=True,
                    timestamp=datetime.now(timezone.utc), kind='document',
                    media=Media(local_path=str(target), mime_type='application/pdf', filename='synthetic-science.pdf'))
                await app.ingest(event)
                await app.process(app.store.next_message())
                deadline = time.monotonic()+90
                while time.monotonic()<deadline:
                    job = app.store.due_job()
                    if job: await app.poll_job(job)
                    state = app.store.message(event.source_key)
                    if state['status'] in ('done','failed'): break
                    await asyncio.sleep(2)
                assert app.store.message(event.source_key)['status']=='done'
                extracted = [f['extraction'] for f in facts() if f['source']['message_id']=='synthetic-pdf']
                assert extracted and any(r['sections'] for r in extracted)
                info=app.store.document(event.source_key)
                assert info['url'] is None and 'not configured' in info['message']
                return {'actual_ocr':True,'synthetic_printed_input':True,'drive_upload':False,'metadata':info}
            for name, action in [('greeting',greeting),('requirements and scheduling',requirement),('Hinglish cancellation',cancellation),('postponement with syllabus retained',postponement),('ambiguous cancellation',ambiguity),('grounded parent answer',grounded),('simulated approval and replay rejection',cart),('accelerated reminder capture',reminder),('generated Hindi speech to grounded text and TTS',speech),('PDF OCR and honest unconfigured Drive result',document)]:
                await check(name,action)
            app.store.close()
    finally: await ai.close()
    print('Evidence:', output)
    return all(c['pass'] for c in report['checks'])

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-apis',action='store_true',help='Authorize real Sarvam API requests on synthetic inputs; never WhatsApp or Google')
    if not parser.parse_args().live_apis: parser.error('--live-apis is required')
    raise SystemExit(0 if asyncio.run(main()) else 1)
