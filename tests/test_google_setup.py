import base64
import hashlib
import json
import sqlite3
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from octo.google_setup import (make_authorization, callback_values, provision,
                               save_private, retry_calendar_jobs, SetupError, TOKEN_URL)


def test_oauth_uses_pkce_state_and_small_scopes():
    url, state, verifier = make_authorization('client', 'http://127.0.0.1:123/callback')
    query = parse_qs(urlsplit(url).query)
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    assert query['code_challenge'] == [expected]
    assert query['state'] == [state] and query['prompt'] == ['consent']
    assert query['access_type'] == ['offline']
    assert 'calendar.app.created' in query['scope'][0]
    assert 'drive.file' in query['scope'][0]
    assert callback_values('/callback?state=bad&code=secret', state) is None
    assert callback_values('/callback?state=' + state + '&code=secret', state) == {'code':'secret'}
    assert callback_values('/other?state=' + state + '&code=secret', state) is None
    assert 'error' in callback_values('/callback?state=' + state + '&error=access_denied', state)


def test_setup_creates_only_dedicated_resources_and_resumes_without_duplicates(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        if str(request.url) == TOKEN_URL:
            return httpx.Response(200, json={'access_token':'secret'})
        is_drive = '/drive/' in str(request.url)
        return httpx.Response(200, json={'id':'folder1' if is_drive else 'demo@group.calendar.google.com'})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    creds = dict(client_id='c',client_secret='s',refresh_token='r')
    path = tmp_path/'resources.json'
    result = provision(client,creds,path)
    assert result['drive_folder']['id']=='folder1'
    assert path.stat().st_mode & 0o777 == 0o600
    provision(client,creds,path)
    creates = [r for r in requests if r.method=='POST' and str(r.url)!=TOKEN_URL]
    assert len(creates)==2
    assert json.loads(creates[0].content)['name']=='Octo Demo'
    assert json.loads(creates[1].content)['timeZone']=='Asia/Kolkata'


def test_uncertain_resource_create_is_not_repeated(tmp_path):
    path = tmp_path/'resources.json'
    calls = []
    def handler(request):
        calls.append(request)
        if str(request.url)==TOKEN_URL:
            return httpx.Response(200,json={'access_token':'secret'})
        raise httpx.ReadTimeout('provider secret',request=request)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    creds = dict(client_id='c',client_secret='s',refresh_token='r')
    with pytest.raises(SetupError) as exc:
        provision(client,creds,path)
    assert 'provider secret' not in str(exc.value)
    with pytest.raises(SetupError,match='unconfirmed'):
        provision(client,creds,path)
    assert sum(str(r.url)!=TOKEN_URL for r in calls)==1


def test_save_private_tightens_preexisting_file_permissions(tmp_path):
    path=tmp_path/'token.json'
    path.write_text('old')
    path.chmod(0o644)
    save_private(path,{'refresh_token':'secret'})
    assert path.stat().st_mode & 0o777==0o600


def test_deliberate_retry_resets_only_failed_jobs_for_configured_calendar(tmp_path):
    from octo.storage import Store
    store=Store(tmp_path/'live'/'octo.sqlite3')
    for sid,cal,status in [('old','demo','failed'),('new','demo','pending'),('elsewhere','other','failed')]:
        store.queue_calendar(sid,cal,'upsert')
        store.db.execute('UPDATE calendar_jobs SET status=?,attempts=3 WHERE source_id=?',(status,sid))
    store.db.commit()
    assert retry_calendar_jobs(tmp_path,'demo')==1
    rows={r['source_id']:dict(r) for r in store.db.execute('SELECT * FROM calendar_jobs')}
    assert rows['old']['status']=='pending' and rows['old']['attempts']==0
    assert rows['new']['attempts']==3 and rows['elsewhere']['status']=='failed'
    store.close()
