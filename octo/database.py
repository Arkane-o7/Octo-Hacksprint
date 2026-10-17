"""SQLCipher connections and explicit, offline plaintext migration."""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlcipher3 import dbapi2 as cipher


class DatabaseError(RuntimeError):
    """Safe operator error; never includes keys or SQL."""


def validate_key(key: str) -> None:
    if not re.fullmatch(r'[0-9a-fA-F]{64}', key):
        raise DatabaseError('OCTO_DB_KEY must be 64 hexadecimal characters (32 random bytes).')


def connect(path: Path, key: str = ''):
    path = Path(path)
    if key:
        validate_key(key)
        if path.exists() and path.stat().st_size:
            with path.open('rb') as source:
                if source.read(16) == b'SQLite format 3\x00':
                    raise DatabaseError('Plaintext database detected. Stop Octo and run python -m octo.encrypt_db first.')
        driver = cipher
    else:
        driver = sqlite3
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create private files before SQLite opens them (also controls WAL permissions).
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    path.chmod(0o600)
    db = driver.connect(path, check_same_thread=False)
    try:
        if key:
            if not db.execute('PRAGMA cipher_version').fetchone():
                raise DatabaseError('SQLCipher is unavailable; refusing an unencrypted fallback.')
            # Key is validated hex, never interpolated arbitrary SQL or logged.
            db.execute(f'''PRAGMA key = "x'{key}'"''')
            db.execute('PRAGMA temp_store=MEMORY')
        db.execute('SELECT count(*) FROM sqlite_master').fetchone()
        db.row_factory = driver.Row
        return db
    except Exception:
        db.close()
        raise DatabaseError('Database could not be opened. Check the encryption key and database integrity.') from None


def encrypt_existing(path: Path, key: str) -> bool:
    """Worker MUST be stopped. Verified export replaces plaintext atomically.

    Failures before replacement leave the original untouched. No plaintext backup
    is made. Preserve the key separately before running this operation.
    """
    validate_key(key)
    path = Path(path)
    if not path.is_file():
        raise DatabaseError('Database does not exist.')
    with path.open('rb') as source:
        plaintext = source.read(16) == b'SQLite format 3\x00'
    if not plaintext:
        with closing(connect(path, key)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise DatabaseError('Database integrity check failed.')
        return False
    temporary = path.with_name(path.name + '.encrypting')
    if temporary.exists():
        raise DatabaseError('A previous encrypted staging file exists; inspect it before retrying.')
    db = cipher.connect(path, timeout=1)
    try:
        # Refuse migration while another process holds a reader/writer lock.
        if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
            raise DatabaseError('Stop all database users before migration.')
        db.execute('PRAGMA locking_mode=EXCLUSIVE')
        db.execute('BEGIN EXCLUSIVE')
        db.execute('COMMIT')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        def counts(conn):
            return {t: conn.execute('SELECT count(*) FROM "' + t.replace('"', '""') + '"').fetchone()[0] for t in tables}
        before = counts(db)
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        db.execute('ATTACH DATABASE ? AS encrypted KEY ?', (str(temporary), "x'" + key + "'"))
        db.execute("SELECT sqlcipher_export('encrypted')")
        db.execute(f'PRAGMA encrypted.user_version={version}')
        db.execute('DETACH DATABASE encrypted')
        with closing(connect(temporary, key)) as verified:
            if verified.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or counts(verified) != before:
                raise DatabaseError('Encrypted export validation failed.')
        with temporary.open('rb') as source:
            os.fsync(source.fileno())
        db.close()
        os.replace(temporary, path)
        path.chmod(0o600)
        return True
    except Exception:
        db.close()
        temporary.unlink(missing_ok=True)
        raise DatabaseError('Encryption migration failed; original database retained. Stop database users and check the key.') from None
