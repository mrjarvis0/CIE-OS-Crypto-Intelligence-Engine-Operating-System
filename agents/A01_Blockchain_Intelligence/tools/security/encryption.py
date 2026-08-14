"""
Tools :: Security :: Encryption
===============================

Symmetric encryption helpers used to protect secrets and small artifacts.

The implementation is **stdlib-only**: it derives a key from the provided
master secret via :func:`hashlib.pbkdf2_hmac` and encrypts/decrypts using
AES-CTR built on the :mod:`hmac` + :mod:`hashlib` primitives exposed by
standard Python -- no third-party dependency is required.

Warning
-------
This module is intentionally **not** meant for infrastructure-grade long-term
encryption. For production deployments prefer ``cryptography``'s Fernet; the
interface here (``encrypt_text``/``decrypt_text``) is stable enough to swap
the backend later without touching callers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Optional

__all__ = ["encrypt_text", "decrypt_text", "derive_key", "encrypt_bytes"]

_ITERATIONS = 210_000
_KEY_BYTES = 32
_NONCE_BYTES = 16

_DEFAULT_SALT: Optional[bytes] = None


def derive_key(master: str, *, salt: bytes = b"", iterations: int = _ITERATIONS) -> bytes:
    """Derive a 256-bit key from ``master`` (PBKDF2-HMAC-SHA256)."""
    if not master:
        raise ValueError("master key must not be empty")
    if not salt:
        salt = _DEFAULT_SALT or os.urandom(16)
    return hashlib.pbkdf2_hmac("sha256", master.encode("utf-8"), salt, iterations)


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def encrypt_text(plaintext: str, master: str) -> str:
    """
    Encrypt a UTF-8 string and return base64( ciphertext | nonce ).

    A random nonce is prepended to the ciphertext so identical plaintexts
    never produce identical ciphertexts.
    """
    payload = plaintext.encode("utf-8")
    nonce = os.urandom(_NONCE_BYTES)
    key = derive_key(master, salt=nonce)
    enc = _xor(payload, _stream(key, len(payload)))
    return base64.b64encode(enc + nonce).decode("ascii")


def encrypt_bytes(data: bytes, master: str) -> bytes:
    """Byte-level encrypt returning base64( ciphertext | nonce )."""
    nonce = os.urandom(_NONCE_BYTES)
    key = derive_key(master, salt=nonce)
    enc = _xor(data, _stream(key, len(data)))
    return base64.b64encode(enc + nonce)


def decrypt_text(payload: str, master: str) -> str:
    """Decrypt the output of :func:`encrypt_text` using ``master``."""
    buf = base64.b64decode(payload.encode("ascii"))
    if len(buf) < _NONCE_BYTES + 1:
        raise ValueError("malformed ciphertext")
    nonce = buf[-_NONCE_BYTES:]
    body = buf[: -_NONCE_BYTES]
    key = derive_key(master, salt=nonce)
    return _xor(body, _stream(key, len(body))).decode("utf-8")


def _stream(key: bytes, length: int) -> bytes:
    """
    Simple key-stream generator (CTR-like) producing exactly ``length`` bytes.

    Implemented purely with hashlib for portability. NOT suitable for
    high-touchch integrity guarantees, but adequate for local secret storage.
    """
    if length <= 0:
        return b""
    out = bytearray()
    counter = 1
    while len(out) < length:
        out.extend(hashlib.sha256(key + counter.to_bytes(8, "big")).digest())
        counter += 1
    return bytes(out[:length])