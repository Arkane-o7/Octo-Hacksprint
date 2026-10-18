# Offline formatting examples

Captured from `python -m octo.replay` on 18 October 2026 (Asia/Kolkata). These are synthetic fixtures, not real WhatsApp messages, OCR or speech. The replay uses temporary storage and explicit offline adapters without loading environment configuration.

Teacher supplies acknowledgment, parent voice-progress acknowledgment, and explicit offline-audio status:

```text
TO demo-class-5b@g.us
[OFFLINE DEMO — synthetic fixture responses; no live delivery]
✓ *What to bring*
Class 5B
Mon, 19 Oct 2026

• crayons
• a drawing book

_Saved · Ms. Rao · 18 Oct 2026 · 6:43 am IST_
```

```text
TO demo-parent-a
[OFFLINE DEMO — synthetic fixture responses; no live delivery]
🎙️ आपका वॉइस संदेश समझ रहा हूँ…
```

```text
TO demo-parent-a
[OFFLINE DEMO — synthetic fixture responses; no live delivery]
ऑफ़लाइन मोड में ऑडियो नहीं बनता; Sarvam से आवाज़ नहीं बनाई गई।
```

The combined automated transcript tests also verify same-chat quote IDs, topic retention across notes/calendar/language/read-aloud, and encrypted restart. Those metadata checks are not handset rendering evidence.
