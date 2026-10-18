"""WAHA NOWEB transport. Authenticate before calling ``normalize``.

The only engine-specific fields used are NOWEB's message key (sender aliases)
and content wrapper (forward/reply metadata). Quoted authors are never callers.
"""

import asyncio
import base64
import hashlib
import hmac
import math
import mimetypes
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import httpx

from octo.contracts import IncomingMessage, Media

MAX_MEDIA_BYTES = 20 * 1024 * 1024
TEXT_CHUNK_SIZE = 3500
LOCAL_WAHA_HOSTS = {"localhost", "127.0.0.1", "::1", "waha", "host.docker.internal"}


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify WAHA's X-Webhook-Hmac SHA512 hex digest over the unchanged body."""
    if not secret or not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{128}", signature):
        return False
    expected = hmac.digest(secret.encode(), body, hashlib.sha512)
    return hmac.compare_digest(expected, bytes.fromhex(signature))


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _string(value) -> str:
    return value if isinstance(value, str) else ""


def _jid(value) -> str:
    value = _string(value)
    if value.endswith("@s.whatsapp.net"):
        value = value.removesuffix("@s.whatsapp.net") + "@c.us"
    # A Baileys device suffix identifies a device of the same account.
    return re.sub(r"^(\d+):\d+(@(?:c\.us|lid))$", r"\1\2", value)


def _person(value: str) -> bool:
    return bool(re.fullmatch(r"\d+@(?:c\.us|lid)", value))


def _content(raw: dict) -> dict:
    content = _mapping(raw.get("message"))
    for _ in range(5):
        wrapped = next(
            (content[name] for name in (
                "ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2",
                "viewOnceMessageV2Extension", "documentWithCaptionMessage",
            ) if isinstance(content.get(name), dict)),
            None,
        )
        if wrapped is None:
            break
        content = _mapping(wrapped.get("message"))
    return content


def normalize(payload: dict) -> IncomingMessage | None:
    """Normalize authenticated message events; reject incomplete caller identity.

    Non-message, outgoing and broadcast events return None. Malformed incoming
    messages raise ValueError so the caller can record the failed delivery.
    """
    if not isinstance(payload, dict) or payload.get("event") not in {"message", "message.any"}:
        return None
    message = _mapping(payload.get("payload"))
    raw = _mapping(message.get("_data"))
    key = _mapping(raw.get("key"))
    if message.get("fromMe") is True or key.get("fromMe") is True:
        return None
    session = _string(payload.get("session"))
    message_id = _string(message.get("id"))
    chat_id = _jid(message.get("from"))
    if chat_id.endswith(("@broadcast", "@newsletter")):
        return None
    is_group = chat_id.endswith("@g.us")
    if not session or not message_id or not (is_group or _person(chat_id)):
        raise ValueError("Incoming message is missing a valid session, message ID or chat")
    sender = _jid(message.get("participant") or key.get("participant")) if is_group else chat_id
    if not _person(sender):
        raise ValueError("Group message is missing a valid participant")

    # Only the transport's key can establish LID/phone equivalence. Never use
    # quoted contextInfo.participant, pushName, body, or user-supplied IDs.
    primary_field = "participant" if is_group else "remoteJid"
    aliases: list[str] = []
    if _jid(key.get(primary_field)) == sender:
        alternative = _jid(key.get(primary_field + "Alt"))
        if alternative != sender and _person(alternative):
            aliases.append(alternative)

    stamp = message.get("timestamp")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
        raise ValueError("Incoming message is missing a numeric timestamp")
    if stamp >= 1_000_000_000_000:
        stamp /= 1000
    try:
        timestamp = datetime.fromtimestamp(stamp, timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("Incoming message timestamp is invalid") from exc

    content = _content(raw)
    nodes = [_mapping(content.get(name)) for name in (
        "extendedTextMessage", "imageMessage", "audioMessage", "documentMessage", "videoMessage", "listResponseMessage",
    )]
    context = next((_mapping(node.get("contextInfo")) for node in nodes if node.get("contextInfo")), {})
    text = _string(message.get("body")) or _string(message.get("caption"))
    if not text:
        text = next((_string(node.get("caption")) for node in nodes if node.get("caption")), "")
    selection = _mapping(content.get('listResponseMessage'))
    choice_id = None
    if selection:
        choice_id = _string(_mapping(selection.get('singleSelectReply')).get('selectedRowId')) or 'invalid'
        # Display titles are untrusted and must never become cart/freeform commands.
        text = ''
    media_info = _mapping(message.get("media"))
    media = None
    kind = "text"
    if media_info or message.get("hasMedia"):
        mime = _string(media_info.get("mimetype")) or next(
            (_string(node.get("mimetype")) for node in nodes if node.get("mimetype")),
            "application/octet-stream",
        )
        mime = mime.lower()
        kind = "image" if mime.startswith("image/") else "voice" if mime.startswith("audio/") else "document"
        filename = _string(media_info.get("filename"))
        if not filename:
            extension = mimetypes.guess_extension(mime.split(";")[0].strip()) or ".bin"
            filename = "attachment" + extension
        media = Media(
            url=_string(media_info.get("url")) or None,
            mime_type=mime,
            filename=Path(filename.replace("\\", "/")).name,
        )
    reply = _mapping(message.get("replyTo"))
    return IncomingMessage(
        session=session, message_id=message_id, chat_id=chat_id, sender_id=sender,
        sender_aliases=aliases, timestamp=timestamp, kind=kind, text=text, media=media,
        is_group=is_group,
        forwarded=message.get("isForwarded") is True or context.get("isForwarded") is True,
        quoted_message_id=_string(reply.get("id")) or _string(context.get("stanzaId")) or None,
        is_quoted=bool(reply) or bool(context.get('quotedMessage')) or bool(context.get('stanzaId')),
        menu_choice_id=choice_id,
    )


class WahaClient:
    def __init__(self, base_url: str, api_key: str, session: str, *, client: httpx.AsyncClient | None = None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("WAHA base URL must be an HTTP(S) origin without credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("WAHA base URL must not contain a path, query or fragment")
        self.base_url = base_url.rstrip("/")
        self._origin = parsed
        self.session = session
        self._headers = {"X-Api-Key": api_key}
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False)

    async def group_members(self, group_id: str) -> list[list[str]]:
        """Read current members and their transport-provided phone/LID aliases."""
        if not group_id.endswith('@g.us'):
            raise ValueError('Expected a WhatsApp group ID')
        endpoint = f'/api/{quote(self.session, safe="")}/groups/{quote(group_id, safe="")}/participants'
        response = await self._client.get(self.base_url + endpoint, headers=self._headers,
                                          timeout=15, follow_redirects=False)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError('WAHA returned an invalid group member list')
        members = []
        for participant in data:
            if not isinstance(participant, dict):
                raise ValueError('WAHA returned an invalid group member')
            aliases = set()
            for field in ('id', 'phoneNumber', 'lid'):
                value = participant.get(field)
                if isinstance(value, dict):
                    value = value.get('_serialized')
                identifier = _jid(value)
                if _person(identifier):
                    aliases.add(identifier)
            if not aliases:
                raise ValueError('Group member has no valid WhatsApp identity')
            members.append(sorted(aliases))
        return members

    def _media_url(self, value: str | None) -> str:
        if not value:
            raise ValueError("WAHA did not provide a media download URL")
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Invalid WAHA media URL")
        if parsed.netloc:
            source_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            target_port = self._origin.port or (443 if self._origin.scheme == "https" else 80)
            same_host = parsed.hostname == self._origin.hostname
            local_alias = parsed.hostname in LOCAL_WAHA_HOSTS and self._origin.hostname in LOCAL_WAHA_HOSTS
            if parsed.scheme != self._origin.scheme or source_port != target_port or not (same_host or local_alias):
                raise ValueError("Media URL is outside the configured WAHA origin")
        elif parsed.scheme or not value.startswith("/") or value.startswith("//"):
            raise ValueError("Media URL is outside the configured WAHA origin")
        decoded = unquote(parsed.path)
        if not decoded.startswith("/api/files/") or any(p in {".", ".."} for p in decoded.split("/")) or "\\" in decoded or "\x00" in decoded:
            raise ValueError("Media URL must reference WAHA file storage")
        # Even accepted Docker aliases are rewritten. Never send the key to the
        # supplied hostname or rely on redirects. Query API keys are discarded.
        return urlunsplit((self._origin.scheme, self._origin.netloc, parsed.path, "", ""))

    async def download_media(self, media: Media, destination: Path) -> Path:
        url = self._media_url(media.url)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            async with asyncio.timeout(45):
                async with self._client.stream("GET", url, headers=self._headers, follow_redirects=False, timeout=30) as response:
                    response.raise_for_status()
                    length = response.headers.get("content-length")
                    if length and int(length) > MAX_MEDIA_BYTES:
                        raise ValueError("Media exceeds the 20 MB demo limit")
                    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".octo-download-", delete=False) as stream:
                        temporary = Path(stream.name)
                        total = 0
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > MAX_MEDIA_BYTES:
                                raise ValueError("Media exceeds the 20 MB demo limit")
                            stream.write(chunk)
                    if total == 0:
                        raise ValueError("WAHA returned an empty media file")
                    temporary.replace(destination)
                    temporary = None
            return destination
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def _post(self, endpoint: str, body: dict) -> str | None:
        # No automatic send retry: a timeout may mean WhatsApp accepted it.
        response = await self._client.post(
            self.base_url + endpoint, json=body, headers=self._headers,
            timeout=60, follow_redirects=False,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return None
        identifier = data.get("id")
        if isinstance(identifier, str):
            return identifier
        if isinstance(identifier, dict):
            return _string(identifier.get("_serialized")) or None
        return _string(_mapping(data.get("key")).get("id")) or None

    async def send_text(self, chat_id: str, text: str, reply_to: str | None = None) -> str | None:
        if not text.strip():
            return None
        last_id = None
        remaining = text
        first = True
        while remaining:
            cut = min(len(remaining), TEXT_CHUNK_SIZE)
            if cut < len(remaining):
                boundary = max(remaining.rfind("\n", 0, cut), remaining.rfind(" ", 0, cut))
                if boundary > cut // 2:
                    cut = boundary + 1
            body = {"session": self.session, "chatId": _jid(chat_id), "text": remaining[:cut], "linkPreview": False}
            if first and reply_to:
                body["reply_to"] = reply_to
            last_id = await self._post("/api/sendText", body)
            remaining = remaining[cut:]
            first = False
        return last_id

    async def send_voice(self, chat_id: str, path: Path) -> str | None:
        path = Path(path)
        if not 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
            raise ValueError("Voice file must be nonempty and under 20 MB")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return await self._post("/api/sendVoice", {
            "session": self.session, "chatId": _jid(chat_id), "convert": True,
            "file": {"mimetype": mime, "filename": path.name, "data": base64.b64encode(path.read_bytes()).decode("ascii")},
        })

    async def send_menu(self, chat_id: str, text: str, menu: dict, reply_to: str | None = None) -> str | None:
        """Try NOWEB's DM list API; only definite unsupported requests fall back.

        Timeouts/5xx/ambiguous acceptance never trigger a second send.
        The description retains numbered options for clients hiding the list UI.
        """
        if _jid(chat_id).endswith('@g.us'):
            raise ValueError('Tappable menus are available only in private chat')
        body = {'session': self.session, 'chatId': _jid(chat_id), 'message': menu}
        if reply_to:
            body['reply_to'] = reply_to
        try:
            return await self._post('/api/sendList', body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (400, 404, 405, 422, 501):
                raise
            return await self.send_text(chat_id, text, reply_to=reply_to)

    async def close(self):
        if self._owns_client:
            await self._client.aclose()
