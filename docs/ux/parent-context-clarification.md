# Parent follow-up context and narrow teacher date clarification

Implemented on an isolated feature branch; general brain remains disabled by default.

## Parent references

A structured Sarvam intent pass distinguishes independent questions from reference,
date, language and audio follow-ups. The existing four-argument answer API remains
compatible. Offline classification is explicitly a small synthetic fixture, not a
claim of multilingual live understanding.

The encrypted Store connection persists a 30-minute selection scoped by session,
chat and verified caller. It contains student IDs, at most eight cited source IDs,
extraction fingerprints and a bounded previous question; it never stores answer
prose as facts. Each turn resolves membership first and fetches authorized current
facts again. Missing/replaced/amended facts, expired selection and ambiguous links
ask for a full question. Explicit questions do not inherit prior restrictions;
multi-child follow-ups use the previous authorized child. Date follow-ups retain
the topic; language/audio turns restrict the answer to current selected facts and
instruct the provider not to recalculate event dates. Cart creation is disabled for
all follow-ups; existing fresh typed approval handling remains separate.

Delivery integration hook: `ContextStore.get(event, parent, 'answer_intent')`
returns bounded per-message metadata, including `source_key` and `read_aloud`.
Match the exact source key. This is an intent signal only, never permission to
send audio; the delivery worker must apply DM/group policy. This change does not
itself add audio to a text request. At most eight such intents are retained per
scope, with a 30-minute TTL.

## Teacher date completion

Supported narrow-parser undated supplies, syllabus and whole-class day notices
create a pending slot scoped by session/chat/teacher/class/source. Pending slots
expire after 24 hours (both receipt age and message timestamp age are checked).
At most eight original slots plus an ambiguity marker are retained per scope.
Multiple pending notices require a full corrected notice, rather than choosing
the latest. Unreadable/incomplete or conflicting extraction uncertainty does not
create a date-only completion target.

Accepted replies are date-only: today/tomorrow/day after tomorrow, ISO dates,
English day-month-year, or a four-digit year completing an original day-month.
Relative dates use the reply timestamp in Asia/Kolkata. No pending target means
no write. Forwarded/quoted replies, other teachers, chats, classes and parents
cannot complete a target. Other natural-language or multilingual date replies
still require a full corrected notice; widening this grammar needs validation.

Completion atomically amends the same source ID and consumes pending state. It
preserves original text/media/OCR and adds follow-up message provenance. Durable
completion/reply markers make retries safe and prevent stale OCR from restoring
undated content. Existing reminder/calendar reconciliation uses the same source
ID, so it does not create a second event. This does not introduce cancellation or
rescheduling of unsupported activities.

## Acceptance and integration

`tests/test_followup_context.py` exercises realistic text/photo/date conversations,
restart/retry, invalid context, expiry, multiple children, explicit topic changes,
language/link/audio requests and cart suppression. The live-policy scheduling test
uses synthetic adapters only and checks one calendar job and one reminder per
eligible parent. Existing membership tests cover process/delivery revocation.

Message hooks for translation: `context-clarify`, `date-clarify`, `date-clarified`.
The additional initial date question currently accompanies the normal saved notice
for undated supplies/syllabus; integration may combine these presentation strings.
Shared-file changes are localized to core initialization, narrow teacher hooks and
`_answer`; no outbox schema or calendar notification policy was changed. The
`test_app.py` mock now recognizes the additional Sarvam classification request.

Remaining handset/provider checks: multilingual and romanized follow-up intent;
“And Friday?” with real conflicting school sources; precise language-only restating;
notes/calendar reference UX; midnight date completion; audio under final DM/group
policy. No live messages, services, credentials, databases or restarts were used.
