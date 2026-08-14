"""
Tools :: Plugins :: Signer
==========================

Plugin signature handling: signing manifests/packages and verifying
publisher identity before installation.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from ..governance.signing import SigningKey, sign_payload, verify_payload

__all__ = ["PluginSigner"]


class PluginSigner:
    """Signs and verifies plugin manifests."""

    def __init__(self, *, key: Optional[SigningKey] = None) -> None:
        self.key = key
        self._trusted: Dict[str, SigningKey] = {}

    def set_signing_key(self, key: SigningKey) -> None:
        self.key = key

    def trust_publisher(self, publisher: str, key: SigningKey) -> None:
        self._trusted[publisher] = key

    def sign(self, manifest: Mapping[str, Any]) -> str:
        if self.key is None:
            raise ValueError("no signing key configured")
        return sign_payload(self.key, dict(manifest))

    def verify(self, manifest: Mapping[str, Any], signature: str, publisher: str = "") -> bool:
        key = self.key
        if publisher:
            key = self._trusted.get(publisher)
        if key is None:
            return False
        return verify_payload(key, dict(manifest), signature)