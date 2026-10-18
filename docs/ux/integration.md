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

Validated on 18 October 2026 (Asia/Kolkata) from the isolated integration worktree.

- Reviewed and cherry-picked conversation `f5ba00b29d712255fe1c436471bac19498da97c4`, delivery `a7094a35777517f275aaee361925b1a7fd3a47d8`, and welcome `ffce64c477230738f41058f8b6ff12ab0e0649dc`.
- Final complete suite: **407 passed** (`/Users/abhilaksh/Projects/Octo/.venv/bin/python -m pytest -q`, worktree cwd). An earlier full run had three new fixture assertions expecting an underscore that the established WhatsApp formatter strips; the fixture now uses a plain item name. The final complete run is green.
- **30 combined integration scenarios** in `tests/test_ux_integration.py`, with SQLCipher fixture storage, injected synthetic speech/transport/Calendar adapters and no credentials. Tests using `mode=live` only enable scheduling/audio policy; all external adapters remain fake.
- Existing offline replay passed against its own temporary fixture directory: text/photo/voice routing, source references, deduplication and restart. [Actual offline formatting excerpts](offline-examples.md).
- Existing full-suite coverage includes legacy outbox migration, SQLCipher migration/wrong-key handling, authorization at ingestion/processing/delivery, multi-child context, stale/quoted approvals and concurrency, source uncertainty, and quiet Calendar retry/recovery.
- `git diff --check` passes. Only source, tests and UX documentation changed; no configuration, dependency, credential, database or media artifacts are part of the branch.

## Integration decisions

- Reconciled all three parent-answer hooks and their naming conflict. Shortcut expansions cannot supply cart consent, and follow-ups cannot create carts. New proposals also require fresh unquoted/unforwarded typed DM requests; exact approval handling remains unchanged.
- Connected the persisted, exact-message read-aloud intent to DM-only delivery policy. Context retains the requested English/Hindi/Tamil language for follow-ups, including after encrypted restart. Independent questions choose their own topic and current language again.
- Context scope additionally includes the current student/class authorization set and class-wide-only flag. Changed access invalidates the old selection before sending reference metadata to the provider.
- Teacher clarification retains original source timestamp in formatted provenance and sends its quoted acknowledgment before optional Calendar work. One original source ID drives the fact, reminders and Calendar intent.
- Kept plain notes supported by the narrow parser; blocked unsupported activity categories, replacements and non-active update statuses. Ambiguous numeric dates and missing-year month/day forms do not accept model date guesses.
- Added English/Hindi/Tamil voice-progress, clarification and terminal Calendar/delivery error copy. Source topics/items/uncertainty remain source content. Cart command syntax and numerical amounts remain exact.
- General brain remains disabled by default. Sarvam remains the brain, speech and OCR provider; no runtime dependencies were added.

Feature notes describe their individual commits. This integration record supersedes their unfinished audio/localization hooks. Intentional scope remains narrow: teacher date-only completion accepts English relative dates, ISO/full English dates or a year completing a day/month; other date phrasing needs a full corrected notice. Existing reminder/Drive and detailed cart copy retain English fallback as documented in the welcome feature notes. No unsupported activity-update workflow, real checkout, WhatsApp interactive menus or dashboard was added.

## Real-device acceptance remaining

A separate user-assisted handset rehearsal must check WhatsApp quotation rendering, perceived acknowledgment timing, voice playback/preferences, actual handwriting OCR and short-voice STT/TTS in English/Hindi/Tamil, and real Calendar authorization/delivery. Synthetic checks cannot establish provider or handset reliability.
