# Welcome/help and fixed-message language

Implemented on `codex/octo-welcome-i18n`, based on `715fe57ef94c3a9487296eedf979692f5e39f2d6`. All work and synthetic tests use the isolated worktree. No live messages, service restarts, credentials, primary-checkout edits, or new dependencies.

## Behavior

- Exact greetings/help in English, Hindi and Tamil (plus namaste/namaskar/vanakkam) receive compact help without invoking AI or requiring a teacher source. A greeting plus a substantive question follows the normal answer path.
- First substantive parent DM appends a welcome after the answer, not before it. Later substantive DMs do not repeat it. Explicit greetings/help can be repeated. Failed requests and cart commands do not consume first-answer onboarding.
- Context displays configured linked children, otherwise authorized class labels. No inferred child relationships. Bare parent greetings in groups are silent; explicit group help shows only the three examples, without child names or welcome text. Teacher processing remains separate.
- Exact `Tomorrow`, `Next test`, `Find notes` and the displayed Hindi/Tamil equivalents expand to questions on the existing scoped, source-validated answer path. They do not create facts, events or documents. Find notes clarifies when saved study records span subjects. Existing linked-child clarification remains; answers with no scoped records use local no-data copy.
- Expanded shortcut wording never supplies the quote used to authorize a simulated-cart proposal. Existing fresh typed, exact parent/chat/code approval logic is untouched.
- Ingestion, processing and delivery membership checks remain. Help/welcome replies use existing source-bound outbox keys and delivery guards.

## Localized and fallback copy

`octo/i18n.py` uses exact English copy as a deterministic catalog key, with English/Hindi/Tamil variants. No translation model calls.

Translated: welcome/help/context, shortcut questions, no-data and other-child permission messages, child/subject clarification, teacher media acknowledgments, unsupported input/notice and class/date clarifications, forwarded-notice warning, common media/document/voice failures, generic failure heading/body, unavailable/offline audio messages, saved-notice labels and presentation-generated full-date clarification. Saved notice content, source names, summaries, topics, instructions and existing uncertainty strings remain as supplied. Dates retain readable English day/month abbreviations.

Cart translation is deliberately limited to exact whole lines: simulation/no-purchase warning, fixed-demo-price/no-merchant warning, and action/expiry heading. Codes, APPROVE/CANCEL/CHANGE command lines, item names, amounts, cart title/version/total and detailed action outcomes/rejections remain English. This preserves exact command syntax and existing warning text. No cart implementation changes.

Calendar/Drive workflows, reminder copy, delivery-level audio uncertainty, optional disabled-general-brain decision messages and provider-specific safe errors not in the catalog retain existing English fallback. Existing source/document/calendar labels for other languages in `presentation.LABELS` are unchanged. Integration can add catalog entries without changing permissions or workflows.

Language: current Tamil/Devanagari script is used for fixed copy; Marathi STT/roster signals are retained for shared Devanagari. Successful STT language is retained for ambiguous/romanized transcripts. Typed ASCII prose is English, except recognized greeting aliases. Unheard audio has no usable language signal and uses the roster fallback (unlinked member default currently Hindi). Other unsupported language copy falls back to English; existing answer/source labels still support their prior languages. Romanized language detection beyond explicit aliases is limited. Translations have not received human language review.

## Integration contract

New helpers: `octo/i18n.py`, `octo/welcome.py`. New tests: `tests/test_welcome_i18n.py`. Existing `tests/test_core.py` changes only two assertions whose Hindi voice replies are now localized.

Core hooks are localized to constructor, `_ui_language`, `reply`, successful STT metadata, `fail`, `_save_extraction` presentation call, and the early help/shortcut/clarification portions of `_answer`. Its AI prompt structure is unchanged; only exact shortcuts supply expanded question text. Preserve `original_text` for the cart quote check when combining other changes. Presentation adds optional `language` parameters (English defaults preserve existing callers).

Two independent UI metadata tables share the existing Store/SQLCipher connection: `welcome_seen(parent_id, source_id)` and `ui_languages(source_id, language)`. No storage, context or outbox schema rewrite. First-use source identity makes retries render consistently. A queued welcome consumes first use even if delivery later becomes cancelled/uncertain; explicit Help always remains available. STT metadata survives normal restart; a crash between transcript and language writes can fall back to transcript/roster detection.

The integration owner should cherry-pick the feature commit and resolve overlaps in `reply`, `_answer`, and presentation call sites. No branch push or merge to main is part of this feature.

## Acceptance evidence

Offline tests cover first use after substantive content, repeated help, restart, no facts, linked/unlinked/outsider scope, silent group greetings, group help privacy, typed en/hi/ta, successful STT and unheard fallback, supported source scope for all shortcuts, subject clarification, localized permission/unsupported messages, source negation and uncertainty, membership revocation before welcome delivery, unchanged command/code lines, and shortcut text not authorizing a cart. Existing cart, delivery, source, presentation and language tests remain in the full suite.

Final validation: `python -m pytest -q` — 346 tests pass using the primary checkout's existing Python executable with worktree cwd and temporary synthetic databases only.

## Remaining manual checks

- Human Hindi/Tamil review for fluency and precise negation, including shared-script/romanized cases.
- Handset wrapping of welcome, saved labels, subject/child clarification and mixed-language teacher topics.
- Authorized first/repeated DM and group help against a real approved test group; no such messages were sent here.
- Real STT/TTS language behavior and source-grounded Next test/Find notes responses with representative teacher notices; synthetic tests do not establish model accuracy or document availability.
- Confirm the documented fallback language for unheard/unlinked audio is desired for the demo roster.
