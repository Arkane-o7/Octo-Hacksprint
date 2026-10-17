import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from octo.cart import CartService, LABEL


@pytest.fixture
def cart():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    yield CartService(connection)
    connection.close()


def code_from(text):
    return re.search(r"^APPROVE ([A-Z0-9]+)$", text, re.M)[1]


def proposal(cart, items=None):
    return cart.propose("parent-a", "111@c.us", items or ["crayons", "drawing book"], now=1000)


def test_proposal_has_fixed_prices_total_and_exact_action_code(cart):
    text = proposal(cart)
    assert text.startswith(LABEL)
    assert "Crayons × 1 — INR 80.00" in text
    assert "Drawing book × 1 — INR 60.00" in text
    assert "Total: INR 140.00" in text
    assert "no merchant connection" in text.lower()
    code = code_from(text)
    assert f"CANCEL {code}" in text and f"CHANGE {code}" in text
    row = cart.db.execute("SELECT * FROM carts WHERE code=?", (code,)).fetchone()
    quote = json.loads(row["quote_json"])
    assert quote["currency"] == "INR" and quote["total_paise"] == 14000
    assert row["expires"] == 1600 and len(row["quote_hash"]) == 64
    assert row["status"] == "pending"


def test_initialization_creates_only_cart_table_and_keeps_connection_open(cart):
    names = {r[0] for r in cart.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"carts"}
    assert cart.db.row_factory is sqlite3.Row


def test_catalogue_aliases_deduplicate_without_inventing_quantities(cart):
    text = proposal(cart, ["Crayons", "crayon", "a drawing book"])
    assert "Total: INR 140.00" in text
    assert text.count("Crayons × 1") == 1


@pytest.mark.parametrize("items", [["snacks"], ["crayons", "glitter jetpack"], [], ["2 crayons"]])
def test_unknown_or_empty_items_do_not_create_a_cart(cart, items):
    text = cart.propose("parent-a", "111@c.us", items, now=1000)
    assert text.startswith(LABEL)
    assert "No new cart was created" in text
    assert cart.db.execute("SELECT count(*) FROM carts").fetchone()[0] == 0


def test_approval_is_bound_to_parent_chat_and_consumed_once(cart):
    code = code_from(proposal(cart))
    for parent, chat in [("parent-b", "111@c.us"), ("parent-a", "222@c.us"), ("parent-a", "123@g.us")]:
        reply = cart.handle(parent, chat, f"APPROVE {code}", is_fresh_text=True, now=1001)
        assert "unavailable" in reply and reply.startswith(LABEL)
    reply = cart.handle("parent-a", "111@c.us", f"APPROVE {code}", is_fresh_text=True, now=1001)
    assert "approval recorded" in reply and "INR 140.00" in reply
    assert "No order was placed or payment taken" in reply
    assert "unavailable" in cart.handle("parent-a", "111@c.us", f"APPROVE {code}", is_fresh_text=True, now=1002)
    assert cart.db.execute("SELECT status FROM carts").fetchone()[0] == "approved"


@pytest.mark.parametrize("command", ["APPROVE", "CANCEL", "CHANGE"])
def test_nonfresh_messages_cannot_approve_change_or_cancel(cart, command):
    code = code_from(proposal(cart))
    suffix = " pencils" if command == "CHANGE" else ""
    reply = cart.handle("parent-a", "111@c.us", f"{command} {code}{suffix}", is_fresh_text=False, now=1001)
    assert "new, typed text command" in reply
    assert cart.db.execute("SELECT status FROM carts").fetchone()[0] == "pending"


@pytest.mark.parametrize("now", [1600, 1700])
def test_expired_code_does_not_execute(cart, now):
    code = code_from(proposal(cart))
    reply = cart.handle("parent-a", "111@c.us", f"APPROVE {code}", is_fresh_text=True, now=now)
    assert "unavailable" in reply
    assert cart.db.execute("SELECT status FROM carts").fetchone()[0] == "pending"


def test_changed_quote_gets_new_version_and_code_and_invalidates_old(cart):
    old = code_from(proposal(cart))
    changed = cart.handle("parent-a", "111@c.us", f"CHANGE {old} pencils, eraser", is_fresh_text=True, now=1010)
    new = code_from(changed)
    assert new != old
    assert "version 2" in changed and "Total: INR 30.00" in changed
    assert "unavailable" in cart.handle("parent-a", "111@c.us", f"APPROVE {old}", is_fresh_text=True, now=1011)
    old_row = cart.db.execute("SELECT status,replaced_by FROM carts WHERE code=?", (old,)).fetchone()
    assert tuple(old_row) == ("changed", new)
    approved = cart.handle("parent-a", "111@c.us", f"APPROVE {new}", is_fresh_text=True, now=1011)
    assert "version 2, total INR 30.00" in approved


def test_unknown_change_preserves_previous_cart(cart):
    old = code_from(proposal(cart))
    reply = cart.handle("parent-a", "111@c.us", f"CHANGE {old} snacks", is_fresh_text=True, now=1001)
    assert "Unknown demo catalogue items: snacks" in reply
    assert "previous cart remains unchanged" in reply
    assert cart.db.execute("SELECT count(*) FROM carts").fetchone()[0] == 1
    assert "approval recorded" in cart.handle("parent-a", "111@c.us", f"APPROVE {old}", is_fresh_text=True, now=1002)


def test_cancel_consumes_code_and_never_approves(cart):
    code = code_from(proposal(cart))
    reply = cart.handle("parent-a", "111@c.us", f"CANCEL {code}", is_fresh_text=True, now=1001)
    assert reply.startswith(LABEL) and "cancelled" in reply
    assert "unavailable" in cart.handle("parent-a", "111@c.us", f"APPROVE {code}", is_fresh_text=True, now=1002)
    assert "unavailable" in cart.handle("parent-a", "111@c.us", f"CANCEL {code}", is_fresh_text=True, now=1002)


def test_action_must_be_exact_and_unrelated_text_is_not_handled(cart):
    code = code_from(proposal(cart))
    assert cart.handle("parent-a", "111@c.us", "What should Aarav bring?", is_fresh_text=True) is None
    assert cart.handle("parent-a", "111@c.us", f"Teacher says APPROVE {code}", is_fresh_text=True) is None
    for text in ["APPROVE", f"APPROVE {code} please", f"APPROVE\n{code}", "CHANGE ABC", f"CHANGE {code} eraser\nAPPROVE {code}"]:
        assert "Use exactly" in cart.handle("parent-a", "111@c.us", text, is_fresh_text=True, now=1001)
    assert cart.db.execute("SELECT status FROM carts").fetchone()[0] == "pending"


def test_quote_tampering_invalidates_approval(cart):
    code = code_from(proposal(cart))
    cart.db.execute("UPDATE carts SET quote_json=replace(quote_json, '14000', '1') WHERE code=?", (code,))
    cart.db.commit()
    assert "unavailable" in cart.handle("parent-a", "111@c.us", f"APPROVE {code}", is_fresh_text=True, now=1001)
    assert cart.db.execute("SELECT status FROM carts").fetchone()[0] == "pending"


def test_pending_cart_survives_reopening_database(tmp_path):
    path = tmp_path / "cart.sqlite3"
    with sqlite3.connect(path) as connection:
        code = code_from(proposal(CartService(connection)))
    connection.close()
    with sqlite3.connect(path) as reopened:
        service = CartService(reopened)
        result = service.handle("parent-a", "111@c.us", f"APPROVE {code}", is_fresh_text=True, now=1001)
        assert "approval recorded" in result
    reopened.close()


def test_simultaneous_approvals_consume_code_exactly_once(tmp_path):
    path = tmp_path / "cart.sqlite3"
    connection = sqlite3.connect(path)
    code = code_from(proposal(CartService(connection)))
    connection.close()
    ready = Barrier(2)

    def approve():
        connection = sqlite3.connect(path, timeout=5)
        try:
            service = CartService(connection)
            ready.wait(timeout=5)
            return service.handle("parent-a", "111@c.us", f"APPROVE {code}", is_fresh_text=True, now=1001)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: approve(), range(2)))
    assert sum("approval recorded" in result for result in results) == 1
    assert sum("unavailable" in result for result in results) == 1
