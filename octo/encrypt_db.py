"""Encrypt an existing database while Octo is stopped; key comes from .env."""
import argparse
from pathlib import Path
from .config import Settings
from .database import DatabaseError, encrypt_existing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path', type=Path, help='Defaults to the configured live database')
    parser.add_argument('--worker-stopped', action='store_true', required=True,
                        help='Confirm all processes using this database have been stopped')
    args = parser.parse_args()
    settings = Settings.from_env()
    try:
        changed = encrypt_existing(args.path or settings.data_dir / 'live' / 'octo.sqlite3', settings.db_key)
    except DatabaseError as error:
        parser.exit(1, str(error) + '\n')
    print('Database encrypted and verified.' if changed else 'Database is already encrypted; key verified.')


if __name__ == '__main__':
    main()
