"""User-run desktop OAuth setup for an app-created demo folder and calendar.

Run: uv run python -m octo.google_setup --client-secret data/google-client.json
No accounts are connected until the user runs this and accepts Google's consent.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
from contextlib import closing
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, quote

import httpx
from dotenv import set_key

SCOPES = ('https://www.googleapis.com/auth/drive.file',
          'https://www.googleapis.com/auth/calendar.app.created')
TOKEN_URL = 'https://oauth2.googleapis.com/token'
DRIVE_URL = 'https://www.googleapis.com/drive/v3/files'
CALENDAR_URL = 'https://www.googleapis.com/calendar/v3/calendars'


from .database import connect


class SetupError(RuntimeError):
    pass


def save_private(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    temporary.replace(path)


def request_json(client, method, url, **kwargs):
    try:
        response = client.request(method, url, follow_redirects=False, timeout=30, **kwargs)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, dict):
            return result
    except (httpx.HTTPError, ValueError):
        pass
    raise SetupError('Google did not confirm the request. Check enabled APIs, consent/test users, and local credentials. No provider body or token is printed.')


def make_authorization(client_id, redirect_uri):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(32)
    url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code',
        'scope': ' '.join(SCOPES), 'state': state, 'code_challenge': challenge,
        'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent',
    })
    return url, state, verifier


def callback_values(path, expected_state):
    parsed = urlsplit(path)
    query = parse_qs(parsed.query)
    state = query.get('state', [])
    if parsed.path != '/callback' or len(state) != 1 or not hmac.compare_digest(state[0], expected_state):
        return None
    if query.get('error'):
        return {'error': 'Consent was declined. No account was connected.'}
    codes = query.get('code', [])
    return {'code': codes[0]} if len(codes) == 1 and codes[0] else None


def authorize(secret_path, credentials_path, client):
    try:
        installed = json.loads(secret_path.read_text())['installed']
        client_id, client_secret = installed['client_id'], installed['client_secret']
        if not isinstance(client_id, str) or not isinstance(client_secret, str):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise SetupError('Download a Desktop app OAuth client JSON and save it as data/google-client.json.') from None
    outcome = {}
    expected_state = ''

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # OAuth codes and state must never enter terminal logs.

        def do_GET(self):
            result = callback_values(self.path, expected_state)
            if result:
                outcome.update(result)
            self.send_response(200 if result else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(b'Return to the Octo terminal to finish setup.' if result else b'Invalid OAuth callback.')

    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        redirect = f'http://127.0.0.1:{server.server_port}/callback'
        url, expected_state, verifier = make_authorization(client_id, redirect)
        print('Opening your browser. Choose the demo Google account and allow both requested scopes.')
        if not webbrowser.open(url):
            print('Open this authorization link in your normal browser:\n' + url)
        deadline = time.monotonic() + 600
        server.timeout = .5
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if 'code' not in outcome:
        raise SetupError(outcome.get('error', 'OAuth timed out. Run this command again when ready.'))
    tokens = request_json(client, 'POST', TOKEN_URL, data={
        'client_id': client_id, 'client_secret': client_secret, 'code': outcome['code'],
        'code_verifier': verifier, 'redirect_uri': redirect, 'grant_type': 'authorization_code',
    })
    if not tokens.get('refresh_token') or not set(SCOPES) <= set(tokens.get('scope', '').split()):
        raise SetupError('Both Drive-file and app-created Calendar access are required. Rerun and allow both scopes.')
    credentials = {'client_id': client_id, 'client_secret': client_secret,
                   'refresh_token': tokens['refresh_token'], 'scopes': list(SCOPES)}
    save_private(credentials_path, credentials)
    return credentials


def provision(client, credentials, resources_path):
    """Create once; a lost create response is not blindly repeated."""
    token = request_json(client, 'POST', TOKEN_URL, data={
        **{k: credentials[k] for k in ('client_id', 'client_secret', 'refresh_token')},
        'grant_type': 'refresh_token',
    })
    if not isinstance(token.get('access_token'), str) or not token['access_token']:
        raise SetupError('Google did not return an access token. Rerun with --reauthorize.')
    headers = {'Authorization': 'Bearer ' + token['access_token']}
    resources = json.loads(resources_path.read_text()) if resources_path.exists() else {}
    for kind, url, body in (
        ('drive_folder', DRIVE_URL, {'name': 'Octo Demo', 'mimeType': 'application/vnd.google-apps.folder'}),
        ('calendar', CALENDAR_URL, {'summary': 'Octo Demo', 'timeZone': 'Asia/Kolkata',
                                  'description': 'Fictional class-wide Octo demo notices. No student-private records.'}),
    ):
        saved = resources.get(kind, {})
        if saved.get('status') == 'creating':
            raise SetupError(f'A previous {kind} create is unconfirmed. Check Google before retrying; no duplicate was created. See GOOGLE_SETUP.md recovery.')
        if saved.get('id'):
            request_json(client, 'GET', url + '/' + quote(saved['id'], safe=''), headers=headers)
            continue
        resources[kind] = {'status': 'creating'}
        save_private(resources_path, resources)
        result = request_json(client, 'POST', url, headers=headers, json=body)
        identifier = result.get('id')
        if not isinstance(identifier, str) or not identifier:
            raise SetupError(f'Google did not confirm a {kind} ID. Check Google before retrying.')
        if kind == 'calendar' and not identifier.endswith('@group.calendar.google.com'):
            raise SetupError('Google did not return a secondary calendar. Check setup before continuing.')
        resources[kind] = {'status': 'created', 'id': identifier}
        save_private(resources_path, resources)
    return resources


def retry_calendar_jobs(data_dir, calendar_id, db_key=""):
    database = data_dir / 'live' / 'octo.sqlite3'
    if not calendar_id or not database.is_file():
        return 0
    with closing(connect(database, db_key)) as connection, connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='calendar_jobs'").fetchone():
            return 0
        return connection.execute("UPDATE calendar_jobs SET status='pending',attempts=0,next_attempt=0,error=NULL WHERE calendar_id=? AND status='failed'", (calendar_id,)).rowcount


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-secret', type=Path, default=Path('data/google-client.json'))
    parser.add_argument('--reauthorize', action='store_true')
    parser.add_argument('--retry-calendar', action='store_true', help='Retry exhausted local Calendar jobs after fixing access; no OAuth browser is opened.')
    args = parser.parse_args()
    credentials_path = Path('data/google-oauth.json')
    try:
        if args.retry_calendar:
            from .config import Settings
            settings = Settings.from_env()
            count = retry_calendar_jobs(settings.data_dir, settings.calendar_id, settings.db_key)
            print(f'Queued {count} failed Calendar jobs for the running worker. No Google write has been confirmed by this command.')
            return
        with httpx.Client() as client:
            if credentials_path.exists() and not args.reauthorize:
                credentials = json.loads(credentials_path.read_text())
                if not set(SCOPES) <= set(credentials.get('scopes', [])):
                    raise SetupError('Existing credentials lack the requested scope metadata. Run again with --reauthorize.')
            else:
                credentials = authorize(args.client_secret, credentials_path, client)
            print('Creating or verifying a dedicated Octo Demo Drive folder and secondary calendar.')
            resources = provision(client, credentials, Path('data/google-resources.json'))
        if not Path('.env').exists():
            Path('.env').touch(mode=0o600)
        for key, value in {
            'GOOGLE_DRIVE_CREDENTIALS': str(credentials_path),
            'GOOGLE_CALENDAR_CREDENTIALS': str(credentials_path),
            'GOOGLE_DRIVE_FOLDER_ID': resources['drive_folder']['id'],
            'GOOGLE_CALENDAR_ID': resources['calendar']['id'],
        }.items():
            set_key('.env', key, value)
        print('Setup complete. Local .env configured; credentials were not printed.')
        print('Restart Octo to load these settings. Future dated class records will sync; resend PDFs for Drive filing.')
        print('Drive folder: https://drive.google.com/drive/folders/' + resources['drive_folder']['id'])
        print('Calendar: https://calendar.google.com/calendar/u/0/r')
    except (SetupError, OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(str(exc) if isinstance(exc, SetupError) else 'Local setup files are missing or invalid. See GOOGLE_SETUP.md; no credentials were printed.') from None


if __name__ == '__main__':
    main()
