# Octo validation — 17 October 2026

**The complete live demo is not yet verified.** The public repository includes
working components and isolated tests, with the limits below. Real account
identities, messages, media, credentials and detailed operator evidence remain
local and are excluded from Git.

## Reproducible local checks

- Full suite: **279 tests passed** with Python 3.12. Tests use synthetic inputs,
  temporary storage and mocked remote responses; they do not prove live delivery.
- `python -m octo.replay` is an explicitly labelled offline demonstration. It
  uses canned fixtures, performs no recognition or network calls, and cannot
  stand in for a live WhatsApp/Sarvam/Google demonstration.
- Covered boundaries include HMAC verification, sender/student scope, duplicate
  messages, persisted OCR jobs, replacement facts, reminder suppression,
  deterministic Calendar IDs, uncertain-write recovery and exact parent-bound
  simulated-cart approvals.

## Observed live evidence and remaining checks

| Capability | Observed evidence | Remaining limitation |
| --- | --- | --- |
| Teacher messages and requirements | Real teacher text reached the dedicated WhatsApp group; Sarvam extracted requirements and class-day notices and the app replied. | Complete repeated teacher/parent rehearsal remains outstanding. |
| Photo/document understanding | Three real images were processed, including handwritten notes. A sampled result invented metadata; extraction guards were repaired and the saved record was transparently corrected. | Board glare, angled shots, mixed scripts and handwriting reliability remain unverified. Never infer missing topics or dates. |
| Parent questions | An actual parent DM was received and answered; an initial relevance error required a grounded correction. | Question relevance and preferred output language are not consistently proven across inputs. Separate-parent isolation is tested locally, not established by a full live rehearsal. |
| Regional speech input | Real Sarvam STT handled generated Hindi samples. | Incoming human voice notes are unverified. A generated Tamil sample changed a word; Tamil fidelity is not a pass. |
| Spoken answers | Real Sarvam speech was produced; a designated Hindi WhatsApp playback test was confirmed by the operator. | This does not establish every parent voice reply or every language. |
| Cancellation and postponement | Structured replacement, old-reminder cancellation and retained syllabus logic are implemented and tested locally. | The broad natural-language parser remains experimental and disabled by default after inconsistent live API runs. |
| PDF to Google Drive | After real OAuth consent, the Drive adapter uploaded a clearly labelled sample PDF into the app-created demo folder. Repeating the upload reused the same file ID. The folder was verified in Chrome. | Actual incoming WhatsApp PDF and recipient link access remain unverified. The sample upload proves the Google adapter, not the complete messaging flow. |
| Google Calendar | Real OAuth created a dedicated secondary calendar. The adapter created and read an all-day test event, reused its ID on repeat sync, moved its date, and deleted the disposable event. No attendees or default reminders were present. | Worker-level WhatsApp-to-Calendar synchronization still needs verification after loading the Google configuration. No primary calendar is used. |
| Reminders | Scheduling, obsolete-record suppression and authorization checks have local tests. | A timed delivery to the designated parent is still unverified; the worker must remain running. |
| Simulated stationery cart | Fixed prices, exact approval codes, parent/chat binding, expiry, changes and replay rejection are tested. | Full parent WhatsApp exchange remains unverified. No merchant, stock, payment or checkout integration exists. |

The broad handler's last recorded synthetic-input live API sequence passed
**7 of 10 checks**; an earlier sequence passed 9 of 10 with a different failure.
Observed failures included cancellation clarification/targeting, structured
parsing, compound dates and PDF structuring. This variation is why
`OCTO_GENERAL_BRAIN=false` remains the default. Mocked tests do not override those
observations.

## Before presenting it as a live demo

Follow [DEMO.md](DEMO.md) with fictional school content and dedicated accounts.
Complete the main story twice with fresh message IDs. Verify the original image
against every saved field, human Hindi/Tamil recordings against the transcript,
parent receipt/playback, a genuine PDF upload/link, a Calendar event, timed
reminders and approval boundaries. Record failures as well as successes.

Use [GOOGLE_SETUP.md](GOOGLE_SETUP.md) for the manual consent step. Confirm access
with the intended viewer; the app never makes Drive files or calendars public.
If a service fails, explicitly identify the offline fixture replay or locally
captured API check being shown. Neither is successful live WhatsApp delivery.
