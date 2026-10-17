import hashlib
import json
from urllib.parse import parse_qs

import httpx
import pytest

from octo.drive import DriveError, GoogleDriveClient


@pytest.fixture
def inputs(tmp_path):
    credentials = tmp_path / "fake-oauth.json"
    credentials.write_text(json.dumps({"client_id": "fake-client", "client_secret": "fake-secret", "refresh_token": "fake-refresh"}))
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.7\n\x00exact demo bytes\n%%EOF")
    return credentials, pdf


class FakeDrive:
    def __init__(self):
        self.calls = []
        self.folders = {}
        self.file = None
        self.upload_metadata = None
        self.upload_body = None
        self.location = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=demo"
        self.fail_token = False
        self.timeout_upload = False
        self.timeout_folder = False
        self.recover_upload = True
        self.web_link = "https://drive.google.com/file/d/FILE123/view?usp=drive_link"

    def __call__(self, request):
        self.calls.append(request)
        assert "permissions" not in request.url.path
        if request.url.host == "oauth2.googleapis.com":
            form = parse_qs(request.content.decode())
            assert form == {
                "client_id": ["fake-client"], "client_secret": ["fake-secret"],
                "refresh_token": ["fake-refresh"], "grant_type": ["refresh_token"],
            }
            assert "Authorization" not in request.headers
            if self.fail_token:
                return httpx.Response(400, json={"error": "invalid_grant", "private": "SECRET-MUST-NOT-LEAK"})
            return httpx.Response(200, json={"access_token": "fake-access", "expires_in": 3600})
        assert request.url.host == "www.googleapis.com"
        assert request.headers["Authorization"] == "Bearer fake-access"
        if request.method == "GET":
            query = request.url.params["q"]
            assert " in parents and trashed = false and " in query
            assert request.url.params["spaces"] == "drive"
            if "application/vnd.google-apps.folder" in query:
                return httpx.Response(200, json={"files": [self.folders[query]] if query in self.folders else []})
            assert "appProperties has" in query and "octo_sha256" in query
            return httpx.Response(200, json={"files": [self.file] if self.file else []})
        if request.method == "POST" and request.url.path == "/drive/v3/files":
            metadata = json.loads(request.content)
            parent = metadata["parents"][0]
            name = metadata["name"].replace("\\", "\\\\").replace("'", "\\'")
            query = f"'{parent}' in parents and trashed = false and mimeType = 'application/vnd.google-apps.folder' and name = '{name}'"
            folder = {"id": f"FOLDER{len(self.folders) + 1}", "name": metadata["name"]}
            self.folders[query] = folder
            if self.timeout_folder:
                self.timeout_folder = False
                raise httpx.ReadTimeout("PRIVATE-provider-details", request=request)
            return httpx.Response(200, json=folder)
        if request.method == "POST" and request.url.path == "/upload/drive/v3/files":
            assert request.url.params["uploadType"] == "resumable"
            self.upload_metadata = json.loads(request.content)
            assert request.headers["X-Upload-Content-Type"] == "application/pdf"
            return httpx.Response(200, headers={"Location": self.location})
        if request.method == "PUT":
            self.upload_body = request.content
            self.file = {"id": "FILE123", "webViewLink": self.web_link} if self.recover_upload else None
            if self.timeout_upload:
                raise httpx.ReadTimeout("PRIVATE-provider-details", request=request)
            return httpx.Response(200, json=self.file)
        pytest.fail(f"Unexpected method/path: {request.method} {request.url.path}")


async def test_missing_configuration_is_explicit_and_never_makes_requests(tmp_path):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected network call"))) as http:
        for path, root in [(None, "ROOT"), (tmp_path / "absent.json", "ROOT"), (None, "")]:
            client = GoogleDriveClient(path, root, client=http)
            assert not client.configured
            with pytest.raises(DriveError, match="not configured; the file is retained locally"):
                await client.file_pdf(tmp_path / "also-absent.pdf", "Science")


@pytest.mark.parametrize("payload", ["invalid json", '{"client_id":"only-client"}', '[]'])
async def test_invalid_local_credentials_are_not_configured(tmp_path, payload):
    credentials = tmp_path / "fake.json"
    credentials.write_text(payload)
    async with httpx.AsyncClient() as http:
        assert not GoogleDriveClient(credentials, "ROOT", client=http).configured


async def test_explicit_root_is_required_even_with_credentials(inputs):
    async with httpx.AsyncClient() as http:
        assert not GoogleDriveClient(inputs[0], "", client=http).configured


async def test_pdf_upload_creates_restricted_hierarchy_and_returns_actual_url(inputs):
    backend = FakeDrive()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        drive = GoogleDriveClient(inputs[0], "ROOT", client=http)
        assert drive.configured
        result = await drive.file_pdf(inputs[1], "Science", "Chapter 6")
        await drive.close()
        assert not http.is_closed
    assert result == {"id": "FILE123", "url": backend.web_link}
    assert backend.upload_body == inputs[1].read_bytes()
    assert backend.upload_metadata == {
        "name": "Science - Chapter 6.pdf", "mimeType": "application/pdf", "parents": ["FOLDER2"],
        "appProperties": {"octo_sha256": hashlib.sha256(inputs[1].read_bytes()).hexdigest()},
    }
    folder_posts = [json.loads(r.content) for r in backend.calls if r.method == "POST" and r.url.path == "/drive/v3/files"]
    assert folder_posts[0]["parents"] == ["ROOT"]
    assert folder_posts[1]["parents"] == ["FOLDER1"]
    queries = [r.url.params["q"] for r in backend.calls if r.method == "GET"]
    assert queries[0].startswith("'ROOT' in parents")
    assert queries[1].startswith("'FOLDER1' in parents")
    assert queries[2].startswith("'FOLDER2' in parents")
    assert sum(r.url.host == "oauth2.googleapis.com" for r in backend.calls) == 1


async def test_sanitized_names_and_escaped_apostrophe_remain_parent_restricted(inputs):
    backend = FakeDrive()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        drive = GoogleDriveClient(inputs[0], "ROOT", client=http)
        await drive.file_pdf(inputs[1], " O'Brien / Science\n", "..\\Chapter 6\x00")
    queries = [r.url.params["q"] for r in backend.calls if r.method == "GET"]
    assert "name = 'O\\'Brien - Science'" in queries[0]
    assert "name = 'Chapter 6'" in queries[1]
    assert backend.upload_metadata["name"] == "O'Brien - Science - Chapter 6.pdf"


async def test_oauth_failure_does_not_expose_provider_body_or_credentials(inputs):
    backend = FakeDrive()
    backend.fail_token = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        drive = GoogleDriveClient(inputs[0], "ROOT", client=http)
        with pytest.raises(DriveError) as caught:
            await drive.file_pdf(inputs[1], "Science")
    assert "OAuth refresh failed" in str(caught.value)
    assert "SECRET" not in str(caught.value) and "fake-secret" not in str(caught.value)
    assert len(backend.calls) == 1


@pytest.mark.parametrize("bad_kind", ["extension", "signature", "size"])
async def test_pdf_validation_precedes_any_google_call(inputs, monkeypatch, bad_kind):
    path = inputs[1]
    if bad_kind == "extension":
        renamed = path.with_suffix(".jpg")
        path.rename(renamed)
        path = renamed
    elif bad_kind == "signature":
        path.write_bytes(b"not a PDF")
    else:
        monkeypatch.setattr("octo.drive.MAX_PDF_BYTES", 8)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected network"))) as http:
        drive = GoogleDriveClient(inputs[0], "ROOT", client=http)
        with pytest.raises(DriveError):
            await drive.file_pdf(path, "Science")


async def test_content_hash_reuses_existing_file_without_upload(inputs):
    backend = FakeDrive()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        drive = GoogleDriveClient(inputs[0], "ROOT", client=http)
        first = await drive.file_pdf(inputs[1], "Science", "Chapter 6")
        second = await drive.file_pdf(inputs[1], "Science", "Chapter 6")
    assert first == second
    assert sum(r.method == "PUT" for r in backend.calls) == 1
    assert sum(r.method == "POST" and r.url.path == "/drive/v3/files" for r in backend.calls) == 2


async def test_real_file_id_can_supply_view_link_when_api_omits_it(inputs):
    backend = FakeDrive()
    backend.web_link = None
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        result = await GoogleDriveClient(inputs[0], "ROOT", client=http).file_pdf(inputs[1], "Science")
    assert result == {"id": "FILE123", "url": "https://drive.google.com/file/d/FILE123/view"}


async def test_uncertain_folder_create_is_recovered_without_post_retry(inputs):
    backend = FakeDrive()
    backend.timeout_folder = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        result = await GoogleDriveClient(inputs[0], "ROOT", client=http).file_pdf(inputs[1], "Science")
    assert result["id"] == "FILE123"
    assert sum(r.method == "POST" and r.url.path == "/drive/v3/files" for r in backend.calls) == 1


@pytest.mark.parametrize("recover", [True, False])
async def test_uncertain_upload_uses_only_read_only_recovery(inputs, recover):
    backend = FakeDrive()
    backend.timeout_upload = True
    backend.recover_upload = recover
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        drive = GoogleDriveClient(inputs[0], "ROOT", client=http)
        if recover:
            assert (await drive.file_pdf(inputs[1], "Science"))["id"] == "FILE123"
        else:
            with pytest.raises(DriveError, match="check Drive before retrying") as caught:
                await drive.file_pdf(inputs[1], "Science")
            assert "PRIVATE" not in str(caught.value)
    assert sum(r.method == "PUT" for r in backend.calls) == 1
    assert sum(r.method == "POST" and r.url.path == "/upload/drive/v3/files" for r in backend.calls) == 1


async def test_upload_destination_cannot_leak_oauth_to_another_host(inputs):
    backend = FakeDrive()
    backend.location = "https://evil.test/upload"
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as http:
        with pytest.raises(DriveError, match="invalid upload destination"):
            await GoogleDriveClient(inputs[0], "ROOT", client=http).file_pdf(inputs[1], "Science")
    assert all(r.url.host in {"www.googleapis.com", "oauth2.googleapis.com"} for r in backend.calls)
    assert not any(r.method == "PUT" for r in backend.calls)


async def test_ambiguous_folders_stop_without_creating_or_uploading(inputs):
    backend = FakeDrive()

    def handle(request):
        if request.method == "GET":
            return httpx.Response(200, json={"files": [{"id": "FOLDER1"}, {"id": "FOLDER2"}]})
        return backend(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(DriveError, match="ambiguous"):
            await GoogleDriveClient(inputs[0], "ROOT", client=http).file_pdf(inputs[1], "Science")
    assert all(r.url.host == "oauth2.googleapis.com" for r in backend.calls)


async def test_redirect_is_not_followed_even_with_injected_client_setting(inputs):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.test/credentials"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as http:
        with pytest.raises(DriveError):
            await GoogleDriveClient(inputs[0], "ROOT", client=http).file_pdf(inputs[1], "Science")
    assert len(calls) == 1
