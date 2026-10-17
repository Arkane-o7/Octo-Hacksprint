"""Fixed-price simulated stationery carts. No merchant calls or purchases."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from sqlcipher3 import dbapi2 as cipher
import time


LABEL = "SIMULATED — no purchase made."
EXPIRY_SECONDS = 10 * 60
CATALOGUE = {
    "crayons": ("Crayons", 8000),
    "drawing_book": ("Drawing book", 6000),
    "pencils": ("Pencils", 2000),
    "eraser": ("Eraser", 1000),
    "ruler": ("Ruler", 1500),
    "notebook": ("Notebook", 4000),
}
ALIASES = {
    "crayon": "crayons", "crayons": "crayons", "crayon pack": "crayons",
    "drawing book": "drawing_book", "drawing books": "drawing_book", "drawing_book": "drawing_book",
    "pencil": "pencils", "pencils": "pencils", "pencil pack": "pencils",
    "eraser": "eraser", "erasers": "eraser", "ruler": "ruler", "rulers": "ruler",
    "notebook": "notebook", "notebooks": "notebook",
}
UNAVAILABLE = LABEL + "\nThis action is unavailable: check the code and parent chat, or request a new cart if it expired or was already used."
USAGE = LABEL + "\nUse exactly APPROVE CODE, CANCEL CODE, or CHANGE CODE crayons, drawing book."


def _canonical(quote: dict) -> str:
    return json.dumps(quote, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(quote_json: str) -> str:
    return hashlib.sha256(quote_json.encode()).hexdigest()


def _quote(items: list[str], version: int) -> tuple[dict | None, str | None]:
    skus = set()
    unknown = []
    for item in items:
        normalized = re.sub(r"\s+", " ", item.strip().casefold())
        normalized = re.sub(r"^(?:a|an) ", "", normalized)
        sku = ALIASES.get(normalized)
        if sku:
            skus.add(sku)
        else:
            unknown.append(item.strip() or "(empty item)")
    if unknown or not skus:
        detail = "Unknown demo catalogue items: " + ", ".join(unknown) + "." if unknown else "Please select at least one item."
        return None, (
            LABEL + "\n" + detail + " No new cart was created.\n"
            "Available demo items: " + ", ".join(name for name, _ in CATALOGUE.values()) + ". "
            "These are fixed demonstration prices, not live merchant availability."
        )
    lines = [
        {"sku": sku, "name": CATALOGUE[sku][0], "quantity": 1, "unit_price_paise": CATALOGUE[sku][1]}
        for sku in sorted(skus)
    ]
    return {
        "currency": "INR", "version": version, "items": lines,
        "total_paise": sum(line["quantity"] * line["unit_price_paise"] for line in lines),
    }, None


def _money(paise: int) -> str:
    return f"INR {paise // 100}.{paise % 100:02d}"


def _render(quote: dict, code: str) -> str:
    lines = [LABEL, f"Demo stationery cart — version {quote['version']}"]
    lines.extend(
        f"• {item['name']} × {item['quantity']} — {_money(item['unit_price_paise'] * item['quantity'])}"
        for item in quote["items"]
    )
    lines.extend([
        f"Total: {_money(quote['total_paise'])}",
        "Fixed demo prices; no merchant connection. One of each listed item.",
        "Code expires in 10 minutes. Reply in this parent chat:",
        f"APPROVE {code}", f"CANCEL {code}",
        f"CHANGE {code} crayons, drawing book",
    ])
    return "\n".join(lines)


class CartService:
    """Uses the caller's SQLite connection; never closes it or changes row_factory."""

    def __init__(self, connection: sqlite3.Connection):
        self.db = connection
        self.db.execute("""CREATE TABLE IF NOT EXISTS carts (
            code TEXT PRIMARY KEY,
            parent_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            quote_json TEXT NOT NULL,
            quote_hash TEXT NOT NULL,
            version INTEGER NOT NULL,
            created REAL NOT NULL,
            expires REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            replaced_by TEXT
        )""")

    def _insert(self, parent_id: str, chat_id: str, quote: dict, now: float) -> str:
        quote_json = _canonical(quote)
        while True:
            code = secrets.token_hex(5).upper()
            try:
                self.db.execute(
                    "INSERT INTO carts(code,parent_id,chat_id,quote_json,quote_hash,version,created,expires) VALUES(?,?,?,?,?,?,?,?)",
                    (code, parent_id, chat_id, quote_json, _hash(quote_json), quote["version"], now, now + EXPIRY_SECONDS),
                )
                return code
            except (sqlite3.IntegrityError, cipher.IntegrityError):
                # The code is random; retry the extremely unlikely collision.
                if not self.db.execute("SELECT 1 FROM carts WHERE code=?", (code,)).fetchone():
                    raise

    def propose(self, parent_id: str, chat_id: str, requested_items: list[str], *, now: float | None = None) -> str:
        if not parent_id or not chat_id:
            return UNAVAILABLE
        quote, error = _quote(requested_items, 1)
        if error:
            return error
        now = time.time() if now is None else now
        with self.db:
            code = self._insert(parent_id, chat_id, quote, now)
        return _render(quote, code)

    def handle(self, parent_id: str, chat_id: str, text: str, *, is_fresh_text: bool, now: float | None = None) -> str | None:
        text = text.strip()
        if not re.match(r"^(?:APPROVE|CANCEL|CHANGE)\b", text, re.I):
            return None
        if not is_fresh_text:
            return LABEL + "\nCart actions require a new, typed text command in your parent DM. Voice, forwards, quotes and documents cannot approve or change a cart."
        match = re.fullmatch(r"(APPROVE|CANCEL)[ \t]+([A-Z0-9]{10})", text, re.I)
        change = re.fullmatch(r"CHANGE[ \t]+([A-Z0-9]{10})[ \t]+([^\r\n]+)", text, re.I)
        if not match and not change:
            return USAGE
        action, code = (match[1].upper(), match[2].upper()) if match else ("CHANGE", change[1].upper())
        now = time.time() if now is None else now
        row = self.db.execute(
            "SELECT quote_json,quote_hash,version FROM carts WHERE code=? AND parent_id=? AND chat_id=? AND status='pending' AND expires>?",
            (code, parent_id, chat_id, now),
        ).fetchone()
        if not row or not hmac.compare_digest(_hash(row[0]), row[1]):
            return UNAVAILABLE
        try:
            old_quote = json.loads(row[0])
            if old_quote["version"] != row[2] or _canonical(old_quote) != row[0]:
                return UNAVAILABLE
        except (TypeError, ValueError, KeyError):
            return UNAVAILABLE
        next_quote = None
        if action == "CHANGE":
            requested = re.split(r"\s*[,;]\s*|\s+and\s+", change[2], flags=re.I)
            next_quote, error = _quote(requested, row[2] + 1)
            if error:
                return error + "\nYour previous cart remains unchanged."
        with self.db:
            # The predicate is checked again at the write, so concurrent/replayed
            # commands cannot consume the same approval more than once.
            result = self.db.execute(
                "UPDATE carts SET status=? WHERE code=? AND parent_id=? AND chat_id=? AND status='pending' AND expires>? AND quote_hash=? AND quote_json=? AND version=?",
                ({"APPROVE": "approved", "CANCEL": "cancelled", "CHANGE": "changed"}[action],
                 code, parent_id, chat_id, now, row[1], row[0], row[2]),
            )
            if result.rowcount != 1:
                return UNAVAILABLE
            if action == "CHANGE":
                new_code = self._insert(parent_id, chat_id, next_quote, now)
                self.db.execute("UPDATE carts SET replaced_by=? WHERE code=?", (new_code, code))
        if action == "CHANGE":
            return "Previous code invalidated.\n" + _render(next_quote, new_code)
        if action == "CANCEL":
            return LABEL + "\nDemo cart cancelled. Its code can no longer be used."
        return LABEL + f"\nDemo approval recorded for cart version {old_quote['version']}, total {_money(old_quote['total_paise'])}. No order was placed or payment taken."
