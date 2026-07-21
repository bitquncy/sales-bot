"""Encrypted backup roundtrip and authentication."""

import pytest
from cryptography.fernet import Fernet

from utils.backup_crypto import decrypt_backup_file, encrypt_backup_file


def test_backup_crypto_roundtrip(tmp_path):
    source = tmp_path / "db.sql"
    source.write_bytes(b"database backup" * 1000)
    key = Fernet.generate_key().decode()
    encrypted = encrypt_backup_file(source, key)
    assert not source.exists()
    restored = decrypt_backup_file(encrypted, tmp_path / "restored.sql", key)
    assert restored.read_bytes() == b"database backup" * 1000


def test_backup_crypto_detects_tampering(tmp_path):
    source = tmp_path / "db.sql"
    source.write_bytes(b"secret")
    key = Fernet.generate_key().decode()
    encrypted = encrypt_backup_file(source, key)
    data = bytearray(encrypted.read_bytes())
    data[-20] ^= 1
    encrypted.write_bytes(data)
    with pytest.raises(Exception):
        decrypt_backup_file(encrypted, tmp_path / "bad.sql", key)
