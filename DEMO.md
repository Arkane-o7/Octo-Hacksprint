# Octo live rehearsal

**Not yet completed end to end.** Use this checklist with real designated test
accounts. API tests on generated images/audio and captured delivery do not count
as a live rehearsal. Keep all school data fictional.

Before starting: bot is WORKING; correct teacher/group are allowlisted; add the
real parent number to `roster.local.json`; restart the single worker. Send fresh
notices so reminders include the newly configured parent. Set up dedicated Drive
OAuth/folder separately if demonstrating a real upload. Never invent a parent
identity, Google link or merchant connection.

Use one explicit future school date consistently. If the rehearsal already
contains a holiday notice and supplies for the same day, keep that evidence and
demonstrate Octo explaining the conflict, or use a different date. Do not silently
erase contradictory notices to make “tomorrow” look correct.

Two-minute story (allow processing to finish; do not promise fixed OCR latency):

| Time | Action | Visible proof |
| --- | --- | --- |
| 0:00–0:20 | Teacher posts “Bring crayons and a drawing book tomorrow.” | Saved date, items and source; reminder only if parent is configured. |
| 0:20–0:55 | Teacher uploads a real photo of handwritten “Class 5B, Science test [upcoming date], Chapter 6, Parts of a plant; roots and stems; pages 42–47; revise the labelled diagram.” | Sarvam OCR job then grouped checklist. Compare every field to the board. |
| 0:55–1:25 | Parent asks by voice: “आरव को कल क्या लाना है और विज्ञान की परीक्षा के लिए क्या पढ़ना है?” | Grounded parent-only written reply with both sources. |
| 1:25–1:45 | Play the Hindi response. | Audible answer agrees with the written facts. |
| 1:45–2:00 | Parent asks “Prepare a simulated cart for the crayons and drawing book.” | SIMULATED quote with items, INR 140 total and Approve/Change/Cancel commands. No purchase. |

If OCR is too slow for the timed presentation, process the photo beforehand and
say so explicitly. Do not substitute canned recognition silently.

Complete these acceptance checks outside the two-minute story:

Checks 1–3 exercise the experimental broad parser, which is disabled by default
after inconsistent live results. Validate it in a separate rehearsal before
claiming cancellation or postponement works live.

1. Create football practice for an explicit future date. Teacher sends a short
   Hindi, Tamil or Hinglish cancellation voice note. Verify transcription,
   exact event target, cancelled state and obsolete reminder suppression.
2. Create two different practices. “Cancel practice” must ask which one and
   leave both unchanged. Clarify in a fresh message with the exact date/title.
3. Postpone a Science test to another date. Confirm the old date is superseded,
   the original syllabus remains, and any reminder uses the new date.
4. Send the real Science Chapter 6 PDF. With Drive configured, open the returned
   link from the parent's Google account and inspect folder/file. Without it,
   expect explicit local-only retention; this is a blocked integration, not a pass.
5. Ask where the saved Science notes are; answer must cite the source and actual
   uploaded link, if one exists. Unuploaded files must not acquire fake links.
6. In the parent DM, change a cart. Old code must stop working; show updated
   items/total/new code. Cancel one cart and approve another. Replay approval
   and try a different parent: neither may approve. No checkout/payment occurs.
7. Schedule a near-term reminder in a disposable rehearsal database and keep the
   worker running. Confirm real parent delivery. Cancel another event before its
   reminder and verify no later reminder is delivered. Do not alter real notice
   dates merely to make the test pass.
8. Test a second allowed parent for isolation: Aarav's individual notice must
   not appear in Meera's answer. Unknown senders/groups must stay ignored.
9. Test a glare/angled/imperfect handwritten photo and human Hindi/Tamil notes.
   Compare names, class, dates, negation and every topic against the originals.
   Clarify missing words instead of filling them from general knowledge.
10. Restart once; confirm saved facts survive, accepted messages do not duplicate,
    and in-progress/uncertain deliveries are not blindly sent twice.

Record outcome, input/source ID, elapsed time and handset confirmation for each.
Run the main story twice with fresh message IDs. No complete live rehearsal has
been recorded yet; see [VALIDATION.md](VALIDATION.md) for the current gaps.

If a live service fails, say: **“This is the labelled offline replay, using
synthetic fixture responses. It does not call Sarvam or deliver WhatsApp.”**
Run `uv run python -m octo.replay`. Audio is explicitly skipped. The optional
`--live-apis` acceptance script uses real Sarvam but captures messages locally;
that is a third evidence type, never a replacement for handset verification.
