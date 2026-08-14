"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.providers.keys

Purpose:
    Resolve provider API keys from the environment and report, without ever
    exposing a key, which providers are currently reachable.

Design goals:
    - No secrets in memory beyond a SecretValue wrapper
    - No network I/O
    - Absent key is a normal state, never an error
    - Safe to import anywhere

Notes:
    A01 is built to run on free provider tiers. Most of the catalog therefore
    needs no key at all, and the keyed entries are expected to sit dormant
    until an operator supplies one. Resolution is re-read on every call rather
    than cached at import, so dropping a key into the environment activates a
    provider without a restart or a code change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Mapping

from config.security.secrets import SecretValue


# ==============================================================================
# ENUMS
# ==============================================================================

class KeyState(StrEnum):
    """Whether a provider's credential is usable."""

    PRESENT = "present"
    ABSENT = "absent"
    BLANK = "blank"


# ==============================================================================
# MODELS
# ==============================================================================

@dataclass(frozen=True, slots=True)
class ApiKeySpec:
    """
    Declares where a provider's key comes from, without holding the key.

    ``env_vars`` is ordered: the first variable that carries a non-blank value
    wins. Several providers have been renamed over time and still ship two
    accepted variable names, so a single spec has to be able to accept both.
    """

    provider: str
    env_vars: tuple[str, ...]
    signup_url: str = ""
    free_tier: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider cannot be empty")
        if not self.env_vars:
            raise ValueError(f"{self.provider}: at least one env var is required")
        if any(not var.strip() for var in self.env_vars):
            raise ValueError(f"{self.provider}: env var names cannot be blank")

    @property
    def primary_env_var(self) -> str:
        """The variable to name in operator-facing guidance."""
        return self.env_vars[0]


@dataclass(frozen=True, slots=True)
class KeyResolution:
    """
    Outcome of looking up one key spec.

    Carries the resolved ``SecretValue`` when present. ``as_dict`` deliberately
    omits it: this object flows into ``doctor`` output and health snapshots,
    which are printed and logged.
    """

    spec: ApiKeySpec
    state: KeyState
    secret: SecretValue | None = None
    env_var: str | None = None

    @property
    def is_usable(self) -> bool:
        return self.state == KeyState.PRESENT and self.secret is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.spec.provider,
            "state": self.state.value,
            "env_var": self.env_var or self.spec.primary_env_var,
            "free_tier": self.spec.free_tier,
            "signup_url": self.spec.signup_url,
        }


# ==============================================================================
# RESOLUTION
# ==============================================================================

def resolve_key(
    spec: ApiKeySpec,
    environ: Mapping[str, str] | None = None,
) -> KeyResolution:
    """
    Look up ``spec`` in the environment.

    A variable that exists but holds only whitespace resolves to ``BLANK``
    rather than ``PRESENT``. An empty ``PROVIDER_API_KEY=`` line in a .env file
    is the single most common way a provider appears configured and then fails
    on first request, and the distinction lets ``doctor`` say so plainly.
    """
    source = environ if environ is not None else os.environ

    for var in spec.env_vars:
        if var not in source:
            continue

        raw = source[var]
        if not raw.strip():
            return KeyResolution(spec=spec, state=KeyState.BLANK, env_var=var)

        return KeyResolution(
            spec=spec,
            state=KeyState.PRESENT,
            secret=SecretValue(name=var, _value=raw.strip(), source="environment"),
            env_var=var,
        )

    return KeyResolution(spec=spec, state=KeyState.ABSENT)


def has_key(spec: ApiKeySpec, environ: Mapping[str, str] | None = None) -> bool:
    """True when ``spec`` resolves to a usable credential."""
    return resolve_key(spec, environ).is_usable


def resolve_all(
    specs: tuple[ApiKeySpec, ...],
    environ: Mapping[str, str] | None = None,
) -> tuple[KeyResolution, ...]:
    """Resolve every spec, preserving order."""
    return tuple(resolve_key(spec, environ) for spec in specs)


# ==============================================================================
# KEY SPECS
# ==============================================================================
#
# Every keyed provider A01 knows about. Entries are inert until the matching
# variable is set; none of them is required for A01 to run.

# --- Multi-chain RPC providers ------------------------------------------

ALCHEMY: Final = ApiKeySpec(
    provider="alchemy",
    env_vars=("ALCHEMY_API_KEY",),
    signup_url="https://www.alchemy.com/",
    notes="Free tier includes archive access, which public endpoints rarely do.",
)

INFURA: Final = ApiKeySpec(
    provider="infura",
    env_vars=("INFURA_API_KEY", "INFURA_PROJECT_ID"),
    signup_url="https://www.infura.io/",
    notes="Archive data requires a paid plan; the free tier is latest-state only.",
)

QUICKNODE: Final = ApiKeySpec(
    provider="quicknode",
    env_vars=("QUICKNODE_URL",),
    signup_url="https://www.quicknode.com/",
    notes="Issues a full per-endpoint URL rather than a bare key, so the whole URL is the secret.",
)

ANKR: Final = ApiKeySpec(
    provider="ankr",
    env_vars=("ANKR_API_KEY",),
    signup_url="https://www.ankr.com/rpc/",
    notes="Public Ankr endpoints work without a key; a key raises the rate limit.",
)

DRPC: Final = ApiKeySpec(
    provider="drpc",
    env_vars=("DRPC_API_KEY",),
    signup_url="https://drpc.org/",
)

BLOCKPI: Final = ApiKeySpec(
    provider="blockpi",
    env_vars=("BLOCKPI_API_KEY",),
    signup_url="https://blockpi.io/",
)

CHAINSTACK: Final = ApiKeySpec(
    provider="chainstack",
    env_vars=("CHAINSTACK_URL",),
    signup_url="https://chainstack.com/",
    notes="Per-node URL, like QuickNode.",
)

GETBLOCK: Final = ApiKeySpec(
    provider="getblock",
    env_vars=("GETBLOCK_API_KEY",),
    signup_url="https://getblock.io/",
)

NOWNODES: Final = ApiKeySpec(
    provider="nownodes",
    env_vars=("NOWNODES_API_KEY",),
    signup_url="https://nownodes.io/",
    notes="One of the few free providers covering Bitcoin JSON-RPC as well as EVM.",
)

# --- Explorer / indexer providers ---------------------------------------

ETHERSCAN: Final = ApiKeySpec(
    provider="etherscan",
    env_vars=("ETHERSCAN_API_KEY",),
    signup_url="https://etherscan.io/apis",
    notes=(
        "Etherscan V2 accepts one key across every supported EVM chain via the "
        "chainid parameter, so this single key covers BSC, Polygon, Arbitrum, "
        "Optimism, Base and Avalanche too."
    ),
)

MORALIS: Final = ApiKeySpec(
    provider="moralis",
    env_vars=("MORALIS_API_KEY",),
    signup_url="https://moralis.io/",
)

COVALENT: Final = ApiKeySpec(
    provider="covalent",
    env_vars=("COVALENT_API_KEY", "GOLDRUSH_API_KEY"),
    signup_url="https://goldrush.dev/",
    notes="Rebranded to GoldRush; both variable names are accepted.",
)

HELIUS: Final = ApiKeySpec(
    provider="helius",
    env_vars=("HELIUS_API_KEY",),
    signup_url="https://www.helius.dev/",
    notes="Solana-specific; substantially better than the public Solana endpoint.",
)

BLOCKCYPHER: Final = ApiKeySpec(
    provider="blockcypher",
    env_vars=("BLOCKCYPHER_TOKEN",),
    signup_url="https://www.blockcypher.com/",
    notes="Bitcoin REST; works without a token at a much lower rate limit.",
)

# --- Market data --------------------------------------------------------

COINGECKO: Final = ApiKeySpec(
    provider="coingecko",
    env_vars=("COINGECKO_API_KEY", "COINGECKO_DEMO_API_KEY"),
    signup_url="https://www.coingecko.com/en/api",
    notes="Public endpoint needs no key; a demo key roughly triples the rate limit.",
)

CRYPTOCOMPARE: Final = ApiKeySpec(
    provider="cryptocompare",
    env_vars=("CRYPTOCOMPARE_API_KEY",),
    signup_url="https://www.cryptocompare.com/cryptopian/api-keys",
)


ALL_KEY_SPECS: Final[tuple[ApiKeySpec, ...]] = (
    ALCHEMY,
    INFURA,
    QUICKNODE,
    ANKR,
    DRPC,
    BLOCKPI,
    CHAINSTACK,
    GETBLOCK,
    NOWNODES,
    ETHERSCAN,
    MORALIS,
    COVALENT,
    HELIUS,
    BLOCKCYPHER,
    COINGECKO,
    CRYPTOCOMPARE,
)

_SPECS_BY_PROVIDER: Final[dict[str, ApiKeySpec]] = {
    spec.provider: spec for spec in ALL_KEY_SPECS
}


def get_key_spec(provider: str) -> ApiKeySpec:
    """Look up a spec by provider name."""
    try:
        return _SPECS_BY_PROVIDER[provider.strip().lower()]
    except KeyError as exc:
        raise KeyError(f"Unknown key provider: {provider!r}") from exc


def configured_providers(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Names of every provider with a usable key, for doctor output."""
    return tuple(
        resolution.spec.provider
        for resolution in resolve_all(ALL_KEY_SPECS, environ)
        if resolution.is_usable
    )


__all__ = [
    "KeyState",
    "ApiKeySpec",
    "KeyResolution",
    "resolve_key",
    "resolve_all",
    "has_key",
    "get_key_spec",
    "configured_providers",
    "ALL_KEY_SPECS",
    "ALCHEMY",
    "INFURA",
    "QUICKNODE",
    "ANKR",
    "DRPC",
    "BLOCKPI",
    "CHAINSTACK",
    "GETBLOCK",
    "NOWNODES",
    "ETHERSCAN",
    "MORALIS",
    "COVALENT",
    "HELIUS",
    "BLOCKCYPHER",
    "COINGECKO",
    "CRYPTOCOMPARE",
]
