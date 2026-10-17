# Database encryption

Live Octo uses SQLCipher 4 through the pinned `sqlcipher3-wheels` driver. The
whole SQLite database, including school facts, inbox, outbox, carts and database
journals, is encrypted at rest. There is no plaintext fallback in live startup.
Offline replay and isolated fixtures use ordinary SQLite.

## Setup or migration

1. Install the locked dependencies with `uv sync`.
2. Stop every worker or script using the database before migration.
3. Generate a random key locally and add it to your ignored `.env`:

   ```bash
   uv run python -c 'import secrets; print(secrets.token_hex(32))'
   ```

   Set `OCTO_DB_KEY` to that value. Keep `.env` readable only by your user
   (`chmod 600 .env`). Store a separate copy of the key in a password manager.
   Never put the key in chat, source code, logs or a command argument.
4. For an existing plaintext database run:

   ```bash
   uv run python -m octo.encrypt_db --worker-stopped
   ```

   For another database snapshot, add `--path path/to/snapshot.sqlite3`.
   A new empty live database is encrypted automatically on startup.
5. Start the usual worker. Missing or invalid keys prevent live startup.

Migration exports schema and records to an encrypted staging file, checks
integrity and table row counts, then replaces the original file. It refuses
an active SQLite lock and never creates a plaintext backup. A failed export
leaves the source intact. Already-encrypted files are verified without being
converted again. All database users must stay stopped for the whole operation;
the CLI flag is an operator acknowledgement, not a process manager.

SQLCipher's export mechanism is documented by
[Zetetic](https://www.zetetic.net/sqlcipher/sqlcipher-api/#sqlcipher_export).

## Recovery and scope

- Keep the encryption key with a secure, separate backup. Losing it loses access
  to the data. Changing the environment variable does not rotate the database key.
- Back up encrypted databases while the worker is stopped, or use a SQLCipher-aware
  backup tool. Copying only the main file while WAL writes are active can lose data.
- Do not use Python's ordinary `sqlite3` to inspect an encrypted file. Internal
  utilities use `octo.database.connect(path, key)`; Google retry uses this too.
- Old database copies must be migrated separately. Removing plaintext files does
  not guarantee erasure from SSD history, filesystem snapshots or remote backups.
- Media downloads, transcripts in diagnostic reports, logs, OAuth files, WhatsApp
  session files and the key itself are outside this database encryption boundary.
  Keep them private; use full-disk encryption for wider device protection.
- A process or user able to read both `.env` and the database can decrypt it. This
  is protection against disclosure of the database alone, not a compromised host.

Validation covers encrypted WAL bytes, restart persistence, wrong/missing keys,
plaintext refusal, migration preservation, encrypted carts and Calendar retries.
