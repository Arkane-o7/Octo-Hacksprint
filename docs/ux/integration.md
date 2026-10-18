# Octo UX integration acceptance

Integration branch: `codex/octo-ux`, based on `715fe57ef94c3a9487296eedf979692f5e39f2d6`.
All validation uses synthetic adapters and temporary fixture storage. No live service, credentials, messages or primary-checkout data are used.

## Acceptance checklist

- Teacher text/photo missing date → fresh date/year follow-up preserves the original source, uncertainty and deduplication; schedules only one record/reminder/Calendar intent.
- Parent question → notes/calendar → language change → read aloud retains only the authorized, unexpired topic. Explicit new questions replace that topic.
- Expiry, multiple children, changed membership, changed student authorization, and different session/chat/person scopes cannot leak context.
- Typed/voice × DM/group × explicit audio preference follows the quieter audio policy; voice progress and same-chat reply attribution persist across retry/restart.
- Welcome/help stays compact and authorized; group notices do not gain welcome or Calendar-success spam.
- English/Hindi/Tamil fixed notices, help and errors retain factual content and uncertainty. Calendar pending/failure never claims success.
- SQLCipher persistence and existing migration behavior survive new context/preferences/outbox fields.
- Simulated purchases require fresh typed approval by the correct parent for the exact current proposal; voice, quotes, forwards, stale/replayed/history approvals cannot authorize purchases.
- Sarvam remains the sole configured AI provider; general brain stays off by default and unsupported lesson/test/practice updates stay unsupported.

## Validation record

Pending feature review and combined offline verification.

## Real-device acceptance remaining

A separate user-assisted handset rehearsal must check WhatsApp quotation rendering, perceived acknowledgment timing, voice playback/preferences, actual handwriting OCR and short-voice STT/TTS in English/Hindi/Tamil, and real Calendar authorization/delivery. Synthetic checks cannot establish provider or handset reliability.
