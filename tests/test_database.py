import sqlite3
from contextlib import closing

import pytest

from octo.database import connect, encrypt_existing, DatabaseError
from octo.storage import Store
from octo.cart import CartService
from octo.config import Settings
from octo.google_setup import retry_calendar_jobs

KEY = 'ab' * 32


def test_encrypted_store_restart_wal_and_wrong_key(tmp_path):
    path = tmp_path / 'secret.sqlite3'
    store = Store(path, key=KEY)
    store.reply('id', 'private-parent', 'secret school information')
    for file in tmp_path.iterdir():
        assert b'secret school information' not in file.read_bytes()
    assert not path.read_bytes().startswith(b'SQLite format 3')
    assert path.stat().st_mode & 0o777 == 0o600
    store.close()
    reopened = Store(path, key=KEY)
    assert reopened.replies()[0]['text'] == 'secret school information'
    reopened.close()
    for key in ('', 'cd' * 32):
        with pytest.raises(DatabaseError):
            connect(path, key)
    with closing(sqlite3.connect(path)) as raw:
        with pytest.raises(sqlite3.DatabaseError):
            raw.execute('SELECT * FROM outbox').fetchall()


def test_migrate_retains_all_tables_and_cart_and_is_idempotent(tmp_path):
    path = tmp_path / 'old.sqlite3'
    old = Store(path)
    old.reply('id', 'parent', 'private notice')
    CartService(old.db).propose('parent', 'chat', ['crayons'])
    old.queue_calendar('source', 'calendar', 'upsert')
    old.db.execute("UPDATE calendar_jobs SET status='failed'")
    old.db.commit()
    expected = list(old.db.execute('SELECT code,quote_json FROM carts'))
    old.close()
    before = path.read_bytes()
    with pytest.raises(DatabaseError, match='Plaintext'):
        connect(path, KEY)
    assert path.read_bytes() == before
    assert encrypt_existing(path, KEY)
    assert not encrypt_existing(path, KEY)
    migrated = Store(path, key=KEY)
    assert migrated.replies()[0]['text'] == 'private notice'
    assert [tuple(r) for r in migrated.db.execute('SELECT code,quote_json FROM carts')] == [tuple(r) for r in expected]
    assert len(CartService(migrated.db).propose('parent', 'chat', ['pencils'])) > 0
    migrated.close()
    assert not list(tmp_path.glob('*.encrypting'))


def test_bad_key_never_changes_plaintext(tmp_path):
    path=tmp_path/'old.sqlite3'; Store(path).close(); before=path.read_bytes()
    with pytest.raises(DatabaseError):
        encrypt_existing(path, 'invalid')
    assert path.read_bytes()==before


def test_live_key_required_and_hidden():
    config=Settings(mode='live', sarvam_api_key='x', waha_api_key='x', webhook_secret='x')
    with pytest.raises(ValueError, match='OCTO_DB_KEY'): config.check_live()
    config.db_key=KEY; config.check_live()
    assert KEY not in repr(config)


def test_google_retry_on_encrypted_database(tmp_path):
    path=tmp_path/'live'/'octo.sqlite3';store=Store(path,key=KEY)
    store.queue_calendar('source','calendar','upsert')
    store.db.execute("UPDATE calendar_jobs SET status='failed'");store.db.commit()
    assert retry_calendar_jobs(tmp_path,'calendar',KEY)==1
    assert store.db.execute('SELECT status FROM calendar_jobs').fetchone()[0]=='pending'
    store.close()


def test_failed_export_verification_retains_original(tmp_path, monkeypatch):
    from octo import database
    path = tmp_path / 'old.sqlite3'
    store = Store(path)
    store.reply('id', 'parent', 'must survive a failed migration')
    store.close()
    def reject(*args, **kwargs):
        raise DatabaseError('Simulated verification failure')
    monkeypatch.setattr(database, 'connect', reject)
    with pytest.raises(DatabaseError, match='original database retained'):
        encrypt_existing(path, KEY)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT text FROM outbox').fetchone()[0] == 'must survive a failed migration'
    assert not path.with_name(path.name + '.encrypting').exists()
