"""Explicit manual setup helpers. No session is created without the pair command."""
import argparse
import json
import secrets
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import Settings
from .core import Roster


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'check', 'status', 'pair', 'groups'])
    args = parser.parse_args()
    if args.command == 'init':
        destination = Path('.env')
        if destination.exists():
            print('.env already exists; no changes made.')
            return
        content = Path('.env.example').read_text()
        for name in ['WAHA_API_KEY', 'WAHA_WEBHOOK_SECRET', 'WAHA_DASHBOARD_PASSWORD', 'WHATSAPP_SWAGGER_PASSWORD']:
            content = content.replace(name + '=\n', name + '=' + secrets.token_urlsafe(32) + '\n')
        with destination.open('x') as stream:
            stream.write(content)
        destination.chmod(0o600)
        print('Created .env with local webhook credentials. Set SARVAM_API_KEY there; it is still blank.')
        return
    config = Settings.from_env()
    if args.command == 'check':
        print('Mode:', config.mode)
        for name, value in [('SARVAM_API_KEY', config.sarvam_api_key), ('WAHA_API_KEY', config.waha_api_key),
                            ('WAHA_WEBHOOK_SECRET', config.webhook_secret)]:
            print(f'{name}: ' + ('configured' if value.strip() else 'missing'))
        try:
            Roster(config.roster_path, live=True)
            print('Live roster: configured (identities still need a real-message check)')
        except (ValueError, OSError, KeyError):
            print('Live roster: not ready; edit roster.local.json and OCTO_ROSTER')
        return
    if not config.waha_api_key:
        raise SystemExit('Set WAHA_API_KEY locally first.')
    session = quote(config.waha_session, safe='')
    with httpx.Client(base_url=config.waha_base_url, headers={'X-Api-Key': config.waha_api_key}, timeout=30) as client:
        try:
            if args.command == 'status':
                result = client.get('/api/sessions', params={'all': 'true'})
                result.raise_for_status()
                print(json.dumps([{'name': s['name'], 'status': s['status']} for s in result.json()], indent=2))
            elif args.command == 'groups':
                result = client.get(f'/api/{session}/groups', params={'limit': 20, 'exclude': 'participants'})
                result.raise_for_status()
                groups = result.json()
                groups = groups.values() if isinstance(groups, dict) else groups
                print(json.dumps([{'id': g.get('id'), 'subject': g.get('subject', g.get('name'))} for g in groups], indent=2))
            else:
                # Run this only for the dedicated demo account. Existing sessions
                # are never reset or replaced by this helper.
                result = client.get(f'/api/sessions/{session}')
                if result.status_code == 404:
                    result = client.post('/api/sessions', json={'name': config.waha_session, 'start': True,
                        'config': {'noweb': {'store': {'enabled': True, 'fullSync': False}}}})
                    result.raise_for_status()
                else:
                    result.raise_for_status()
                    status = result.json().get('status')
                    if status == 'WORKING':
                        print('Demo session is already paired. No changes made.')
                        return
                    if status == 'STOPPED':
                        result = client.post(f'/api/sessions/{session}/start')
                        result.raise_for_status()
                result = client.get(f'/api/{session}/auth/qr', params={'format': 'image'}, headers={'Accept': 'image/png'})
                result.raise_for_status()
                if not result.content.startswith(b'\x89PNG'):
                    raise ValueError('QR response was not a PNG.')
                destination = config.data_dir / 'pairing-qr.png'
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(result.content)
                destination.chmod(0o600)
                print('Scan with the dedicated demo account: ' + str(destination.resolve()))
        except httpx.HTTPStatusError as exc:
            raise SystemExit(f'WAHA returned HTTP {exc.response.status_code}. If the session is starting, wait a few seconds and repeat. No response body or credentials printed.') from None
        except (httpx.RequestError, ValueError):
            raise SystemExit('WAHA is unavailable or returned an unexpected response. Check Docker and repeat.') from None


if __name__ == '__main__':
    main()
