"""Verify a decrypted SQLite backup without modifying the production database."""

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    if not args.backup.is_file():
        print(f"[ERROR] Backup not found: {args.backup}")
        return 1
    try:
        connection = sqlite3.connect(f"file:{args.backup}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        print(f"[ERROR] SQLite backup verification failed: {type(exc).__name__}")
        return 1
    if not result or result[0] != "ok":
        print(f"[ERROR] SQLite integrity check returned: {result!r}")
        return 1
    print("[OK] SQLite backup integrity check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
