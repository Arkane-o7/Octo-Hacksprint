# Numbered menus over WAHA

By default this feature uses ordinary quoted WhatsApp text messages. With
`OCTO_TAPPABLE_MENUS=true`, private-chat menus use WAHA NOWEB's free `sendList`
endpoint: one localized Choose button opens a list of tappable options. Main,
Settings, Language, Audio and short answer follow-ups are supported. Child
selection and long answers retain numbered text. No provider or dependency is
added, and the WAHA session is retained.

This is a list picker, not a row of inline reply buttons. WAHA marks `sendButtons`
as broken and warns that list messages can also stop working. Check rendering
and selection on the actual handset. The same message includes numbered choices
as a fallback. A definite unsupported/invalid-request response sends text instead;
timeouts, server errors and missing message IDs remain uncertain and are never
automatically resent. Set the flag false and restart to return to text menus.

List replies carry a menu-specific option ID. The router verifies the current
parent/chat/session, scope, delivery and expiry before using it. Stale, forwarded
and cross-parent selections cannot change preferences. Display titles cannot
become cart approvals or freeform model requests. Menu navigation makes no AI call.
The existing speech and question actions still use Sarvam credits.

See the [WAHA list-message contract](https://waha.devlike.pro/docs/how-to/send-messages/#send-list).
`OCTO_MENU_STYLE=buttons` explicitly opts into the deprecated inline quick-reply
endpoint instead of the list picker. This is a handset compatibility experiment,
not a guarantee: WhatsApp may accept the send without displaying the buttons.
Button replies use the same scoped option IDs and validation as list replies.
On 18 October, the operator confirmed the list picker opens; a real Main →
Settings selection was processed and its reply sent. The operator disliked the
modal list UI. Inline mode was then enabled, but the operator reported no visible
reply. No fresh input was recorded after that switch, so this does not distinguish
message ingress from button-rendering failure. Inline rendering remains unverified.
The running demo was returned to numbered text menus. All **434 local tests** pass;
they do not establish native-button support on the handset.
The tappable-menu change passes **426 tests**, including 21 new normalization,
selection, isolation, fallback and uncertain-delivery checks. Tests use synthetic
adapters; actual list rendering still requires a handset check.

## Parent experience

In a private chat, send `menu`, `help`, `hi`, `hello` or a supported greeting.
English, Hindi, Tamil, Telugu, Marathi, Bengali and Gujarati menu copy is included.
Other menu languages fall back to English. Today, Tomorrow and Notes use a
question in the menu language; freeform school answers still follow the current
question's language.

Send `menu`, then `4` (Settings), then `1` (Language). The language choices are:

```text
1 · English
2 · हिंदी
3 · தமிழ்
4 · తెలుగు
5 · मराठी
6 · বাংলা
7 · ગુજરાતી
0 · Main menu
```

The heading and Main menu label are translated into the current menu language.
The original three numbers stay unchanged. Selecting a language saves it for
that parent in that private chat and shows the translated main menu. Neutral
commands (`menu`, `help`, `start`, `0`) preserve this explicit choice across
restarts. A greeting in another supported script can temporarily show that
language without overwriting the saved choice. Hindi and Marathi share a script,
so Devanagari menu commands use Marathi when it is the parent's preference.

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

## Language expansion validation

The menu tests exercise all seven language selections, persistence across store
reopen, translated settings and follow-up actions, question routing, and the
language passed to the speech adapter. They also check native-script commands,
invalid selections, and isolation between parents. These are synthetic adapter
tests; they do not certify translation quality or live speech pronunciation.
The full suite passes with **405 tests**, including **61 menu/onboarding tests**.
All seven language codes are supported by the configured Bulbul v3 adapter and
[Sarvam's language list](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/how-to/set-the-language).

## Original implementation validation and integration

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
