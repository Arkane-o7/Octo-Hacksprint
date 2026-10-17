# Octo

A small WhatsApp school-assistant demo: a teacher's class requirement and science
syllabus photo become saved facts; a parent asks by voice and receives a cited
written answer plus speech. Sarvam handles the live language understanding,
Document AI, STT and TTS. WAHA handles WhatsApp. SQLite holds facts and jobs.

**Current status:** the full original demo is not complete. Live
teacher text works; broader conversational processing is experimental and disabled by default
(`OCTO_GENERAL_BRAIN=false`) after inconsistent live API results. Reminders, PDF
filing, Calendar and simulated carts are implemented, with the live limits below.
Three real images were inspected, and unsupported metadata in one handwritten
result was corrected. Human voice input, a full parent rehearsal and live Google
integration remain unverified. See [VALIDATION.md](VALIDATION.md) for observed
results and limitations; tests are not proof of live delivery. Account identities
and detailed operator reports are kept out of this public repository.

## Run the offline demo now

From your checkout directory:

```sh
uv sync --python 3.12
uv run python -m octo.setup init
uv run python -m octo.replay
uv run pytest -q
```

Replay creates an isolated temporary database and removes it afterward. Every
reply is marked **OFFLINE DEMO**. The photo/audio inputs are text markers, and
responses are canned fixtures. It performs no OCR, transcription, synthesis,
WhatsApp delivery or external API calls. It never overwrites live records.

To serve the local app in the default offline mode:

```sh
uv run uvicorn octo.app:app --host 127.0.0.1 --port 8018
```

`GET http://127.0.0.1:8018/health` reports local app health. Offline mode rejects
the WhatsApp webhook so fixtures cannot accidentally become live replies.
Port 8018 avoids the pre-existing service on port 8000.

## Connect the dedicated live demo

Use a separate WhatsApp account for Octo. The bot account must be different from
the teacher and parent senders; its own messages are ignored to prevent loops.
Create one test group containing the bot and designated teacher. Parents ask
questions in DMs to the bot. Do not pair a personal account or add personal groups.
WAHA is an unofficial linked-device bridge, so pairing and message compatibility
must be checked on the actual account.

Every member of a configured WhatsApp class group other than its teacher gets
the **parent** role. Group members can ask about shared class notices in the
group or in DMs. Non-members receive no automated replies, including numbers
listed in the parent roster. Live group membership is checked through WAHA
before ingestion, processing and delivery; a failed lookup does not reuse old
membership. Phone/LID aliases come from the transport's participant list.
Only configured teachers can save or update notices. Existing `parents` entries
retain their linked-student access and language preferences. New group members
see only class-wide facts for groups they belong to; group answers always use
only that group's class-wide facts. Individual records still require an explicit
account link, and message text cannot create that link. Offline replay uses
synthetic roster membership and never checks a real WhatsApp group.

1. Open `.env` locally and set `SARVAM_API_KEY`. `setup init` generates the two
   API/webhook secrets and disabled-dashboard passwords for a fresh checkout;
   it preserves an existing `.env`. Never commit or paste this file.
2. Start Docker Desktop, then run:

   ```sh
   docker compose up -d
   uv run python -m octo.setup status
   ```

   On this Mac, if `docker` is not on PATH, use
   `/Applications/Docker.app/Contents/Resources/bin/docker`.
   The image is pinned to `devlikeapro/waha:noweb-arm-2026.9.2`. The dedicated
   volumes are named under `octo-demo`; no Hermes or personal session is reused.
3. Once the dedicated account is ready, explicitly create/start its session and
   get the QR:

   ```sh
   uv run python -m octo.setup pair
   open data/pairing-qr.png
   ```

   Scan it from that phone's WhatsApp **Linked devices** screen. If WAHA is still
   starting, repeat `pair` after a few seconds. It does not reset an existing
   session. Confirm `WORKING` with `setup status`. Remove the QR file after pairing.
4. Run `uv run python -m octo.setup groups` on this dedicated account to find the
   test group's ID. Copy `roster.example.json` to `roster.local.json`. Replace the
   teacher/parent IDs and group ID with designated real IDs. Keep the fictional
   student names. Phone identities normally use `91…@c.us`; group IDs end in
   `@g.us`. Verify the actual envelope: WhatsApp can send a `@lid` identity, which
   must match a verified roster alias or its transport-provided phone alias.
   Never infer identity from display names, quoted messages or message text.
5. Set these values in `.env`:

   ```dotenv
   OCTO_MODE=live
   OCTO_ROSTER=roster.local.json
   ```

   The initial model settings are `sarvam-105b`, `saaras:v4` and `bulbul:v3`.
   `SARVAM_DOCUMENT_LANGUAGE=en-IN` is the initial English-board setting; choose
   the supported document language for the actual sample. Mixed-script board
   accuracy is a live check, not an assumed capability.
6. Check configuration and start exactly one app worker:

   ```sh
   uv run python -m octo.setup check
   uv run uvicorn octo.app:app --host 0.0.0.0 --port 8018
   ```

   Docker delivers signed webhooks to `host.docker.internal:8018`. Do not use
   multiple workers; this demo has one SQLite-backed worker. WAHA's API is bound
   to 127.0.0.1:3000. Use that exact IPv4 address: `localhost:3000` timed out on
   this Mac. HMAC authentication is required on the app webhook.
7. Prove the short text exchange first: teacher sends “Bring crayons and a
   drawing book tomorrow.” Wait for the saved confirmation. Aarav's parent asks
   “What does Aarav need tomorrow?” Confirm the date and source against the
   original message. Only then proceed to photos and voice.

The helper's pairing/group routes follow the
[WAHA session documentation](https://waha.devlike.pro/docs/how-to/sessions/) and
[group documentation](https://waha.devlike.pro/docs/how-to/groups/). Pairing is a
manual account action, not something offline replay performs.

## Supported flow and operating limits

By default, live text and speech use the established requirement/syllabus/dated
class-day extractor. This still does not handle general chat or event changes.
The experimental `OCTO_GENERAL_BRAIN=true` path uses a broad Sarvam proposal. Its
category is open-ended: notices, homework, events, supplies and other school
facts need not match a hardcoded topic. Code validates class/student scope,
source references and state transitions before committing. Questions and
ordinary conversation should not create records. Updates retain their original
sources; ambiguous cancellations or postponements request clarification.

Photos and PDFs use a persisted Sarvam Document AI job, then Sarvam chat for
structuring. Readable facts and unclear passages stay separate. JPEG, PNG and
PDF inputs are limited to 20 MB; keep the demo to one board or a short PDF.
Incoming audio must be shorter than 30 seconds. OGG/Opus is passed to Sarvam STT;
Bulbul produces MP3 which WAHA converts to a WhatsApp voice note. Text remains
available if speech fails. The parent's `language` and `voice_replies` are saved
roster preferences; voice questions also request spoken replies.

Facts, replacements, jobs, reminders and approvals are in SQLite. Dates use
Asia/Kolkata. Reminders default to 18:00 the day before the event, or 07:00 on the
event date when the evening has passed. Set `OCTO_REMINDER_TIME` as HH:MM to
change the evening time. The app must remain running. Only configured parents
receive reminders; replacing/cancelling a fact stops its obsolete reminders.
Past-date reminders and recipients whose authorization changed are suppressed.
Existing records saved before a parent is configured are not automatically
backfilled: send a fresh demo notice after adding the parent.

The simulated stationery catalogue supports crayons, drawing book, pencils,
eraser, ruler and notebook, one of each. Ask in a parent DM to prepare a cart.
Reply with the exact displayed `APPROVE CODE`, `CHANGE CODE crayons, drawing
book` or `CANCEL CODE`. Codes expire after ten minutes and bind the parent, chat,
version, items and total. Changes invalidate the old code. Only fresh typed
commands work; documents, forwards, quotes and voice cannot approve. Every cart
is labelled SIMULATED: no merchant access, real stock, checkout or payment.

Configure each designated parent in ignored `roster.local.json`. The optional
`demo_parent_id` teacher mapping supports an explicit single-phone rehearsal;
leave it absent when testing separate teacher and parent accounts. Follow
[DEMO.md](DEMO.md) for the rehearsal sequence.

Forwarded teacher notices need a fresh confirmation containing the full notice.
WhatsApp message edits/deletes are not applied automatically: post a new explicit
correction. Individual student questions and carts use DMs; teacher ingestion is
restricted to the allowlisted group. Multi-child accounts must identify the
child. This is one fictional demo school, not production multi-school tenancy.

## Optional Google Drive filing

The easiest current setup is the user-run helper in **`GOOGLE_SETUP.md`**. It
uses a Desktop OAuth client, opens Google consent in your browser, creates one
dedicated Drive folder and secondary Calendar, and writes the local `.env`.
No new dependencies are required:

```sh
uv run python -m octo.google_setup --client-secret data/google-client.json
```

The helper requests only `drive.file` and `calendar.app.created`. Its folder is
created by this client, so it does not need arbitrary-Drive access or a Picker.
The manual credential configuration below remains supported.

Create a dedicated demo folder in an explicitly chosen Google account. Enable
Drive API in its Cloud project, configure OAuth consent/test users, and authorize
a desktop OAuth client. Save the local authorized-user JSON containing
`client_id`, `client_secret`, `refresh_token` under ignored `data/` and set:

```dotenv
GOOGLE_DRIVE_CREDENTIALS=data/google-oauth.json
GOOGLE_DRIVE_FOLDER_ID=the_explicit_demo_folder_id
```

Use `drive.file` access where the chosen demo root was created or explicitly
selected by this client; a manually pasted arbitrary folder ID alone does not
grant that scope access. See Google’s [scope documentation](https://developers.google.com/workspace/drive/api/guides/api-specific-auth). Confirm actual folder access during setup. Restart the
worker after configuration. No OAuth connection has been made in this workspace.
The adapter refreshes the token, creates subject/chapter folders under that root,
returns Google's real file ID/link, and inherits existing permissions. It never
makes files public or changes sharing. Verify the intended parent can open the
link on their own account. The demo currently handles a single clear subject
and at most one chapter per PDF; ambiguous or individual-student documents remain
local and need clarification/resending. With missing credentials the reply says
"retained locally" and creates no Drive link. After setup resend that PDF.
For an interrupted/unconfirmed upload, check Drive before manually retrying.

## Validation and recovery

```sh
uv run pytest -q
uv run python -m octo.replay
# Opt-in real Sarvam calls on synthetic inputs; captured delivery only:
uv run python scripts/live_acceptance.py --live-apis
```

The live-API check explicitly exercises the experimental broad handler, even
when the running app has it disabled. It writes dated evidence to `data/validation/` and uses an
isolated temporary database. It never sends WhatsApp or calls Google. It cannot
replace the actual teacher/parent rehearsal in `DEMO.md`.

Live data is `data/live/octo.sqlite3`; offline server data is separate under
`data/offline/`. Media stays under `data/media/`. Sources retain message identity,
sender, timestamp and original text/media locally. Parents receive scoped facts
and minimal citation metadata, not the unfiltered body of a multi-student message.
There is no document browsing UI. A WhatsApp send returning an ID does not prove
that a phone received or played it.

Exactly one worker must run. Duplicates are suppressed by session/chat/message
identity. Applied model decisions, OCR jobs and queued work survive restart.
An interrupted outbound send is marked `uncertain` and is never blindly retried.
Stop the app before copying/resetting a database; use SQLite backup while it is
running. To rehearse fresh data, stop it, set a new `OCTO_DATA_DIR`, then restart.
Keep previous evidence. Stop WAHA with `docker compose stop`.

## Google Calendar

Set `GOOGLE_CALENDAR_ID` to the dedicated secondary calendar and
`GOOGLE_CALENDAR_CREDENTIALS` to the same authorized-user JSON (defaults to the
Drive credential path). The setup helper does this. Primary/personal-calendar
IDs are rejected. On startup and new saved facts, the app queues clear,
future-dated, class-wide records. All-day events carry the structured details and
source reference. Private/student records, unclear records and undated notes do
not sync. Google invitations and default reminders are disabled.

Validated replacements remove obsolete event IDs before adding the replacement.
Deterministic IDs, persisted jobs and bounded retries avoid duplicate events on
restart. Use `uv run python -m octo.google_setup --retry-calendar` after fixing
OAuth if jobs exhausted their three attempts. The broad natural-language update
parser remains disabled; adapter support does not establish live cancellation
accuracy. Calendar is implemented and mocked tests pass, but real Google sync
is unverified until consent and a live event check are completed.

No dashboard, merchant connection, deployment or persistent macOS service is
installed. These are not implied by local success.
