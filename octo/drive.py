"""Small Google Drive PDF adapter. Uses only explicitly configured local OAuth.

Uploads inherit existing folder access. This module never changes permissions
and a returned link does not establish that a particular parent can open it.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import httpx


FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
TOKEN_URL = "https://oauth2.googleapis.com/token"
MAX_PDF_BYTES = 20 * 1024 * 1024
NOT_CONFIGURED = "Google Drive is not configured; the file is retained locally. Configure local OAuth credentials and an explicit demo folder."


class DriveError(RuntimeError):
    """Safe user-facing error without credentials, provider bodies or local paths."""


def _name(value: str) -> str:
    value = "".join(" " if unicodedata.category(char).startswith("C") else char for char in value)
    value = re.sub(r"\s+", " ", value.replace("/", " - ").replace("\\", " - ")).strip(" .-")[:100]
    if not value:
        raise DriveError("Please confirm the document subject/chapter; the file is retained locally.")
    return value


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveClient:
    def __init__(self, credentials_path: Path | None, root_folder_id: str, *, client: httpx.AsyncClient | None = None):
        self.root_folder_id = root_folder_id.strip()
        self._credentials: dict | None = None
        if credentials_path is not None and re.fullmatch(r"[A-Za-z0-9_-]+", self.root_folder_id):
            try:
                data = json.loads(Path(credentials_path).read_text())
                if isinstance(data, dict) and all(isinstance(data.get(key), str) and data[key].strip() for key in ("client_id", "client_secret", "refresh_token")):
                    self._credentials = {key: data[key] for key in ("client_id", "client_secret", "refresh_token")}
            except (OSError, ValueError):
                pass
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10), follow_redirects=False)
        self._access_token = ""
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        """Local configuration exists; this does not prove OAuth or folder access."""
        return self._credentials is not None

    async def close(self):
        if self._owns_client:
            await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = await self._client.request(method, url, follow_redirects=False, timeout=60, **kwargs)
        except httpx.RequestError:
            raise DriveError("Google Drive could not confirm this request. The file is retained locally; check Drive before retrying an upload.") from None
        if not 200 <= response.status_code < 300:
            if response.status_code in (401, 403):
                self._access_token = ""
                message = "Google Drive access was denied. Check OAuth consent and demo-folder access; the file is retained locally."
            elif url == TOKEN_URL:
                message = "Google Drive OAuth refresh failed. Reconnect the demo credentials locally; the file is retained locally."
            else:
                message = "Google Drive did not confirm the operation. The file is retained locally; check Drive before retrying an upload."
            raise DriveError(message)
        return response

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            data = response.json()
        except ValueError:
            raise DriveError("Google Drive returned an unreadable response; the file is retained locally.") from None
        if not isinstance(data, dict):
            raise DriveError("Google Drive returned an unexpected response; the file is retained locally.")
        return data

    async def _auth(self) -> dict[str, str]:
        if not self.configured:
            raise DriveError(NOT_CONFIGURED)
        if not self._access_token or time.monotonic() >= self._expires_at:
            response = await self._request("POST", TOKEN_URL, data={**self._credentials, "grant_type": "refresh_token"})
            data = self._json(response)
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                raise DriveError("Google Drive OAuth did not return an access token; the file is retained locally.")
            try:
                lifetime = max(0, min(float(data.get("expires_in", 3600)) - 60, 3600))
            except (TypeError, ValueError):
                lifetime = 0
            self._access_token = token
            self._expires_at = time.monotonic() + lifetime
        return {"Authorization": "Bearer " + self._access_token}

    async def _find(self, parent_id: str, condition: str) -> dict | None:
        query = f"'{_escape(parent_id)}' in parents and trashed = false and {condition}"
        data = self._json(await self._request("GET", FILES_URL, headers=await self._auth(), params={
            "q": query, "pageSize": 2, "spaces": "drive",
            "fields": "files(id,name,webViewLink),nextPageToken,incompleteSearch",
        }))
        files = data.get("files")
        if not isinstance(files, list) or data.get("incompleteSearch") or data.get("nextPageToken") or len(files) > 1:
            raise DriveError("Google Drive found ambiguous or incomplete folder/file results. Check the demo folder before retrying.")
        if files and not isinstance(files[0], dict):
            raise DriveError("Google Drive returned invalid file metadata; the file is retained locally.")
        return files[0] if files else None

    @staticmethod
    def _id(data: dict) -> str:
        identifier = data.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
            raise DriveError("Google Drive did not confirm a file ID; the file is retained locally.")
        return identifier

    async def _folder(self, parent: str, name: str) -> str:
        condition = f"mimeType = 'application/vnd.google-apps.folder' and name = '{_escape(name)}'"
        existing = await self._find(parent, condition)
        if existing:
            return self._id(existing)
        try:
            data = self._json(await self._request("POST", FILES_URL, headers=await self._auth(), params={"fields": "id"}, json={
                "name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent],
            }))
            return self._id(data)
        except DriveError as original:
            # Only search to recover an uncertain create; never repeat the POST.
            try:
                recovered = await self._find(parent, condition)
                if recovered:
                    return self._id(recovered)
            except DriveError:
                pass
            raise original from None

    @classmethod
    def _result(cls, data: dict) -> dict[str, str]:
        identifier = cls._id(data)
        url = data.get("webViewLink")
        if isinstance(url, str):
            parsed = urlsplit(url)
            if parsed.scheme == "https" and parsed.hostname in {"drive.google.com", "docs.google.com"} and not parsed.username and not parsed.password:
                return {"id": identifier, "url": url}
        return {"id": identifier, "url": f"https://drive.google.com/file/d/{identifier}/view"}

    async def file_pdf(self, path: Path, subject: str, chapter: str | None = None) -> dict[str, str]:
        if not self.configured:
            raise DriveError(NOT_CONFIGURED)
        path = Path(path)
        try:
            if path.suffix.lower() != ".pdf" or not 0 < path.stat().st_size <= MAX_PDF_BYTES:
                raise DriveError("Please send a PDF smaller than 20 MB; the file is retained locally.")
            content = path.read_bytes()
        except OSError:
            raise DriveError("The saved PDF is unavailable locally. Please resend it.") from None
        if len(content) > MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
            raise DriveError("The attachment is not a supported PDF; the file is retained locally.")
        subject = _name(subject)
        chapter = _name(chapter) if chapter is not None else None
        parent = await self._folder(self.root_folder_id, subject)
        if chapter:
            parent = await self._folder(parent, chapter)
        digest = hashlib.sha256(content).hexdigest()
        condition = f"mimeType = 'application/pdf' and appProperties has {{ key='octo_sha256' and value='{digest}' }}"
        existing = await self._find(parent, condition)
        if existing:
            return self._result(existing)
        started = await self._request("POST", UPLOAD_URL, headers={
            **await self._auth(), "X-Upload-Content-Type": "application/pdf", "X-Upload-Content-Length": str(len(content)),
        }, params={"uploadType": "resumable", "fields": "id,webViewLink"}, json={
            "name": subject + (" - " + chapter if chapter else " notes") + ".pdf",
            "mimeType": "application/pdf", "parents": [parent], "appProperties": {"octo_sha256": digest},
        })
        location = started.headers.get("location", "")
        parsed = urlsplit(location)
        if parsed.scheme != "https" or parsed.netloc != "www.googleapis.com" or parsed.path != "/upload/drive/v3/files" or parsed.fragment:
            raise DriveError("Google Drive returned an invalid upload destination; the file is retained locally.")
        try:
            uploaded = await self._request("PUT", location, headers={
                **await self._auth(), "Content-Type": "application/pdf", "Content-Length": str(len(content)),
            }, content=content)
            return self._result(self._json(uploaded))
        except DriveError as original:
            # Recovery is read-only. A later retry also performs this hash lookup.
            try:
                recovered = await self._find(parent, condition)
                if recovered:
                    return self._result(recovered)
            except DriveError:
                pass
            raise original from None
