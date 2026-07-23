"""Streaming AES-256-GCM encryption for database backup files."""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"SABK1"
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024


def _decode_key(encoded: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(encoded.encode())
    except Exception as exc:
        raise ValueError("invalid backup encryption key") from exc
    if len(key) != 32:
        raise ValueError("backup encryption key must decode to 32 bytes")
    return key


def encrypt_backup_file(path: Path, encoded_key: str) -> Path:
    key = _decode_key(encoded_key)
    nonce = os.urandom(NONCE_SIZE)
    output = path.with_suffix(path.suffix + ".enc")
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    with path.open("rb") as source, output.open("wb") as target:
        target.write(MAGIC + nonce)
        while chunk := source.read(CHUNK_SIZE):
            target.write(encryptor.update(chunk))
        target.write(encryptor.finalize())
        target.write(encryptor.tag)
    os.chmod(output, 0o600)
    path.unlink()
    return output


def decrypt_backup_file(path: Path, destination: Path, encoded_key: str) -> Path:
    key = _decode_key(encoded_key)
    size = path.stat().st_size
    if size < len(MAGIC) + NONCE_SIZE + TAG_SIZE:
        raise ValueError("invalid encrypted backup")
    with path.open("rb") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise ValueError("invalid encrypted backup magic")
        nonce = source.read(NONCE_SIZE)
        source.seek(-TAG_SIZE, 2)
        tag = source.read(TAG_SIZE)
        ciphertext_end = size - TAG_SIZE
        source.seek(len(MAGIC) + NONCE_SIZE)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        with destination.open("wb") as target:
            while source.tell() < ciphertext_end:
                remaining = ciphertext_end - source.tell()
                target.write(decryptor.update(source.read(min(CHUNK_SIZE, remaining))))
            target.write(decryptor.finalize())
    os.chmod(destination, 0o600)
    return destination
