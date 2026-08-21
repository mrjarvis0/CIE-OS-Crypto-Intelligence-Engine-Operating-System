"""
Tools :: Security :: Encryption
===============================

Symmetric encryption helpers used to protect secrets and small artifacts.

The implementation is **stdlib-only**: keys are derived from the provided
master secret with :func:`hashlib.pbkdf2_hmac`, the payload is masked with an
HMAC-SHA256 keystream, and the result is authenticated with HMAC-SHA256 under
a separate key -- encrypt-then-MAC.

Why the MAC is not optional
---------------------------
The previous version XOR'd a keystream over the plaintext and stopped there.
A stream cipher without a tag is *malleable*: an attacker who can reach the
stored ciphertext flips a bit of ciphertext and flips exactly that bit of
plaintext, without knowing the key and without producing any error on
decryption. A stored ``admin=0`` became ``admin=9`` with a one-byte edit, and
:func:`decrypt_text` returned it as though nothing had happened.

So the tag is computed over the version byte, the salt and the ciphertext,
and :func:`decrypt_text` verifies it with :func:`hmac.compare_digest` before
a single byte of plaintext is produced. Tampering now raises
:class:`IntegrityError`.

Warning
-------
This is still not a replacement for a reviewed AEAD. For production
deployments prefer ``cryptography``'s Fernet or AES-GCM; the interface here
(``encrypt_text``/``decrypt_text``) is stable enough to swap the backend
later without touching callers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Tuple

__all__ = [
    "IntegrityError",
    "encrypt_text",
    "decrypt_text",
    "derive_key",
    "derive_keys",
    "encrypt_bytes",
    "decrypt_bytes",
]

_ITERATIONS = 210_000
_KEY_BYTES = 32
_MAC_BYTES = 32
_SALT_BYTES = 16
_TAG_BYTES = 32

#: Leading byte of every payload. A format change increments it, so a reader
#: rejects an old ciphertext with a clear error instead of returning noise.
_VERSION = b"\x01"


class IntegrityError(ValueError):
    """Raised when a ciphertext fails authentication or is malformed."""


def derive_keys(
    master: str, *, salt: bytes, iterations: int = _ITERATIONS
) -> Tuple[bytes, bytes]:
    """
    Derive the (encryption, MAC) key pair from ``master`` and ``salt``.

    Two independent keys come from one PBKDF2 call of double width rather than
    from two calls, which halves the work and guarantees the keys differ.
    Reusing one key for both masking and authentication is the classic way to
    make a MAC prove less than it appears to.
    """
    if not master:
        raise ValueError("master key must not be empty")
    if not salt:
        raise ValueError("salt must not be empty")

    material = hashlib.pbkdf2_hmac(
        "sha256",
        master.encode("utf-8"),
        salt,
        iterations,
        dklen=_KEY_BYTES + _MAC_BYTES,
    )
    return material[:_KEY_BYTES], material[_KEY_BYTES:]


def derive_key(master: str, *, salt: bytes, iterations: int = _ITERATIONS) -> bytes:
    """
    Derive a 256-bit encryption key from ``master`` (PBKDF2-HMAC-SHA256).

    ``salt`` is required. It used to default to ``os.urandom(16)`` when
    omitted, and the salt was then discarded -- so two calls with the same
    master returned two different keys, and anything encrypted under the first
    could not be decrypted under the second. A KDF that silently returns a
    different answer each time is worse than one that refuses.
    """
    return derive_keys(master, salt=salt, iterations=iterations)[0]


def _keystream(key: bytes, length: int) -> bytes:
    """
    Keystream of exactly ``length`` bytes, as HMAC-SHA256(key, counter) blocks.

    HMAC rather than a bare ``sha256(key + counter)``: the bare form is a
    prefix-keyed hash, the construction length-extension applies to. Nothing
    here extends it today, but the keyed primitive costs the same and removes
    the question.
    """
    if length <= 0:
        return b""

    out = bytearray()
    counter = 1
    while len(out) < length:
        out.extend(hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(data, stream))


def _seal(payload: bytes, master: str) -> bytes:
    """Return VERSION || salt || ciphertext || tag."""
    salt = os.urandom(_SALT_BYTES)
    enc_key, mac_key = derive_keys(master, salt=salt)
    ciphertext = _xor(payload, _keystream(enc_key, len(payload)))
    body = _VERSION + salt + ciphertext
    tag = hmac.new(mac_key, body, hashlib.sha256).digest()
    return body + tag


def _open(buf: bytes, master: str) -> bytes:
    """Verify and decrypt the output of :func:`_seal`."""
    if len(buf) < len(_VERSION) + _SALT_BYTES + _TAG_BYTES:
        raise IntegrityError("malformed ciphertext: too short")

    version = buf[: len(_VERSION)]
    if version != _VERSION:
        raise IntegrityError(f"unsupported ciphertext version: {version!r}")

    body, tag = buf[:-_TAG_BYTES], buf[-_TAG_BYTES:]
    salt = body[len(_VERSION) : len(_VERSION) + _SALT_BYTES]
    ciphertext = body[len(_VERSION) + _SALT_BYTES :]

    enc_key, mac_key = derive_keys(master, salt=salt)
    expected = hmac.new(mac_key, body, hashlib.sha256).digest()

    # Verified before any plaintext is produced, and compared in constant time
    # so a wrong tag leaks nothing about the right one.
    if not hmac.compare_digest(expected, tag):
        raise IntegrityError("ciphertext failed authentication (wrong key or tampered)")

    return _xor(ciphertext, _keystream(enc_key, len(ciphertext)))


def encrypt_text(plaintext: str, master: str) -> str:
    """
    Encrypt a UTF-8 string; returns base64(VERSION | salt | ciphertext | tag).

    A fresh random salt per message means identical plaintexts never produce
    identical ciphertexts.
    """
    return base64.b64encode(_seal(plaintext.encode("utf-8"), master)).decode("ascii")


def decrypt_text(payload: str, master: str) -> str:
    """
    Decrypt the output of :func:`encrypt_text`.

    Raises :class:`IntegrityError` when the payload was modified, truncated,
    or was produced under a different master key.
    """
    try:
        buf = base64.b64decode(payload.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise IntegrityError("malformed ciphertext: not valid base64") from exc

    return _open(buf, master).decode("utf-8")


def encrypt_bytes(data: bytes, master: str) -> bytes:
    """Byte-level encrypt; returns base64(VERSION | salt | ciphertext | tag)."""
    return base64.b64encode(_seal(data, master))


def decrypt_bytes(payload: bytes, master: str) -> bytes:
    """Decrypt the output of :func:`encrypt_bytes`."""
    try:
        buf = base64.b64decode(payload, validate=True)
    except ValueError as exc:
        raise IntegrityError("malformed ciphertext: not valid base64") from exc

    return _open(buf, master)
