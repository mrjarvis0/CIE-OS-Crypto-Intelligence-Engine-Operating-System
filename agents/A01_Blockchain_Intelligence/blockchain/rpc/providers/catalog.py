"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.providers.catalog

Purpose:
    The catalog of node and explorer endpoints A01 can read chain data from,
    across every chain in the chain registry.

Design goals:
    - Free-tier first: A01 must be usable with no credentials at all
    - Keyed providers declared but dormant until a key appears
    - Capability flags carried per endpoint, not assumed
    - No network I/O at import
    - No secrets in the catalog itself

Notes:
    Two properties of this catalog matter more than its size.

    The first is ``archive``. Most free public endpoints serve recent state
    only, typically 128 blocks, and answer historical queries with a pruning
    error rather than a wrong number. DET-DORMANT-01 asks how long an address
    sat still, and a backtest replays historical windows by definition, so
    both are unanswerable without an archive endpoint. Recording the flag here
    lets a detector decline for lack of data instead of silently reading a
    truncated history as genuine dormancy.

    The second is that endpoints rot. Public RPCs are withdrawn, rate-limited
    or repointed without notice, so nothing here is assumed live: the health
    probe in transport/ decides what is usable, and this catalog only supplies
    candidates ordered by expected quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Mapping, Sequence

from config.rpc.chains import ChainName

from . import keys as keyspecs
from .keys import ApiKeySpec, resolve_key


# ==============================================================================
# ENUMS
# ==============================================================================

class Protocol(StrEnum):
    """Wire protocol an endpoint speaks."""

    #: Ethereum JSON-RPC 2.0 over HTTP. All EVM chains.
    EVM_JSON_RPC = "evm_json_rpc"
    #: Solana JSON-RPC. Same envelope as EVM, entirely different method set.
    SOLANA_JSON_RPC = "solana_json_rpc"
    #: Esplora REST (Blockstream and compatible). The practical way to read
    #: Bitcoin without running a node -- public Bitcoin JSON-RPC is not a thing.
    ESPLORA_REST = "esplora_rest"
    #: Etherscan-family REST, including the V2 multichain endpoint.
    ETHERSCAN_REST = "etherscan_rest"
    #: Blockscout REST. Open, no key, weaker label coverage than Etherscan.
    BLOCKSCOUT_REST = "blockscout_rest"
    #: Vendor-specific REST that fits none of the above.
    VENDOR_REST = "vendor_rest"


class Access(StrEnum):
    """What it takes to use an endpoint."""

    #: Usable immediately, no credential.
    OPEN = "open"
    #: Free tier, but a key must be supplied.
    KEYED_FREE = "keyed_free"


class ProviderRole(StrEnum):
    """What A01 reads from a provider."""

    #: Raw node access: blocks, receipts, logs, eth_call.
    NODE = "node"
    #: Indexed history and labels: address transaction lists, verified source.
    EXPLORER = "explorer"
    #: Prices, supply, market structure.
    MARKET = "market"


# ==============================================================================
# MODELS
# ==============================================================================

@dataclass(frozen=True, slots=True)
class Endpoint:
    """
    One provider endpoint for one chain.

    ``url_template`` may contain a single ``{key}`` placeholder. Rendering is
    the only point at which a credential enters a URL, and rendering is
    refused when the credential is missing, so a half-substituted URL can
    never be dispatched.
    """

    provider: str
    chain: ChainName
    role: ProviderRole
    protocol: Protocol
    url_template: str
    access: Access = Access.OPEN
    key_spec: ApiKeySpec | None = None

    #: The credential is the entire endpoint URL, not a value to substitute.
    #: QuickNode and Chainstack issue a per-tenant URL and have no separate key.
    key_is_url: bool = False
    #: The credential travels in this request header and the URL is fixed.
    #: NowNodes authenticates with `api-key`, so nothing goes in the URL at all.
    key_header: str | None = None

    #: Serves state older than the recent-block window. Required by
    #: DET-DORMANT-01 and by every backtest.
    archive: bool = False
    #: Serves eth_getLogs over wide block ranges without truncating.
    logs: bool = False
    #: Serves debug_/trace_ methods. Needed for internal-transaction analysis.
    traces: bool = False

    #: Documented free-tier ceiling. Advisory: the limiter treats it as a
    #: budget, and a 429 is still authoritative over whatever is written here.
    rate_limit_per_minute: int = 60
    timeout_seconds: int = 30
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("provider cannot be empty")
        if not self.url_template.strip():
            raise ValueError(f"{self.provider}: url_template cannot be empty")
        if self.rate_limit_per_minute <= 0:
            raise ValueError(f"{self.provider}: rate_limit_per_minute must be > 0")
        if self.timeout_seconds <= 0:
            raise ValueError(f"{self.provider}: timeout_seconds must be > 0")

        needs_key = self.access == Access.KEYED_FREE
        if needs_key and self.key_spec is None:
            raise ValueError(f"{self.provider}: keyed access requires a key_spec")
        if "{key}" in self.url_template and not needs_key:
            raise ValueError(
                f"{self.provider}: url_template has a key placeholder but access is {self.access.value}"
            )

        # How the credential reaches the provider must be stated, never
        # inferred. Treating "no placeholder" as "the key is the URL" quietly
        # turns a header-authenticated provider into a bare key dispatched as
        # an endpoint, which fails far from its cause.
        if needs_key:
            carriers = (
                "{key}" in self.url_template and not self.key_is_url,
                self.key_is_url,
                self.key_header is not None,
            )
            if sum(carriers) != 1:
                raise ValueError(
                    f"{self.provider}: a keyed endpoint needs exactly one credential "
                    f"carrier -- a {{key}} placeholder, key_is_url, or key_header"
                )
        elif self.key_is_url or self.key_header:
            raise ValueError(
                f"{self.provider}: credential carriers require {Access.KEYED_FREE.value} access"
            )

        if self.key_is_url and self.url_template.strip() != "{key}":
            raise ValueError(
                f"{self.provider}: key_is_url means the URL comes wholly from the "
                f"credential, so url_template must be exactly '{{key}}'"
            )

    @property
    def requires_key(self) -> bool:
        return self.access == Access.KEYED_FREE

    def render_url(self, environ: Mapping[str, str] | None = None) -> str | None:
        """
        Resolve the endpoint to a usable URL, or ``None`` if it is unavailable.

        ``None`` is the ordinary result for a keyed provider with no key set;
        callers filter rather than handle an exception, because running the
        whole catalog with no credentials at all is the expected default.
        """
        if not self.requires_key:
            return self.url_template

        assert self.key_spec is not None  # guaranteed by __post_init__
        resolution = resolve_key(self.key_spec, environ)
        if not resolution.is_usable or resolution.secret is None:
            return None

        secret = resolution.secret.get_secret_value()

        if self.key_is_url:
            return secret
        if self.key_header is not None:
            # The URL is fixed; the credential is applied by auth_headers().
            return self.url_template
        return self.url_template.replace("{key}", secret)

    def auth_headers(self, environ: Mapping[str, str] | None = None) -> dict[str, str]:
        """
        Headers carrying this endpoint's credential, if it travels that way.

        Kept separate from ``render_url`` so a URL can be logged or compared
        without dragging a header secret along with it.
        """
        if self.key_header is None or not self.requires_key:
            return {}

        assert self.key_spec is not None  # guaranteed by __post_init__
        resolution = resolve_key(self.key_spec, environ)
        if not resolution.is_usable or resolution.secret is None:
            return {}
        return {self.key_header: resolution.secret.get_secret_value()}

    def as_dict(self) -> dict[str, Any]:
        """Redacted description. Never contains a rendered URL."""
        return {
            "provider": self.provider,
            "chain": self.chain.value,
            "role": self.role.value,
            "protocol": self.protocol.value,
            "access": self.access.value,
            "archive": self.archive,
            "logs": self.logs,
            "traces": self.traces,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "requires_key": self.requires_key,
            "key_env_var": self.key_spec.primary_env_var if self.key_spec else None,
            "notes": self.notes,
        }


# ==============================================================================
# ENDPOINT HELPERS
# ==============================================================================

def _open_node(
    provider: str,
    chain: ChainName,
    url: str,
    *,
    protocol: Protocol = Protocol.EVM_JSON_RPC,
    archive: bool = False,
    logs: bool = False,
    traces: bool = False,
    rate_limit_per_minute: int = 60,
    notes: str = "",
) -> Endpoint:
    """Build an open node endpoint. Trims the catalog's repetition."""
    return Endpoint(
        provider=provider,
        chain=chain,
        role=ProviderRole.NODE,
        protocol=protocol,
        url_template=url,
        access=Access.OPEN,
        archive=archive,
        logs=logs,
        traces=traces,
        rate_limit_per_minute=rate_limit_per_minute,
        notes=notes,
    )


def _keyed_node(
    provider: str,
    chain: ChainName,
    url_template: str,
    key_spec: ApiKeySpec,
    *,
    protocol: Protocol = Protocol.EVM_JSON_RPC,
    archive: bool = True,
    logs: bool = True,
    traces: bool = False,
    key_is_url: bool = False,
    key_header: str | None = None,
    rate_limit_per_minute: int = 300,
    notes: str = "",
) -> Endpoint:
    """Build a keyed node endpoint, dormant until its key is supplied."""
    return Endpoint(
        provider=provider,
        chain=chain,
        role=ProviderRole.NODE,
        protocol=protocol,
        url_template=url_template,
        access=Access.KEYED_FREE,
        key_spec=key_spec,
        key_is_url=key_is_url,
        key_header=key_header,
        archive=archive,
        logs=logs,
        traces=traces,
        rate_limit_per_minute=rate_limit_per_minute,
        notes=notes,
    )


# ==============================================================================
# EVM NODE ENDPOINTS
# ==============================================================================
#
# Ordering is priority order, and it is deliberate: keyed archive providers
# come first because an archive endpoint can answer strictly more questions,
# then the better-behaved open endpoints, then the rest as failover. The
# fallback manager reorders on observed health, so this is a starting guess,
# not a fixed hierarchy.

_ETHEREUM_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "alchemy", ChainName.ETHEREUM,
        "https://eth-mainnet.g.alchemy.com/v2/{key}", keyspecs.ALCHEMY,
        traces=True,
        notes="Free tier serves archive state, which is what makes dormancy measurable.",
    ),
    _keyed_node(
        "infura", ChainName.ETHEREUM,
        "https://mainnet.infura.io/v3/{key}", keyspecs.INFURA,
        archive=False,
        notes="Free tier is latest-state only; archive needs a paid plan.",
    ),
    _keyed_node(
        "quicknode", ChainName.ETHEREUM,
        "{key}", keyspecs.QUICKNODE, traces=True, key_is_url=True,
        notes="The issued URL is itself the credential.",
    ),
    _keyed_node(
        "chainstack", ChainName.ETHEREUM,
        "{key}", keyspecs.CHAINSTACK, key_is_url=True,
    ),
    _keyed_node(
        "drpc", ChainName.ETHEREUM,
        "https://lb.drpc.org/ogrpc?network=ethereum&dkey={key}", keyspecs.DRPC,
    ),
    _keyed_node(
        "blockpi", ChainName.ETHEREUM,
        "https://ethereum.blockpi.network/v1/rpc/{key}", keyspecs.BLOCKPI,
    ),
    _keyed_node(
        "getblock", ChainName.ETHEREUM,
        "https://go.getblock.io/{key}", keyspecs.GETBLOCK,
    ),
    _open_node(
        "publicnode", ChainName.ETHEREUM,
        "https://ethereum-rpc.publicnode.com",
        logs=True, rate_limit_per_minute=120,
        notes="Allnodes-operated. Among the more dependable open endpoints.",
    ),
    _open_node(
        "llamarpc", ChainName.ETHEREUM,
        "https://eth.llamarpc.com", logs=True,
    ),
    _open_node(
        "ankr-public", ChainName.ETHEREUM,
        "https://rpc.ankr.com/eth", logs=True,
        notes="Open tier of the same infrastructure ANKR_API_KEY unlocks.",
    ),
    _open_node(
        "cloudflare", ChainName.ETHEREUM,
        "https://cloudflare-eth.com",
        notes="Very stable, but no logs and no archive.",
    ),
    _open_node("1rpc", ChainName.ETHEREUM, "https://1rpc.io/eth"),
    _open_node("drpc-public", ChainName.ETHEREUM, "https://eth.drpc.org", logs=True),
    _open_node(
        "flashbots", ChainName.ETHEREUM, "https://rpc.flashbots.net",
        notes="Built for private tx submission; read methods work but are not its purpose.",
    ),
    _open_node("merkle", ChainName.ETHEREUM, "https://eth.merkle.io"),
)

_BNB_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "quicknode", ChainName.BNB_CHAIN, "{key}", keyspecs.QUICKNODE, key_is_url=True,
    ),
    _keyed_node(
        "drpc", ChainName.BNB_CHAIN,
        "https://lb.drpc.org/ogrpc?network=bsc&dkey={key}", keyspecs.DRPC,
    ),
    _keyed_node(
        "blockpi", ChainName.BNB_CHAIN,
        "https://bsc.blockpi.network/v1/rpc/{key}", keyspecs.BLOCKPI,
    ),
    _open_node(
        "binance-dataseed", ChainName.BNB_CHAIN,
        "https://bsc-dataseed.bnbchain.org", logs=True, rate_limit_per_minute=120,
        notes="Operated by the chain itself.",
    ),
    _open_node("binance-dataseed-1", ChainName.BNB_CHAIN, "https://bsc-dataseed1.bnbchain.org", logs=True),
    _open_node("defibit", ChainName.BNB_CHAIN, "https://bsc-dataseed1.defibit.io", logs=True),
    _open_node("ninicoin", ChainName.BNB_CHAIN, "https://bsc-dataseed1.ninicoin.io", logs=True),
    _open_node("publicnode", ChainName.BNB_CHAIN, "https://bsc-rpc.publicnode.com", logs=True),
    _open_node("ankr-public", ChainName.BNB_CHAIN, "https://rpc.ankr.com/bsc", logs=True),
    _open_node("1rpc", ChainName.BNB_CHAIN, "https://1rpc.io/bnb"),
    _open_node("drpc-public", ChainName.BNB_CHAIN, "https://bsc.drpc.org", logs=True),
)

_POLYGON_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "alchemy", ChainName.POLYGON,
        "https://polygon-mainnet.g.alchemy.com/v2/{key}", keyspecs.ALCHEMY, traces=True,
    ),
    _keyed_node(
        "infura", ChainName.POLYGON,
        "https://polygon-mainnet.infura.io/v3/{key}", keyspecs.INFURA, archive=False,
    ),
    _keyed_node(
        "drpc", ChainName.POLYGON,
        "https://lb.drpc.org/ogrpc?network=polygon&dkey={key}", keyspecs.DRPC,
    ),
    _keyed_node(
        "blockpi", ChainName.POLYGON,
        "https://polygon.blockpi.network/v1/rpc/{key}", keyspecs.BLOCKPI,
    ),
    _open_node(
        "polygon-official", ChainName.POLYGON,
        "https://polygon-rpc.com", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.POLYGON, "https://polygon-bor-rpc.publicnode.com", logs=True),
    _open_node("llamarpc", ChainName.POLYGON, "https://polygon.llamarpc.com", logs=True),
    _open_node("ankr-public", ChainName.POLYGON, "https://rpc.ankr.com/polygon", logs=True),
    _open_node("1rpc", ChainName.POLYGON, "https://1rpc.io/matic"),
    _open_node("drpc-public", ChainName.POLYGON, "https://polygon.drpc.org", logs=True),
)

_ARBITRUM_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "alchemy", ChainName.ARBITRUM,
        "https://arb-mainnet.g.alchemy.com/v2/{key}", keyspecs.ALCHEMY, traces=True,
    ),
    _keyed_node(
        "infura", ChainName.ARBITRUM,
        "https://arbitrum-mainnet.infura.io/v3/{key}", keyspecs.INFURA, archive=False,
    ),
    _keyed_node(
        "drpc", ChainName.ARBITRUM,
        "https://lb.drpc.org/ogrpc?network=arbitrum&dkey={key}", keyspecs.DRPC,
    ),
    _open_node(
        "arbitrum-official", ChainName.ARBITRUM,
        "https://arb1.arbitrum.io/rpc", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.ARBITRUM, "https://arbitrum-one-rpc.publicnode.com", logs=True),
    _open_node("llamarpc", ChainName.ARBITRUM, "https://arbitrum.llamarpc.com", logs=True),
    _open_node("ankr-public", ChainName.ARBITRUM, "https://rpc.ankr.com/arbitrum", logs=True),
    _open_node("1rpc", ChainName.ARBITRUM, "https://1rpc.io/arb"),
    _open_node("drpc-public", ChainName.ARBITRUM, "https://arbitrum.drpc.org", logs=True),
)

_OPTIMISM_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "alchemy", ChainName.OPTIMISM,
        "https://opt-mainnet.g.alchemy.com/v2/{key}", keyspecs.ALCHEMY, traces=True,
    ),
    _keyed_node(
        "infura", ChainName.OPTIMISM,
        "https://optimism-mainnet.infura.io/v3/{key}", keyspecs.INFURA, archive=False,
    ),
    _keyed_node(
        "drpc", ChainName.OPTIMISM,
        "https://lb.drpc.org/ogrpc?network=optimism&dkey={key}", keyspecs.DRPC,
    ),
    _open_node(
        "optimism-official", ChainName.OPTIMISM,
        "https://mainnet.optimism.io", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.OPTIMISM, "https://optimism-rpc.publicnode.com", logs=True),
    _open_node("llamarpc", ChainName.OPTIMISM, "https://optimism.llamarpc.com", logs=True),
    _open_node("ankr-public", ChainName.OPTIMISM, "https://rpc.ankr.com/optimism", logs=True),
    _open_node("1rpc", ChainName.OPTIMISM, "https://1rpc.io/op"),
    _open_node("drpc-public", ChainName.OPTIMISM, "https://optimism.drpc.org", logs=True),
)

_BASE_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "alchemy", ChainName.BASE,
        "https://base-mainnet.g.alchemy.com/v2/{key}", keyspecs.ALCHEMY, traces=True,
    ),
    _keyed_node(
        "drpc", ChainName.BASE,
        "https://lb.drpc.org/ogrpc?network=base&dkey={key}", keyspecs.DRPC,
    ),
    _keyed_node(
        "blockpi", ChainName.BASE,
        "https://base.blockpi.network/v1/rpc/{key}", keyspecs.BLOCKPI,
    ),
    _open_node(
        "base-official", ChainName.BASE,
        "https://mainnet.base.org", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.BASE, "https://base-rpc.publicnode.com", logs=True),
    _open_node("llamarpc", ChainName.BASE, "https://base.llamarpc.com", logs=True),
    _open_node("1rpc", ChainName.BASE, "https://1rpc.io/base"),
    _open_node("drpc-public", ChainName.BASE, "https://base.drpc.org", logs=True),
)

_AVALANCHE_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "drpc", ChainName.AVALANCHE,
        "https://lb.drpc.org/ogrpc?network=avalanche&dkey={key}", keyspecs.DRPC,
    ),
    _keyed_node(
        "blockpi", ChainName.AVALANCHE,
        "https://avalanche.blockpi.network/v1/rpc/{key}", keyspecs.BLOCKPI,
    ),
    _open_node(
        "avalanche-official", ChainName.AVALANCHE,
        "https://api.avax.network/ext/bc/C/rpc", logs=True, rate_limit_per_minute=120,
    ),
    _open_node(
        "publicnode", ChainName.AVALANCHE,
        "https://avalanche-c-chain-rpc.publicnode.com", logs=True,
    ),
    _open_node("ankr-public", ChainName.AVALANCHE, "https://rpc.ankr.com/avalanche", logs=True),
    _open_node("1rpc", ChainName.AVALANCHE, "https://1rpc.io/avax/c"),
    _open_node("drpc-public", ChainName.AVALANCHE, "https://avalanche.drpc.org", logs=True),
)

# ------------------------------------------------------------------------------
# The six chains added after the first nine.
#
# Every endpoint below was probed before it was written down: eth_chainId to
# confirm the URL reaches the chain it claims to, eth_getBlockByNumber with full
# transactions, and eth_getLogs over a recent block. Only endpoints that
# answered all three are listed, which is why these blocks are shorter than the
# ones above and why none of them carries a keyed provider.
#
# **No keyed endpoints, and that is a measurement too.** Alchemy's documented
# per-network URLs for all six answered 403 with the credential this deployment
# holds -- an Alchemy key is authorised per network, and these are not on it. A
# 403 cannot be told apart from a wrong URL without a key that should work, so
# rather than record six endpoints as "probably fine" they are omitted. The
# consequence is real and worth stating: these chains have no archive upgrade
# path, so DET-DORMANT-01 and any backtest are unavailable on them until a key
# covering them exists.
# ------------------------------------------------------------------------------

_LINEA_NODES: Final[tuple[Endpoint, ...]] = (
    _open_node(
        "linea-official", ChainName.LINEA,
        "https://rpc.linea.build", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.LINEA, "https://linea-rpc.publicnode.com", logs=True),
    _open_node("1rpc", ChainName.LINEA, "https://1rpc.io/linea", logs=True),
    _open_node("drpc-public", ChainName.LINEA, "https://linea.drpc.org", logs=True),
)

_SCROLL_NODES: Final[tuple[Endpoint, ...]] = (
    _open_node(
        "scroll-official", ChainName.SCROLL,
        "https://rpc.scroll.io", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.SCROLL, "https://scroll-rpc.publicnode.com", logs=True),
    _open_node("1rpc", ChainName.SCROLL, "https://1rpc.io/scroll", logs=True),
    _open_node(
        "drpc-public", ChainName.SCROLL, "https://scroll.drpc.org", logs=True,
        notes="Served blocks on probe; its log read was refused under load, so it ranks last.",
    ),
)

_GNOSIS_NODES: Final[tuple[Endpoint, ...]] = (
    _open_node(
        "gnosis-official", ChainName.GNOSIS,
        "https://rpc.gnosischain.com", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.GNOSIS, "https://gnosis-rpc.publicnode.com", logs=True),
    _open_node(
        "1rpc", ChainName.GNOSIS, "https://1rpc.io/gnosis", logs=True,
        notes="Answered logs but refused a full-transaction block read on probe.",
    ),
)

_CELO_NODES: Final[tuple[Endpoint, ...]] = (
    _open_node(
        "celo-official", ChainName.CELO,
        "https://forno.celo.org", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.CELO, "https://celo-rpc.publicnode.com", logs=True),
    _open_node("ankr-public", ChainName.CELO, "https://rpc.ankr.com/celo", logs=True),
)

_MANTLE_NODES: Final[tuple[Endpoint, ...]] = (
    _open_node(
        "mantle-official", ChainName.MANTLE,
        "https://rpc.mantle.xyz", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.MANTLE, "https://mantle-rpc.publicnode.com", logs=True),
    _open_node("1rpc", ChainName.MANTLE, "https://1rpc.io/mantle", logs=True),
)

_UNICHAIN_NODES: Final[tuple[Endpoint, ...]] = (
    _open_node(
        "unichain-official", ChainName.UNICHAIN,
        "https://mainnet.unichain.org", logs=True, rate_limit_per_minute=120,
    ),
    _open_node("publicnode", ChainName.UNICHAIN, "https://unichain-rpc.publicnode.com", logs=True),
    _open_node("drpc-public", ChainName.UNICHAIN, "https://unichain.drpc.org", logs=True),
)


# ==============================================================================
# NON-EVM NODE ENDPOINTS
# ==============================================================================

_SOLANA_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "helius", ChainName.SOLANA,
        "https://mainnet.helius-rpc.com/?api-key={key}", keyspecs.HELIUS,
        protocol=Protocol.SOLANA_JSON_RPC,
        notes="Only realistic free route to Solana history; the public endpoint prunes aggressively.",
    ),
    _keyed_node(
        "quicknode", ChainName.SOLANA, "{key}", keyspecs.QUICKNODE, key_is_url=True,
        protocol=Protocol.SOLANA_JSON_RPC,
    ),
    _open_node(
        "solana-official", ChainName.SOLANA,
        "https://api.mainnet-beta.solana.com",
        protocol=Protocol.SOLANA_JSON_RPC, rate_limit_per_minute=60,
        notes="Rate-limited hard and explicitly not for production; fine for a health probe.",
    ),
    _open_node(
        "publicnode", ChainName.SOLANA,
        "https://solana-rpc.publicnode.com", protocol=Protocol.SOLANA_JSON_RPC,
    ),
    _open_node(
        "ankr-public", ChainName.SOLANA,
        "https://rpc.ankr.com/solana", protocol=Protocol.SOLANA_JSON_RPC,
    ),
    _open_node("1rpc", ChainName.SOLANA, "https://1rpc.io/sol", protocol=Protocol.SOLANA_JSON_RPC),
    _open_node(
        "drpc-public", ChainName.SOLANA,
        "https://solana.drpc.org", protocol=Protocol.SOLANA_JSON_RPC,
    ),
)

_BITCOIN_NODES: Final[tuple[Endpoint, ...]] = (
    _keyed_node(
        "nownodes", ChainName.BITCOIN,
        "https://btcbook.nownodes.io/api", keyspecs.NOWNODES,
        protocol=Protocol.ESPLORA_REST, key_header="api-key",
        notes="Blockbook-flavoured REST rather than strict Esplora.",
    ),
    _open_node(
        "blockstream", ChainName.BITCOIN,
        "https://blockstream.info/api",
        protocol=Protocol.ESPLORA_REST, archive=True, rate_limit_per_minute=60,
        notes=(
            "Reference Esplora deployment. Bitcoin is fully archival by nature, "
            "so unlike the EVM endpoints historical queries are answerable here."
        ),
    ),
    _open_node(
        "mempool-space", ChainName.BITCOIN,
        "https://mempool.space/api",
        protocol=Protocol.ESPLORA_REST, archive=True, rate_limit_per_minute=60,
        notes="Esplora-compatible; better mempool visibility than Blockstream.",
    ),
    Endpoint(
        provider="blockcypher",
        chain=ChainName.BITCOIN,
        role=ProviderRole.NODE,
        protocol=Protocol.VENDOR_REST,
        url_template="https://api.blockcypher.com/v1/btc/main",
        access=Access.OPEN,
        archive=True,
        rate_limit_per_minute=3,
        notes="Usable without a token at roughly 3/min; BLOCKCYPHER_TOKEN raises it substantially.",
    ),
)


# ==============================================================================
# EXPLORER ENDPOINTS
# ==============================================================================
#
# Explorers supply what a node cannot: an address's transaction history
# without scanning every block, verified contract source, and the entity
# labels attribution depends on. The attribution doctrine caps a label-derived
# claim at the attribution tier precisely because these are third-party
# assertions, not chain facts -- so provenance has to record which explorer
# said it.

#: Chains the V2 multichain endpoint actually serves, and only those.
#:
#: Membership was probed rather than assumed, using the fact that a keyless V2
#: request distinguishes the two failures: a supported chain answers "Missing/
#: Invalid API Key" and an unsupported one answers "unsupported chainid". A
#: nonsense chain id was sent as a control to confirm the second message means
#: what it appears to.
#:
#: **Scroll is absent for that reason.** Its chain id 534352 returns the
#: unsupported-chainid message, identical to the control, so listing it would
#: have produced an explorer endpoint that can never answer. Scroll's explorer
#: coverage comes from Blockscout below instead.
_ETHERSCAN_V2_CHAIN_IDS: Final[Mapping[ChainName, int]] = {
    ChainName.ETHEREUM: 1,
    ChainName.BNB_CHAIN: 56,
    ChainName.POLYGON: 137,
    ChainName.ARBITRUM: 42161,
    ChainName.OPTIMISM: 10,
    ChainName.BASE: 8453,
    ChainName.AVALANCHE: 43114,
    ChainName.LINEA: 59144,
    ChainName.GNOSIS: 100,
    ChainName.CELO: 42220,
    ChainName.MANTLE: 5000,
    ChainName.UNICHAIN: 130,
}


def _etherscan_v2(chain: ChainName) -> Endpoint:
    """
    Etherscan V2 endpoint for an EVM chain.

    V2 collapsed the per-chain explorer keys into one key plus a chainid
    parameter, so a single ETHERSCAN_API_KEY now covers every chain in
    ``_ETHERSCAN_V2_CHAIN_IDS``.
    """
    chain_id = _ETHERSCAN_V2_CHAIN_IDS[chain]
    return Endpoint(
        provider="etherscan-v2",
        chain=chain,
        role=ProviderRole.EXPLORER,
        protocol=Protocol.ETHERSCAN_REST,
        url_template=f"https://api.etherscan.io/v2/api?chainid={chain_id}&apikey={{key}}",
        access=Access.KEYED_FREE,
        key_spec=keyspecs.ETHERSCAN,
        archive=True,
        logs=True,
        rate_limit_per_minute=300,
        notes="One key covers every V2 chain. Free tier is 5 calls/second.",
    )


def _blockscout(chain: ChainName, host: str) -> Endpoint:
    """Open Blockscout instance. No key, thinner labels than Etherscan."""
    return Endpoint(
        provider="blockscout",
        chain=chain,
        role=ProviderRole.EXPLORER,
        protocol=Protocol.BLOCKSCOUT_REST,
        url_template=f"https://{host}/api",
        access=Access.OPEN,
        archive=True,
        logs=True,
        rate_limit_per_minute=60,
        notes="Open explorer API; verified source and history, weaker entity labelling.",
    )


_EXPLORERS: Final[tuple[Endpoint, ...]] = (
    _etherscan_v2(ChainName.ETHEREUM),
    _blockscout(ChainName.ETHEREUM, "eth.blockscout.com"),
    _etherscan_v2(ChainName.BNB_CHAIN),
    _etherscan_v2(ChainName.POLYGON),
    _blockscout(ChainName.POLYGON, "polygon.blockscout.com"),
    _etherscan_v2(ChainName.ARBITRUM),
    _blockscout(ChainName.ARBITRUM, "arbitrum.blockscout.com"),
    _etherscan_v2(ChainName.OPTIMISM),
    _blockscout(ChainName.OPTIMISM, "optimism.blockscout.com"),
    _etherscan_v2(ChainName.BASE),
    _blockscout(ChainName.BASE, "base.blockscout.com"),
    _etherscan_v2(ChainName.AVALANCHE),
    # The six later chains. Each Blockscout host below was probed and returned
    # that chain's own head; the hosts a reader would expect for Linea and
    # Mantle (explorer.linea.build, mantle.blockscout.com) answered 404 and are
    # therefore not listed. Scroll is the one chain with no Etherscan V2 route,
    # so its Blockscout instance is its only explorer.
    _etherscan_v2(ChainName.LINEA),
    _blockscout(ChainName.SCROLL, "scroll.blockscout.com"),
    _etherscan_v2(ChainName.GNOSIS),
    _blockscout(ChainName.GNOSIS, "gnosis.blockscout.com"),
    _etherscan_v2(ChainName.CELO),
    _blockscout(ChainName.CELO, "celo.blockscout.com"),
    _etherscan_v2(ChainName.MANTLE),
    _etherscan_v2(ChainName.UNICHAIN),
    _blockscout(ChainName.UNICHAIN, "unichain.blockscout.com"),
    Endpoint(
        provider="blockstream",
        chain=ChainName.BITCOIN,
        role=ProviderRole.EXPLORER,
        protocol=Protocol.ESPLORA_REST,
        url_template="https://blockstream.info/api",
        access=Access.OPEN,
        archive=True,
        rate_limit_per_minute=60,
    ),
    Endpoint(
        provider="helius",
        chain=ChainName.SOLANA,
        role=ProviderRole.EXPLORER,
        protocol=Protocol.VENDOR_REST,
        url_template="https://api.helius.xyz/v0?api-key={key}",
        access=Access.KEYED_FREE,
        key_spec=keyspecs.HELIUS,
        archive=True,
        rate_limit_per_minute=60,
        notes="Parsed Solana transaction history; no open equivalent worth wiring.",
    ),
)


# ==============================================================================
# MARKET ENDPOINTS
# ==============================================================================
#
# Market data is not decoration. DET-WHALE-01 ranks a transfer against the
# asset's own distribution and applies a USD floor, so without price and
# supply the detector cannot run at all -- an absolute token-count threshold
# is exactly the published evasion guide the detection catalog forbids.

_MARKET: Final[tuple[Endpoint, ...]] = (
    Endpoint(
        provider="coingecko",
        chain=ChainName.ETHEREUM,  # cross-chain; keyed to a chain for registry shape
        role=ProviderRole.MARKET,
        protocol=Protocol.VENDOR_REST,
        url_template="https://api.coingecko.com/api/v3",
        access=Access.OPEN,
        rate_limit_per_minute=10,
        notes="Open tier is roughly 10-30/min and throttles hard. Caching is not optional.",
    ),
    Endpoint(
        provider="defillama",
        chain=ChainName.ETHEREUM,
        role=ProviderRole.MARKET,
        protocol=Protocol.VENDOR_REST,
        url_template="https://api.llama.fi",
        access=Access.OPEN,
        rate_limit_per_minute=120,
        notes="No key, generous limits. Protocol TVL and DEX volume.",
    ),
    Endpoint(
        provider="defillama-coins",
        chain=ChainName.ETHEREUM,
        role=ProviderRole.MARKET,
        protocol=Protocol.VENDOR_REST,
        url_template="https://coins.llama.fi",
        access=Access.OPEN,
        rate_limit_per_minute=120,
        notes="Historical token prices by contract address, including at a timestamp.",
    ),
    Endpoint(
        provider="binance-public",
        chain=ChainName.ETHEREUM,
        role=ProviderRole.MARKET,
        protocol=Protocol.VENDOR_REST,
        url_template="https://api.binance.com/api/v3",
        access=Access.OPEN,
        rate_limit_per_minute=1200,
        notes="Open market data. The reference venue for spot price and volume.",
    ),
)


# ==============================================================================
# CATALOG
# ==============================================================================

_NODES_BY_CHAIN: Final[Mapping[ChainName, tuple[Endpoint, ...]]] = {
    ChainName.ETHEREUM: _ETHEREUM_NODES,
    ChainName.BNB_CHAIN: _BNB_NODES,
    ChainName.POLYGON: _POLYGON_NODES,
    ChainName.ARBITRUM: _ARBITRUM_NODES,
    ChainName.OPTIMISM: _OPTIMISM_NODES,
    ChainName.BASE: _BASE_NODES,
    ChainName.AVALANCHE: _AVALANCHE_NODES,
    ChainName.LINEA: _LINEA_NODES,
    ChainName.SCROLL: _SCROLL_NODES,
    ChainName.GNOSIS: _GNOSIS_NODES,
    ChainName.CELO: _CELO_NODES,
    ChainName.MANTLE: _MANTLE_NODES,
    ChainName.UNICHAIN: _UNICHAIN_NODES,
    ChainName.SOLANA: _SOLANA_NODES,
    ChainName.BITCOIN: _BITCOIN_NODES,
}

ALL_ENDPOINTS: Final[tuple[Endpoint, ...]] = tuple(
    endpoint
    for endpoints in _NODES_BY_CHAIN.values()
    for endpoint in endpoints
) + _EXPLORERS + _MARKET


@dataclass(frozen=True, slots=True)
class ProviderCatalog:
    """Queryable view over the endpoint catalog."""

    endpoints: tuple[Endpoint, ...] = field(default=ALL_ENDPOINTS)

    # -- selection ------------------------------------------------------

    def for_chain(
        self,
        chain: ChainName | str,
        *,
        role: ProviderRole = ProviderRole.NODE,
    ) -> tuple[Endpoint, ...]:
        """Every catalogued endpoint for a chain and role, in priority order."""
        key = chain if isinstance(chain, ChainName) else ChainName(str(chain).lower())
        return tuple(e for e in self.endpoints if e.chain == key and e.role == role)

    def by_role(self, role: ProviderRole) -> tuple[Endpoint, ...]:
        return tuple(e for e in self.endpoints if e.role == role)

    def available(
        self,
        chain: ChainName | str,
        *,
        role: ProviderRole = ProviderRole.NODE,
        require_archive: bool = False,
        require_logs: bool = False,
        require_traces: bool = False,
        environ: Mapping[str, str] | None = None,
    ) -> tuple[Endpoint, ...]:
        """
        Endpoints usable right now, after capability and credential filtering.

        A keyed endpoint with no key is dropped rather than reported as
        broken: running credential-free is the default posture, not a fault.
        """
        selected: list[Endpoint] = []
        for endpoint in self.for_chain(chain, role=role):
            if require_archive and not endpoint.archive:
                continue
            if require_logs and not endpoint.logs:
                continue
            if require_traces and not endpoint.traces:
                continue
            if endpoint.render_url(environ) is None:
                continue
            selected.append(endpoint)
        return tuple(selected)

    def urls(
        self,
        chain: ChainName | str,
        *,
        role: ProviderRole = ProviderRole.NODE,
        require_archive: bool = False,
        require_logs: bool = False,
        environ: Mapping[str, str] | None = None,
    ) -> tuple[str, ...]:
        """Rendered URLs for the usable endpoints. May contain credentials."""
        rendered: list[str] = []
        for endpoint in self.available(
            chain,
            role=role,
            require_archive=require_archive,
            require_logs=require_logs,
            environ=environ,
        ):
            url = endpoint.render_url(environ)
            if url is not None:
                rendered.append(url)
        return tuple(rendered)

    # -- integration ----------------------------------------------------

    def rpc_overrides(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> dict[ChainName, tuple[str, ...]]:
        """
        Build the overrides mapping ``build_default_rpc_registry`` accepts.

        This is the whole join between the catalog and the existing RPC
        machinery: chains.py carries no URLs, rpc_config.py already knows how
        to turn a URL sequence into prioritised endpoints with failover, and
        this supplies the sequence. Nothing in config/ had to change.
        """
        overrides: dict[ChainName, tuple[str, ...]] = {}
        for chain in _NODES_BY_CHAIN:
            urls = self.urls(chain, role=ProviderRole.NODE, environ=environ)
            if urls:
                overrides[chain] = urls
        return overrides

    def protocol_for(self, chain: ChainName | str) -> Protocol:
        """
        The wire protocol a chain's node endpoints speak.

        Every node endpoint for a given chain speaks the same protocol, so the
        first one answers for all -- except Bitcoin, where the catalog mixes
        Esplora and vendor REST and the majority form is the right answer.
        """
        endpoints = self.for_chain(chain, role=ProviderRole.NODE)
        if not endpoints:
            raise KeyError(f"No node endpoints catalogued for chain: {chain!r}")
        return endpoints[0].protocol

    # -- reporting ------------------------------------------------------

    def coverage(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Per-chain availability summary for ``doctor``.

        ``archive`` is surfaced separately because a chain can be perfectly
        reachable and still unable to answer a dormancy question.
        """
        report: dict[str, dict[str, Any]] = {}
        for chain in _NODES_BY_CHAIN:
            catalogued = self.for_chain(chain)
            usable = self.available(chain, environ=environ)
            report[chain.value] = {
                "catalogued": len(catalogued),
                "usable": len(usable),
                "open": sum(1 for e in usable if not e.requires_key),
                "keyed": sum(1 for e in usable if e.requires_key),
                "archive": sum(1 for e in usable if e.archive),
                "logs": sum(1 for e in usable if e.logs),
                "traces": sum(1 for e in usable if e.traces),
                "protocol": catalogued[0].protocol.value if catalogued else None,
                "explorers": len(
                    self.available(chain, role=ProviderRole.EXPLORER, environ=environ)
                ),
            }
        return report

    def dormant_providers(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """
        Keyed endpoints sitting idle for want of a credential.

        Ordered so the highest-value missing key comes first: an archive
        endpoint unlocks whole detectors, an extra latest-state endpoint only
        adds redundancy.
        """
        seen: set[str] = set()
        dormant: list[Endpoint] = []
        for endpoint in self.endpoints:
            if not endpoint.requires_key:
                continue
            if endpoint.render_url(environ) is not None:
                continue
            assert endpoint.key_spec is not None
            marker = f"{endpoint.provider}:{endpoint.key_spec.primary_env_var}"
            if marker in seen:
                continue
            seen.add(marker)
            dormant.append(endpoint)

        dormant.sort(key=lambda e: (not e.archive, not e.traces, e.provider))
        return tuple(
            {
                "provider": e.provider,
                "env_var": e.key_spec.primary_env_var if e.key_spec else None,
                "signup_url": e.key_spec.signup_url if e.key_spec else "",
                "unlocks_archive": e.archive,
                "unlocks_traces": e.traces,
                "notes": e.notes,
            }
            for e in dormant
        )


#: Shared catalog instance. Immutable, so sharing it is safe.
DEFAULT_CATALOG: Final[ProviderCatalog] = ProviderCatalog()


def default_catalog() -> ProviderCatalog:
    """Return the shared provider catalog."""
    return DEFAULT_CATALOG


__all__ = [
    "Protocol",
    "Access",
    "ProviderRole",
    "Endpoint",
    "ProviderCatalog",
    "ALL_ENDPOINTS",
    "DEFAULT_CATALOG",
    "default_catalog",
]
