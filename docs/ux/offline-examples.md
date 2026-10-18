# Offline formatting examples

Freshly rendered from the real Octo routing/presentation code with synthetic extraction and transport adapters, a temporary SQLCipher database and fixed illustrative timestamps in Asia/Kolkata. No API calls, actual OCR/speech or WhatsApp delivery. Fixture extraction explicitly supplies the two items without a date.

The database is closed and reopened between the first teacher message and “Tomorrow”. Each input below produces exactly one response.

## Teacher group: Bring crayons and a drawing book.

```text
[OFFLINE DEMO — synthetic fixture responses; no live delivery]
✓ *What to bring*
Class 5B

• crayons
• a drawing book

*Please confirm*
• Which date (including year) applies? Reply with just the date.

_Saved · Ms. Rao · 18 Oct 2026 · 10:00 am IST_
```

## Teacher group: Tomorrow

```text
[OFFLINE DEMO — synthetic fixture responses; no live delivery]
✓ *What to bring*
Class 5B
Mon, 19 Oct 2026

• crayons
• a drawing book

_Saved · Ms. Rao · 18 Oct 2026 · 10:00 am IST_
```

## Parent DM: Help

```text
[OFFLINE DEMO — synthetic fixture responses; no live delivery]
Hi! I’m Octo. I can help with saved school notices.
Linked children: Aarav
Try: Tomorrow · Next test · Find notes
```

Verified outcome: one fact, original text/source retained, date 19 October 2026, and follow-up provenance attached. No reminder or Calendar delivery is claimed in offline mode. Automated tests separately exercise scheduling through fake adapters.
