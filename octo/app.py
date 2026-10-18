"""Run one worker: uv run uvicorn octo.app:app --host 0.0.0.0 --port 8018."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request

from .config import Settings
from .core import Octo, Roster
from .drive import GoogleDriveClient
from .calendar import GoogleCalendarClient
from .offline import OfflineAI, OfflineTransport
from .sarvam import SarvamClient
from .storage import Store
from .waha import WahaClient, normalize, verify_signature


def create_app(settings: Settings | None = None, *, ai=None, transport=None, drive=None, calendar=None, worker=True):
    @asynccontextmanager
    async def lifespan(app):
        config = settings or Settings.from_env()
        config.check_live()
        roster = Roster(config.roster_path, live=config.mode == 'live')
        store = Store(config.data_dir / config.mode / 'octo.sqlite3', key=config.db_key if config.mode == 'live' else '')
        model = ai or (OfflineAI() if config.mode == 'offline' else SarvamClient(
            config.sarvam_api_key, base_url=config.sarvam_base_url,
            chat_model=config.chat_model, stt_model=config.stt_model,
            tts_model=config.tts_model, document_language=config.document_language))
        messenger = transport or (OfflineTransport() if config.mode == 'offline' else WahaClient(
            config.waha_base_url, config.waha_api_key, config.waha_session))
        documents = drive or (GoogleDriveClient(config.drive_credentials_path, config.drive_root_folder_id) if config.mode == 'live' else None)
        schedule = calendar or (GoogleCalendarClient(config.calendar_credentials_path, config.calendar_id) if config.mode == 'live' else None)
        app.state.octo = Octo(config, store, roster, model, messenger, drive=documents, calendar=schedule)
        app.state.octo.queue_calendar_sync()
        task = asyncio.create_task(app.state.octo.run()) if worker else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await model.close()
            await messenger.close()
            if documents:
                await documents.close()
            if schedule:
                await schedule.close()
            store.close()

    app = FastAPI(title='Octo demo', lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get('/health')
    async def health(request: Request):
        octo = request.app.state.octo
        return {'status': 'ok', 'mode': octo.settings.mode,
                'parent_access': 'group_members_only',
                'interaction_mode': 'conversation',
                'conversation_context_enabled': True,
                'general_brain_enabled': octo.settings.general_brain,
                'calendar_configured': bool(octo.calendar and octo.calendar.configured),
                'calendar_short_links_enabled': octo.calendar_links.enabled,
                'external_integrations_verified': False,
                'note': 'Local app health only; does not establish WhatsApp/Sarvam availability.'}

    @app.post('/webhooks/waha')
    async def webhook(request: Request):
        octo = request.app.state.octo
        if octo.settings.mode != 'live':
            raise HTTPException(409, 'OFFLINE DEMO: webhook disabled. Use python -m octo.replay.')
        # Bound the body before JSON parsing. Media arrives separately through WAHA.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise HTTPException(413, 'Webhook exceeds the demo size limit.')
        if request.headers.get('x-webhook-hmac-algorithm', '').lower() != 'sha512' or not verify_signature(
            bytes(body), request.headers.get('x-webhook-hmac', ''), octo.settings.webhook_secret,
        ):
            raise HTTPException(401, 'Invalid webhook signature.')
        try:
            event = normalize(json.loads(body))
        except (ValueError, TypeError):
            raise HTTPException(400, 'Malformed incoming message.') from None
        if event is None:
            return {'status': 'ignored'}
        status = await octo.ingest(event)
        logging.getLogger(__name__).info('Webhook message outcome: %s', status)
        if status == 'unavailable':
            # WAHA can retry the original message instead of silently losing it.
            raise HTTPException(503, 'Group membership temporarily unavailable.', headers={'Retry-After': '30'})
        return {'status': status}

    return app


logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
# httpx info messages include request URLs. Keep normal logs minimal.
logging.getLogger('httpx').setLevel(logging.WARNING)
app = create_app()
