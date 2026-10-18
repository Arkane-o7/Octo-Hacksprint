"""Temporary membership failures retain webhook retry semantics."""
import httpx
from octo.app import create_app
from octo.offline import OfflineAI
from octo.replay import drain
from test_app import MemberTransport, live_config, send, envelope


async def test_membership_outage_retries_original_message_once_without_stale_access(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import time
    clock = [100.0]
    monkeypatch.setattr('octo.core.time', SimpleNamespace(monotonic=lambda: clock[0], time=time.time))

    class CountingTransport(MemberTransport):
        lookups = 0

        async def group_members(self, group_id):
            self.lookups += 1
            return await super().group_members(group_id)

    transport = CountingTransport()
    app = create_app(live_config(tmp_path), ai=OfflineAI(), transport=transport, worker=False)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://app') as client:
        core = app.state.octo
        await core.refresh_memberships()
        transport.membership_error = True
        event = envelope('RETRY-QUESTION', parent=True, body='What should we bring tomorrow?')
        assert (await send(client, event)).status_code == 503
        assert all(not members for members in core.roster.memberships.values())
        for _ in range(3):
            assert (await send(client, event)).status_code == 503
        assert transport.lookups == 2  # No repeated network calls during the outage cooldown.
        assert core.store.counts()['inbox'] == 0 and not transport.sent

        transport.membership_error = False
        clock[0] += 31
        assert (await send(client, event)).json()['status'] == 'queued'
        assert (await send(client, event)).json()['status'] == 'duplicate'
        await drain(core)
        assert core.store.counts()['inbox'] == 1
        assert len(transport.sent) == 1
