# Numbered menus over WAHA

This feature uses ordinary quoted WhatsApp text messages. It does not call
sendButtons, add a provider, change the WAHA session, or require new dependencies.

## Parent experience

In a private chat, send `menu`, `help`, `hi`, `hello` or a supported greeting.
English, Hindi and Tamil menu copy is included. Other menu languages fall back
to English; the existing school-answer language handling is unchanged.

Example input and output pairs (school details below are illustrative):

**Parent:** `menu`

**Octo:**

```text
Octo · School help

1 · Today
2 · Tomorrow
3 · Notes
4 · Settings

Reply with a number, or ask a question in your own words.
```

**Parent:** `2`

**Octo:** a grounded answer to the tomorrow question, with its existing source
formatting, followed in the same bubble by:

```text
1 · Read aloud
2 · Show sources & links
3 · Ask another question
0 · Main menu
```

**Parent:** `2`

**Octo:** the saved sources for that answer, plus actual Calendar/document links
when present. No new model call is needed. Unconfirmed Calendar links are omitted.

**Parent:** `1`

**Octo:** an audio version of the same verified answer in private chat. In offline
mode, the existing synthetic-mode notice explains that no speech was generated.
Audio generation failure leaves the written answer intact and reports failure.

**Parent:** `0`, then `4`, then `2`

**Octo:**

```text
Audio replies

1 · Text only for typed questions
2 · Text + audio for typed questions

Voice questions still get text + audio in private chat.
0 · Main menu
```

**Parent:** `1`

**Octo:** confirms the saved preference and shows the main menu. Typed answers
stay text-only; explicit Read aloud remains available. Preferences survive restart.

**Parent with multiple linked children:** `What does my child need?`

**Octo:** a numbered list of only that parent's currently linked children.
Selecting a child answers the pending question for that child. A question that
already names a linked child bypasses this choice.

Freeform questions work at any point. Group requests for a menu receive a short
private-chat instruction; group school answers have no menu footer or audio.
Teacher greetings/help receive instructions without being extracted as school facts.

## Safety and delivery

- State is keyed by session, destination chat, parent identity and a fingerprint
  of the current roster scope. It never supplies permissions.
- Choices expire after 30 minutes. Only confirmed/fixture-delivered menus are
  selectable. Missing, expired or unconfirmed choices show a fresh main menu.
- Only typed choices execute menu actions. Forwarded choices and quotes of old
  messages cannot change settings. A reply quoting the currently confirmed menu
  is accepted; a fresh unquoted typed number is always supported.
- The input's menu snapshot is persisted before navigation changes state. A retry
  or restart cannot reinterpret the same number as an action on the next page.
- Read-aloud/source actions require the stored sources to remain accessible and
  unchanged. They cannot replay a replaced notice or another child's answer.
- Read-aloud outbox entries are deduplicated, including uncertain delivery. No
  uncertain send is retried as a new/unquoted message.
- Menus never create or approve carts. Existing natural-language cart proposals
  and fresh typed exact-code approval rules remain; choosing a child or day is
  not a purchase request.
- Preferences and menu snapshots use the existing Store connection, including
  SQLCipher in encrypted deployments. No new plaintext side database is created.

## Validation and integration

22 focused offline tests in `tests/test_menus.py` cover routes, saved preferences,
child scope changes, cross-parent/group boundaries, expiry, delivery uncertainty,
reopen/retry, stale and current quotes, audio failure/deduplication, current sources,
links on demand, cart boundaries, revocation, freeform questions, and encryption.
Full suite: **366 passed**. Tests use synthetic adapters and disposable databases.

Changes are isolated on `codex/octo-numbered-menus`, based on main merge `e6018bc`.
The main application integration is localized in `Octo.__init__`, the teacher-help
branch and `_answer`; menu state and copy live in new helper modules.
The separate `codex/octo-ux` integration branch has welcome/language/conversation
work not present in this base. If combined later, reconcile that branch's welcome
routing and preferences with this menu router rather than running both handlers.

No live messages, account changes, primary checkout edits, restarts or deployments
were performed. Remaining handset checks: quote rendering, long-answer chunking,
current-menu quoted selections, English/Hindi/Tamil copy, and live TTS playback.
