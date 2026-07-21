"""Decrypt an AES-GCM encrypted DB backup."""

import argparse
from pathlib import Path

from config import settings
from utils.backup_crypto import decrypt_backup_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if not settings.backup_encryption_key:
        raise SystemExit("BACKUP_ENCRYPTION_KEY is not configured")
    decrypt_backup_file(args.source, args.destination, settings.backup_encryption_key)
    print(f"Decrypted backup: {args.destination}")


if __name__ == "__main__":
    main()
