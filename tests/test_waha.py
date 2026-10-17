import base64
import copy
import json
from datetime import timezone

import httpx
import pytest

from octo.contracts import Media
from octo.waha import WahaClient, normalize, verify_signature


def event(**changes):
    payload = {
        "id": "false_919000000001@c.us_M1", "from": "919000000001@c.us",
        "fromMe": False, "timestamp": 1792200000, "body": "Bring crayons tomorrow",
    }
    payload.update(changes)
    return {"event": "message", "session": "default", "payload": payload}


def test_documented_hmac_vector_and_modified_body():
    body = b'{"event":"message","session":"default","engine":"WEBJS"}'
    signature = "208f8a55dde9e05519e898b10b89bf0d0b3b0fdf11fdbf09b6b90476301b98d8097c462b2b17a6ce93b6b47a136cf2e78a33a63f6752c2c1631777076153fa89"
    assert verify_signature(body, signature, "my-secret-key")
    assert not verify_signature(body + b" ", signature, "my-secret-key")
    assert not verify_signature(body, signature, "")
    assert not verify_signature(body, "sha512=" + signature, "my-secret-key")
    assert not verify_signature(body, "bad", "my-secret-key")


def test_direct_message_keeps_source_identity_and_aware_time():
    message = normalize(event())
    assert message.sender_id == message.chat_id == "919000000001@c.us"
    assert message.timestamp.tzinfo == timezone.utc
    assert message.kind == "text"
    assert json.loads(message.source_key) == ["default", message.chat_id, message.message_id]


@pytest.mark.parametrize("change", [
    {"event": "message.reaction"}, {"event": "message.edited"}, {"event": "session.status"},
])
def test_nonmessage_events_ignored(change):
    incoming = event()
    incoming.update(change)
    assert normalize(incoming) is None


def test_outbound_and_broadcast_ignored():
    assert normalize(event(fromMe=True)) is None
    assert normalize(event(_data={"key": {"fromMe": True}})) is None
    assert normalize(event(**{"from": "status@broadcast"})) is None
    assert normalize(event(**{"from": "123@newsletter"})) is None


def test_group_image_keeps_participant_caption_and_forward_metadata():
    incoming = event(**{
        "from": "120363123@g.us", "participant": "919000000002@s.whatsapp.net",
        "body": "Class 5 science", "hasMedia": True,
        "media": {"url": "http://localhost:3000/api/files/board.jpg", "mimetype": "image/jpeg", "filename": None},
        "_data": {"message": {"ephemeralMessage": {"message": {
            "imageMessage": {"contextInfo": {"isForwarded": True, "stanzaId": "ORIGINAL"}},
        }}}},
    })
    message = normalize(incoming)
    assert message.chat_id == "120363123@g.us"
    assert message.sender_id == "919000000002@c.us"
    assert message.is_group and message.forwarded
    assert message.quoted_message_id == "ORIGINAL"
    assert message.text == "Class 5 science"
    assert message.kind == "image"
    assert message.media.filename.endswith(".jpg")


def test_null_media_url_still_preserves_pdf_and_sanitizes_filename():
    message = normalize(event(hasMedia=True, media={
        "url": None, "mimetype": "application/pdf", "filename": "../../Science.pdf",
    }))
    assert message.kind == "document"
    assert message.media.url is None
    assert message.media.filename == "Science.pdf"


def test_voice_uses_raw_content_mime_when_download_metadata_missing():
    message = normalize(event(body=None, hasMedia=True, _data={
        "message": {"audioMessage": {"mimetype": "audio/ogg; codecs=opus", "ptt": True}},
    }))
    assert message.kind == "voice"
    assert message.text == ""
    assert message.media.mime_type == "audio/ogg; codecs=opus"


def test_sender_aliases_come_only_from_matching_transport_key():
    incoming = event(**{
        "from": "120363123@g.us", "participant": "777@lid",
        "replyTo": {"id": "R1", "participant": "999@c.us"},
        "_data": {"key": {"participant": "777@lid", "participantAlt": "919000000002@s.whatsapp.net", "remoteJidAlt": "999@c.us"},
                  "message": {"extendedTextMessage": {"contextInfo": {"participant": "999@c.us"}}}},
    })
    assert normalize(incoming).sender_aliases == ["919000000002@c.us"]
    mismatch = copy.deepcopy(incoming)
    mismatch["payload"]["_data"]["key"]["participant"] = "888@lid"
    assert normalize(mismatch).sender_aliases == []
    direct = event(**{"from": "777@lid", "_data": {"key": {
        "remoteJid": "777@lid", "remoteJidAlt": "919000000002:4@s.whatsapp.net",
    }}})
    assert normalize(direct).sender_aliases == ["919000000002@c.us"]


def test_group_cannot_take_sender_from_quote_or_group_id():
    with pytest.raises(ValueError, match="participant"):
        normalize(event(**{"from": "120363123@g.us", "replyTo": {"participant": "999@c.us"}}))


@pytest.mark.parametrize("stamp", [None, "tomorrow", True, float("nan"), float("inf")])
def test_invalid_timestamps_are_rejected(stamp):
    with pytest.raises(ValueError, match="timestamp"):
        normalize(event(timestamp=stamp))


async def test_download_rewrites_local_alias_authenticates_and_copies(tmp_path):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=b"photograph", headers={"Content-Type": "image/jpeg"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        waha = WahaClient("http://127.0.0.1:3000", "secret", "default", client=client)
        path = await waha.download_media(Media(url="http://waha:3000/api/files/board.jpg?x-api-key=old"), tmp_path / "board.jpg")
        assert path.read_bytes() == b"photograph"
        assert str(requests[0].url) == "http://127.0.0.1:3000/api/files/board.jpg"
        assert requests[0].headers["X-Api-Key"] == "secret"


@pytest.mark.parametrize("url", [
    "http://evil.test:3000/api/files/board.jpg", "http://localhost:5000/api/files/a.jpg",
    "http://localhost:3000/api/sessions", "http://localhost:3000/api/files/../sessions",
    "http://localhost:3000/api/files/%2e%2e/sessions", "http://user:pass@localhost:3000/api/files/a.jpg",
    "file:///etc/passwd", "//evil.test/api/files/a.jpg", None,
])
async def test_untrusted_media_url_is_rejected_before_request(tmp_path, url):
    def handle(request):
        pytest.fail("An untrusted media URL reached the HTTP client")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        waha = WahaClient("http://localhost:3000", "secret", "default", client=client)
        with pytest.raises(ValueError):
            await waha.download_media(Media(url=url), tmp_path / "file")


async def test_media_redirect_is_not_followed_even_when_injected_client_enables_it(tmp_path):
    calls = []

    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.test/steal"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        waha = WahaClient("http://localhost:3000", "secret", "default", client=client)
        with pytest.raises(httpx.HTTPStatusError):
            await waha.download_media(Media(url="/api/files/a.jpg"), tmp_path / "file")
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


async def test_stream_size_limit_cleans_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr("octo.waha.MAX_MEDIA_BYTES", 4)

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"abc"
            yield b"def"

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Chunks()))) as client:
        waha = WahaClient("http://localhost:3000", "secret", "default", client=client)
        with pytest.raises(ValueError, match="limit"):
            await waha.download_media(Media(url="/api/files/a.jpg"), tmp_path / "file")
    assert not list(tmp_path.iterdir())


async def test_send_text_chunks_preserving_text_and_quotes_first_only():
    bodies = []

    def handle(request):
        assert request.headers["X-Api-Key"] == "secret"
        assert request.url.path == "/api/sendText"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"M{len(bodies)}"})

    text = "Study science\n" * 400
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        waha = WahaClient("http://localhost:3000", "secret", "demo", client=client)
        result = await waha.send_text("919000000001@s.whatsapp.net", text, "ORIGINAL")
    assert len(bodies) == 2 and result == "M2"
    assert "".join(b["text"] for b in bodies) == text
    assert all(len(b["text"]) <= 3500 and b["session"] == "demo" for b in bodies)
    assert bodies[0]["reply_to"] == "ORIGINAL" and "reply_to" not in bodies[1]
    assert bodies[0]["chatId"] == "919000000001@c.us"


async def test_send_voice_uses_actual_audio_mime_and_requests_conversion(tmp_path):
    path = tmp_path / "reply.wav"
    path.write_bytes(b"RIFF-demo-audio")
    bodies = []

    def handle(request):
        assert request.url.path == "/api/sendVoice"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"key": {"id": "AUDIO1"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        waha = WahaClient("http://localhost:3000", "secret", "default", client=client)
        assert await waha.send_voice("919000000001@c.us", path) == "AUDIO1"
    assert bodies[0]["convert"] is True
    assert bodies[0]["file"]["mimetype"] in {"audio/wav", "audio/x-wav"}
    assert base64.b64decode(bodies[0]["file"]["data"]) == path.read_bytes()


async def test_send_timeout_is_not_retried():
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("send outcome unknown", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        waha = WahaClient("http://localhost:3000", "secret", "default", client=client)
        with pytest.raises(httpx.ReadTimeout):
            await waha.send_text("919000000001@c.us", "Hello")
    assert len(calls) == 1
