<p align="center">
  <img src="docs/assets/octo.png" width="160" alt="Octo, the purple octopus assistant">
</p>

<h1 align="center">Octo</h1>

<p align="center"><strong>An AI agent for the tools you already use.</strong></p>

<p align="center">
  <a href="#the-vision">Vision</a> ·
  <a href="#the-education-demo">Demo</a> ·
  <a href="#integration-status">Integrations</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#documentation">Documentation</a>
</p>

Octo is an AI agent designed to work inside the platforms you already use—
WhatsApp, learning management systems (LMS), Microsoft Teams, Google Classroom,
and more. Ask questions, find relevant information, get reminders, and take
action through a natural conversation.

The goal is to bring the agent into your existing workflow, so you don't need
another app to manage. Education is the first use case: helping teachers share
information and helping parents understand what their child needs next.

**This repository contains a WhatsApp-first education prototype.** The broader
platform vision, the product walkthrough, and the implemented integrations are
distinguished below.

## The vision

Useful information is already spread across class groups, course pages, notices,
documents, and team conversations. Octo's broader direction is to understand
that context and help people take the next step in the same place they work.

- **Ask:** Get a clear answer from the information you are allowed to access.
- **Find:** Retrieve the relevant notice, study material, source, or date.
- **Remember:** Keep track of requirements and upcoming activities.
- **Act:** Connect information to a workflow, with explicit approval where needed.

For education, that might mean turning a teacher's syllabus photo into a study
checklist or helping a parent obtain the supplies mentioned in a notice. The
same direction extends to learning and workplace platforms through additional
connectors.

## The education demo

A teacher posts a class notice. A parent asks a question. Octo connects the two.

1. **Share a notice.** A configured teacher sends text, a syllabus photo, a short
   voice note, or a PDF in the class WhatsApp group.
2. **Save the details.** Octo extracts supported facts, dates, requirements, and
   study topics while retaining the original source and any uncertainty.
3. **Ask naturally.** An authorized parent asks in a private chat or sends a
   short voice question.
4. **Get an answer.** Octo replies with relevant, access-scoped information and
   teacher/source references. Private-chat menus offer read-aloud and links.
5. **Take the next step.** Configured workflows support reminders, document
   filing, and Calendar entries. The product walkthrough also illustrates
   ordering supplies through Blinkit MCP, with parent review and approval.

> **Teacher:** Bring crayons and a drawing book tomorrow.
>
> **Parent:** What does Aarav need tomorrow?
>
> **Octo:** Crayons and a drawing book, with the saved date and teacher reference.

The shareable product walkthrough uses fictional school data and a WhatsApp-style
visual preview. Its voiceover is generated with Sarvam AI. It illustrates the
experience; it is not evidence that every displayed integration has completed a
live transaction.

## What the prototype includes

| Capability | Behavior in this repository |
| --- | --- |
| Teacher notices | Extract supported requirements, study checklists, and class-day notices from allowed teachers and groups. |
| Answers with sources | Answer parent questions from authorized saved facts, with readable teacher/time references. |
| Text and voice | Use Sarvam for language understanding, document extraction, speech recognition, and spoken replies. Answer language follows the current question or an explicit language request. |
| Parent menus | Offer Today, Tomorrow, Notes, Settings, read-aloud, and sources/links through ordinary numbered text replies. Menu copy supports English, Hindi, and Tamil. |
| Saved preferences | Remember private-chat menu language and audio preferences; ask multi-child parents which linked child they mean when needed. |
| Reminders | Persist scheduled reminders and suppress obsolete or unauthorized deliveries while the worker is running. |
| Documents and Calendar | File eligible PDFs in a dedicated Google Drive folder and sync eligible dated class facts to a dedicated secondary calendar after setup. |
| Approval flow | Demonstrate a stationery cart with parent/chat-bound, expiring approval codes. The implemented cart uses fixed demo prices and makes no purchase. |

## Integration status

| Platform or service | Status |
| --- | --- |
| WhatsApp | Implemented through WAHA, an unofficial linked-device bridge. Requires a dedicated account, configured class groups, and handset verification. |
| Sarvam AI | Implemented for language, document extraction, STT, and TTS. Live component checks are documented separately. |
| Google Drive | Optional OAuth adapter for eligible PDFs; folder access and recipient access must be verified for the configured account. |
| Google Calendar | Optional OAuth adapter for eligible future class-wide facts; uses a dedicated secondary calendar. |
| Blinkit MCP | Ordering integration shown in the product vision and visual walkthrough. This checkout includes the simulated cart/approval flow, not a live Blinkit connector. |
| LMS platforms | Part of the broader connector roadmap; no LMS adapter is included in this checkout. |
| Microsoft Teams | Part of the broader connector roadmap; no Teams adapter is included in this checkout. |
| Google Classroom | Part of the broader connector roadmap; no Classroom adapter is included in this checkout. |

### Current maturity

Octo is a single-school, single-worker prototype. There are documented live checks
for individual WhatsApp, Sarvam, Drive, and Calendar components, but a complete,
repeated teacher-to-parent live rehearsal remains outstanding. The broader
conversational update parser is experimental and disabled by default with
`OCTO_GENERAL_BRAIN=false`.

See [VALIDATION.md](VALIDATION.md) for observed results and remaining checks.
Offline fixtures and mocked tests establish local behavior, not live delivery or
language accuracy across every input.

## Quick start

### Requirements

- Python **3.11+**; Python **3.12** is recommended for the demo environment.
- [uv](https://docs.astral.sh/uv/) for dependency management.
- Docker and a dedicated WhatsApp account only when connecting the live bridge.

### Run the offline replay

```sh
git clone https://github.com/Arkane-o7/Octo-Hacksprint.git
cd Octo-Hacksprint
uv sync --python 3.12
uv run python -m octo.setup init
uv run python -m octo.replay
```

The replay uses an isolated temporary database and clearly labelled synthetic
text, photo, and voice fixtures. It makes no external API calls, generates no
speech, and sends no WhatsApp messages. It does not overwrite live records.
`setup init` creates a local `.env` on first use and preserves an existing file.

### Serve the local API

With the default offline configuration on a fresh checkout:

```sh
uv run uvicorn octo.app:app --host 127.0.0.1 --port 8018
```

Open [the health endpoint](http://127.0.0.1:8018/health) to check local app health.
The offline server rejects WhatsApp webhooks. There is no separate dashboard UI;
WhatsApp is the prototype's user interface.

### Connect live services

Follow [setup and operations](docs/OPERATIONS.md) to configure local credentials,
pair a dedicated WhatsApp account, and define teacher/group/student access. Live
mode requires a local database encryption key; existing plaintext databases need
the [documented migration](DATABASE_ENCRYPTION.md) first. Run exactly **one**
application worker.

Use [Google setup](GOOGLE_SETUP.md) for optional Drive and Calendar consent, then
follow the [live rehearsal checklist](DEMO.md). The bundled WAHA image targets
ARM64; other architectures require a compatible image.

## Access and reliability

- Only configured teachers can save class notices in allowed groups.
- Current class-group members receive parent access to class-wide facts.
  Individual student records require an explicit account link.
- Group responses contain only that group's class-wide information. Private
  answers recheck the parent's current access.
- Live group membership is checked at ingestion, processing, and delivery;
  failed lookups do not grant access from a stale membership snapshot.
- Sources, jobs, reminders, and approval state persist across restarts. Duplicate
  messages are suppressed; uncertain sends are not blindly retried.
- Live databases use SQLCipher. Credentials, media, logs, and linked-device files
  are outside that database encryption boundary and must remain private.
- Menu selections do not approve purchases. Cart approvals require a fresh,
  exact typed command bound to the parent and private chat.

Dates use `Asia/Kolkata`. Photos and PDFs are limited to 20 MB, and incoming voice
notes must be shorter than 30 seconds. More limits and recovery procedures are in
the [operations guide](docs/OPERATIONS.md).

## Development

```sh
uv run python -m pytest -q
uv run python -m octo.replay
```

Tests use synthetic adapters and temporary storage. For an explicit opt-in check
against real Sarvam APIs on fictional inputs:

```sh
uv run python scripts/live_acceptance.py --live-apis
```

That script captures delivery locally and never sends WhatsApp messages or calls
Google. Keep real API keys, OAuth files, rosters, school data, and session state
out of commits.

## Repository guide

| Path | Purpose |
| --- | --- |
| `octo/app.py` | FastAPI lifecycle, health endpoint, and signed WAHA webhook. |
| `octo/core.py` | Authorization, notice ingestion, parent questions, and queued work. |
| `octo/sarvam.py`, `octo/waha.py` | AI/speech/document and WhatsApp adapters. |
| `octo/menus.py`, `octo/menu_copy.py` | Numbered menus, preferences, and localized menu copy. |
| `octo/storage.py`, `octo/database.py` | Persistent state and encrypted live database access. |
| `octo/drive.py`, `octo/calendar.py` | Optional Google integrations. |
| `octo/cart.py` | Simulated stationery quotes and approval boundaries. |
| `octo/replay.py`, `octo/offline.py` | Isolated offline demonstration and fixture adapters. |
| `tests/` | Local behavior and integration-boundary tests. |

## Documentation

- [Setup, configuration, operating limits, and recovery](docs/OPERATIONS.md)
- [Live demo rehearsal](DEMO.md)
- [Observed validation and remaining gaps](VALIDATION.md)
- [Google Drive and Calendar setup](GOOGLE_SETUP.md)
- [Database encryption and migration](DATABASE_ENCRYPTION.md)
- [Numbered menus and saved preferences](docs/ux/numbered-menus.md)
- [Quoted replies and quieter delivery](docs/ux/delivery-quiet.md)
