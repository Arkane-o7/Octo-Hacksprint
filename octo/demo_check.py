"""Read-only demo preflight. No messages, Sarvam calls, or Google writes."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import quote

import httpx
from dotenv import dotenv_values
from sqlcipher3 import dbapi2 as cipher

from .config import Settings
from .database import validate_key
from .waha import WahaClient


def database_status(config):
    """Open the existing encrypted database without Store's startup recovery."""
    path = (config.data_dir / 'live' / 'octo.sqlite3').resolve()
    if not path.is_file():
        raise ValueError('Missing live database')
    validate_key(config.db_key)
    db = cipher.connect('file:' + quote(str(path), safe='/') + '?mode=ro', uri=True)
    try:
        db.execute(f'''PRAGMA key = "x'{config.db_key}'"''')
        db.execute('PRAGMA query_only=ON')
        return {
            table: dict(db.execute(f'SELECT status, COUNT(*) FROM {table} GROUP BY status'))
            for table in ('inbox', 'outbox', 'calendar_jobs')
        }
    finally:
        db.close()


async def check(config, app_url='http://127.0.0.1:8018', *, client=None):
    results = []

    def add(name, status, detail):
        results.append({'check': name, 'status': status, 'detail': detail})

    try:
        config.check_live()
        if config.mode != 'live':
            raise ValueError('Not live mode')
        add('Configuration', 'PASS', 'Live configuration present; credentials are not displayed.')
    except ValueError:
        add('Configuration', 'FAIL', 'Live configuration is incomplete. Run octo.setup check locally.')
        return results

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10, follow_redirects=False)
    try:
        try:
            response = await client.get(app_url.rstrip('/') + '/health')
            response.raise_for_status()
            health = response.json()
            ready = health.get('status') == 'ok' and health.get('mode') == 'live'
            add('App', 'PASS' if ready else 'FAIL', 'Live worker responds.' if ready else 'Worker is not healthy in live mode.')
            add('Parent access', 'PASS' if health.get('parent_access') == 'group_members_only' else 'FAIL', 'Current group membership is required.')
            add('Conversation UX', 'PASS' if health.get('interaction_mode') == 'conversation' else 'FAIL', 'Natural conversation mode is enabled.')
            add('Conversation context', 'PASS' if health.get('conversation_context_enabled') else 'FAIL', 'Recent and quoted-message context is enabled.')
            add('Stable parser', 'WARN' if health.get('general_brain_enabled') else 'PASS',
                'Experimental parser enabled.' if health.get('general_brain_enabled') else 'Established notice parser enabled.')
        except (httpx.HTTPError, ValueError, AttributeError):
            add('App', 'FAIL', 'Cannot read healthy app status. Check the single worker on port 8018.')

        try:
            url = config.waha_base_url.rstrip('/') + '/api/sessions/' + quote(config.waha_session, safe='')
            response = await client.get(url, headers={'X-Api-Key': config.waha_api_key})
            response.raise_for_status()
            working = response.json().get('status') == 'WORKING'
            add('WhatsApp', 'PASS' if working else 'FAIL', 'Session WORKING.' if working else 'Session is not WORKING; check the dedicated account.')
        except (httpx.HTTPError, ValueError, AttributeError):
            add('WhatsApp', 'FAIL', 'WAHA session could not be verified.')

        try:
            roster = json.loads(config.roster_path.read_text())
            groups = roster['groups']
            if not isinstance(groups, dict) or not groups:
                raise ValueError('No configured groups')
            transport = WahaClient(config.waha_base_url, config.waha_api_key, config.waha_session, client=client)
            for index, group in enumerate(groups, 1):
                members = await transport.group_members(group)
                add(f'Group {index}', 'PASS' if members else 'FAIL', f'{len(members)} current members resolved; identities omitted.')
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
            add('Group access', 'FAIL', 'Cannot verify configured group membership; parent replies may be blocked.')

        try:
            counts = database_status(config)
            add('Encrypted database', 'PASS', 'Existing live database opened read-only with SQLCipher.')
            for table, statuses in counts.items():
                active = sum(statuses.get(state, 0) for state in ('pending', 'processing', 'downloading', 'sending', 'syncing'))
                failed = sum(statuses.get(state, 0) for state in ('failed', 'uncertain'))
                status = 'WARN' if active or failed else 'PASS'
                add(table, status, f'{active} queued/in progress; {failed} failed/uncertain records (may include historical failures).')
        except (OSError, ValueError, cipher.Error):
            add('Encrypted database', 'FAIL', 'Cannot read the existing encrypted database. No recovery or changes attempted.')
        add('AI usage', 'NOTE', 'No Sarvam call or balance check performed. Live answers/OCR/speech consume existing API credits.')
        add('Handset check', 'NOTE', 'Ask a saved-school-notice question, then quote the answer with "explain this" on a member phone; service checks do not prove phone receipt.')
        return results
    finally:
        if owns_client:
            await client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, help='Use an existing environment file; resolve its relative paths beside that file.')
    parser.add_argument('--app-url', default='http://127.0.0.1:8018')
    args = parser.parse_args()
    if args.env_file:
        path = args.env_file.resolve()
        if not path.is_file():
            parser.error('Environment file does not exist.')
        values = {key: value for key, value in dotenv_values(path).items() if value is not None}
        for key, default in (('OCTO_DATA_DIR', 'data'), ('OCTO_ROSTER', 'roster.example.json'),
                             ('GOOGLE_DRIVE_CREDENTIALS', ''), ('GOOGLE_CALENDAR_CREDENTIALS', '')):
            value = values.get(key, default)
            if value and not Path(value).is_absolute():
                values[key] = str(path.parent / value)
        os.environ.update(values)
    try:
        config = Settings.from_env()
    except ValueError:
        parser.exit(1, 'Invalid local configuration. Credentials were not printed.\n')
    results = asyncio.run(check(config, args.app_url))
    print('Octo preflight: read-only, no messages or billable AI calls.\n')
    for result in results:
        print(f"{result['status']:4}  {result['check']}: {result['detail']}")
    raise SystemExit(1 if any(result['status'] == 'FAIL' for result in results) else 0)


if __name__ == '__main__':
    main()
