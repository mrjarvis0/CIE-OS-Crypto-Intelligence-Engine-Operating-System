"""
Tools :: Governance :: Signing
==============================

Integrity protection: manifest/tool/package signatures, certificate
validation and integrity verification.

Signing is local and deterministic (HMAC-SHA256); it never substitutes
for a hardware signing backend.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Mapping, Optional

__all__ = ["SigningKey", "sign_bytes", "verify_bytes", "sign_payload", "verify_payload", "integrity_digest"]


def integrity_digest(payload: bytes) -> str:
    """Stable content digest for integrity checks."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def sign_bytes(key: "SigningKey", payload: bytes) -> str:
    """HMAC-SHA256 signature over bytes, hex-encoded."""
    return hmac.new(key.secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_bytes(key: "SigningKey", payload: bytes, signature: str) -> bool:
    """Constant-time signature comparison."""
    expected = sign_bytes(key, payload)
    return hmac.compare_digest(expected, signature or "")


def sign_payload(key: "SigningKey", payload: Mapping[str, Any]) -> str:
    """Signature over the canonical JSON of a payload dict."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sign_bytes(key, canonical)


def verify_payload(key: "SigningKey", payload: Mapping[str, Any], signature: str) -> bool:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return verify_bytes(key, canonical, signature)


class SigningKey:
    """Named HMAC signing identity (local, deterministic)."""

    def __init__(self, name: str, secret: str) -> None:
        self.name = name
        self.secret = secret
        self.public_id = "hmac-sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]

    def sign(self, payload: bytes) -> str:
        return sign_bytes(self, payload)

    def verify(self, payload: bytes, signature: str) -> bool:
        return verify_bytes(self, payload, signature)

    def sign_payload(self, payload: Mapping[str, Any]) -> str:
        return sign_payload(self, payload)

    def verify_payload(self, payload: Mapping[str, Any], signature: str) -> bool:
        return verify_payload(self, payload, signature)

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "public_id": self.public_id}