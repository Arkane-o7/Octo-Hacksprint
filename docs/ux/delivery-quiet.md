# Delivery and quieter replies

Implemented on `codex/octo-delivery-quiet`, based on preserved baseline
`715fe57ef94c3a9487296eedf979692f5e39f2d6`. No live service or primary checkout changes.

## Behavior

- Text replies quote their incoming message, not the older message it might quote.
  Outbox migration adds nullable `reply_to` and `reply_chat_id`; existing queued
  replies remain unquoted. Both survive reopen. Store rejects cross-chat quotes;
  delivery rechecks source message, destination and current authorization.
  Reminders stay unquoted.
- Existing WAHA `send_text(reply_to=...)` quotes the first chunk. Uncertain sends
  stay uncertain; there is no unquoted retry fallback.
- Voice processing queues one short status under `<sid>:voice-ack`, then attempts
  that specific pending reply before STT, even with a queue backlog. Restart and
  reprocessing cannot insert or resend another acknowledgment. An uncertain ack
  is not retried. No percentages or typing endpoints were added.
- `octo.delivery.should_speak` selects automatic audio only in DMs: voice input,
  or typed input with saved `voice_replies: true`. Newly resolved members default
  false. Existing explicit roster preferences are preserved. Written answers are
  attempted by their own queue key before TTS; TTS failure leaves them intact.
- Successful Calendar sync persists actual metadata without a success bubble.
  A pending saved-notice answer is attempted before Google work, including with
  an outbox backlog. Actual URLs remain available through on-demand link requests.
- Calendar exceptions retry quietly twice, then persist terminal failed status
  and queue one quoted error under `<source_id>:calendar-error:<calendar_id>`.
  The error explains that automatic retries stopped. Queued errors are blocked
  after recovery or Calendar configuration changes. Stored errors distinguish
  pending retry from exhausted retries. Existing retry intervals remain.

## Acceptance checks

Full offline suite: **344 passed**, using the baseline checkout's Python
environment with this worktree as cwd. No credentials or real contacts loaded.

`tests/test_quiet_delivery.py` and `tests/test_calendar_workflow.py` cover legacy
schema migration, reopening, cross-chat rejection, uncertain-send behavior,
acknowledgment ordering/deduplication, the 12-case audio policy matrix, new-member
defaults, quiet transient recovery, one terminal error, stale-error suppression,
and saved reply before Google with backlog. Existing tests cover revoked access,
TTS failure preserving text, and WAHA first-chunk quoting.

## Integration and manual handset checks

- Cherry-pick the feature commit onto the integration branch. Shared-file edits
  are localized to delivery/outbox, voice ack, Calendar workflow, Roster default
  and answer audio policy/delivery. No extraction or parent prompt changes.
- The language worker should localize new `voice-ack` and revised `calendar-error`
  copy. Current strings follow the existing English status-copy convention.
- Explicit read-aloud conversational intent remains the conversation worker's
  responsibility. The helper covers automatic policy, not intent parsing.
- On an authorized test handset, verify quote rendering, first-chunk attribution,
  voice status ordering, DM preferences, quiet groups and failure status copy.
  No handset or live provider validation was performed.
- Old already-queued Calendar success bubbles retain their existing stale-source
  guard; newly successful syncs never enqueue them.
