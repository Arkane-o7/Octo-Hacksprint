"""Run the complete routing/storage flow with explicitly synthetic inputs."""
import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .contracts import IncomingMessage, Media
from .core import Octo, Roster, OFFLINE
from .offline import OfflineAI, OfflineTransport
from .storage import Store


async def drain(octo):
    for _ in range(30):
        if not await octo.tick():
            return
    raise RuntimeError('Replay did not become idle.')


async def replay():
    print(OFFLINE)
    print('No API calls, WhatsApp delivery, image recognition or speech generation occur.\n')
    with tempfile.TemporaryDirectory(prefix='octo-offline-') as directory:
        settings = Settings(data_dir=Path(directory), poll_seconds=0)
        store = Store(settings.data_dir / 'replay.sqlite3')
        transport = OfflineTransport()
        octo = Octo(settings, store, Roster(settings.roster_path), OfflineAI(), transport)
        common = dict(session='default', timestamp=datetime.now(timezone.utc))
        notices = [
            IncomingMessage(**common, message_id='fixture-requirement', chat_id='demo-class-5b@g.us', sender_id='demo-teacher', is_group=True, text='Bring crayons and a drawing book tomorrow.'),
            IncomingMessage(**common, message_id='fixture-photo', chat_id='demo-class-5b@g.us', sender_id='demo-teacher', is_group=True, kind='image', text='Science test syllabus', media=Media(url='fixture://board-clear', mime_type='image/jpeg')),
            IncomingMessage(**common, message_id='fixture-question', chat_id='demo-parent-a', sender_id='demo-parent-a', kind='voice', media=Media(url='fixture://parent-hindi', mime_type='audio/ogg')),
        ]
        for event in notices:
            assert await octo.ingest(event) == 'queued'
            await drain(octo)
        assert store.counts()['facts'] == 2
        assert await octo.ingest(notices[0]) == 'duplicate'
        for reply in transport.sent:
            print(f"TO {reply['chat_id']}\n{reply['text']}\n")
        assert all(row['status'] == 'fixture' for row in store.replies())
        store.close()
        # Confirm saved data survives opening a new process/connection.
        reopened = Store(settings.data_dir / 'replay.sqlite3')
        assert reopened.counts()['facts'] == 2
        reopened.close()
        print('PASS — synthetic text/photo/voice routing, source references, deduplication and restart.\nLive OCR, STT, TTS and WhatsApp remain untested.')


if __name__ == '__main__':
    asyncio.run(replay())
