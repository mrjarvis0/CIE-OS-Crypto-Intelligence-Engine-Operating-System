"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for blockchain.providers -- the endpoint catalog and credential
resolution.

These tests never touch the network. Everything here is about whether the
catalog describes itself honestly: that a keyed endpoint stays dormant without
a key, that a credential cannot escape into a log line, and that capability
flags mean what a detector will assume they mean.
"""

from __future__ import annotations

import pytest

from blockchain.rpc.providers import (
    Access,
    Endpoint,
    Protocol,
    ProviderRole,
    default_catalog,
    resolve_key,
)
from blockchain.rpc.providers import keys as keyspecs
from blockchain.rpc.providers.keys import KeyState
from config.rpc.chains import (
    ChainName,
    ChainType,
    default_registry,
)
from config.rpc.rpc_config import build_default_rpc_registry

NO_ENV: dict[str, str] = {}


# ==============================================================================
# CATALOG INTEGRITY
# ==============================================================================

def test_every_registered_chain_has_node_endpoints():
    """
    A chain in the registry with no endpoints is a silent dead end: callers
    resolve it happily and then find nothing to talk to.
    """
    catalog = default_catalog()
    for chain in default_registry():
        assert catalog.for_chain(chain.name), f"{chain.name.value} has no node endpoints"


def test_every_chain_is_reachable_without_any_credential():
    """
    The free-tier promise. If any chain needs a key just to answer a single
    call, A01 is not usable out of the box on that chain.
    """
    catalog = default_catalog()
    for chain in default_registry():
        usable = catalog.available(chain.name, environ=NO_ENV)
        assert usable, f"{chain.name.value} unreachable without credentials"


def test_no_duplicate_endpoints():
    """A provider serving one chain in one role twice means one is dead config."""
    catalog = default_catalog()
    seen: set[tuple[str, str, str]] = set()
    for endpoint in catalog.endpoints:
        marker = (endpoint.provider, endpoint.chain.value, endpoint.role.value)
        assert marker not in seen, f"duplicate endpoint: {marker}"
        seen.add(marker)


def test_protocol_matches_chain_family():
    """
    A Solana endpoint reached with EVM methods fails in a confusing way, so
    the protocol tag has to track the chain's actual family.
    """
    catalog = default_catalog()
    registry = default_registry()

    expected = {
        ChainType.EVM: Protocol.EVM_JSON_RPC,
        ChainType.SOLANA_LIKE: Protocol.SOLANA_JSON_RPC,
    }
    for chain in registry:
        if chain.chain_type not in expected:
            continue
        for endpoint in catalog.for_chain(chain.name):
            assert endpoint.protocol == expected[chain.chain_type], (
                f"{endpoint.provider} on {chain.name.value} declares "
                f"{endpoint.protocol.value}"
            )


def test_bitcoin_uses_rest_not_json_rpc():
    """
    There is no public Bitcoin JSON-RPC to point at. Esplora REST is the only
    realistic route, and mislabelling it would send the JSON-RPC dispatcher at
    an endpoint that cannot answer it.
    """
    catalog = default_catalog()
    for endpoint in catalog.for_chain(ChainName.BITCOIN):
        assert endpoint.protocol in {Protocol.ESPLORA_REST, Protocol.VENDOR_REST}


def test_keyed_endpoints_declare_a_key_spec():
    catalog = default_catalog()
    for endpoint in catalog.endpoints:
        if endpoint.access == Access.KEYED_FREE:
            assert endpoint.key_spec is not None, endpoint.provider
        else:
            assert "{key}" not in endpoint.url_template, endpoint.provider


def test_open_endpoint_with_key_placeholder_is_rejected():
    """
    An open endpoint carrying a placeholder would dispatch the literal string
    "{key}" to a live host. Construction has to refuse it.
    """
    with pytest.raises(ValueError, match="key placeholder"):
        Endpoint(
            provider="broken",
            chain=ChainName.ETHEREUM,
            role=ProviderRole.NODE,
            protocol=Protocol.EVM_JSON_RPC,
            url_template="https://example.invalid/v2/{key}",
            access=Access.OPEN,
        )


def test_keyed_endpoint_without_spec_is_rejected():
    with pytest.raises(ValueError, match="requires a key_spec"):
        Endpoint(
            provider="broken",
            chain=ChainName.ETHEREUM,
            role=ProviderRole.NODE,
            protocol=Protocol.EVM_JSON_RPC,
            url_template="https://example.invalid/v2/{key}",
            access=Access.KEYED_FREE,
        )


# ==============================================================================
# CREDENTIAL RESOLUTION
# ==============================================================================

def test_absent_key_resolves_to_absent():
    resolution = resolve_key(keyspecs.ALCHEMY, environ=NO_ENV)
    assert resolution.state == KeyState.ABSENT
    assert not resolution.is_usable


def test_blank_key_is_distinguished_from_absent():
    """
    An empty ALCHEMY_API_KEY= line looks configured and fails on first call.
    Reporting it as BLANK rather than ABSENT is what lets doctor say why.
    """
    resolution = resolve_key(keyspecs.ALCHEMY, environ={"ALCHEMY_API_KEY": "   "})
    assert resolution.state == KeyState.BLANK
    assert not resolution.is_usable


def test_present_key_resolves_and_is_retrievable():
    resolution = resolve_key(keyspecs.ALCHEMY, environ={"ALCHEMY_API_KEY": "abc123"})
    assert resolution.state == KeyState.PRESENT
    assert resolution.is_usable
    assert resolution.secret is not None
    assert resolution.secret.get_secret_value() == "abc123"


def test_alternate_env_var_is_accepted():
    """Providers that were renamed still ship two accepted variable names."""
    resolution = resolve_key(keyspecs.COVALENT, environ={"GOLDRUSH_API_KEY": "xyz"})
    assert resolution.is_usable
    assert resolution.env_var == "GOLDRUSH_API_KEY"


def test_first_matching_env_var_wins():
    resolution = resolve_key(
        keyspecs.COVALENT,
        environ={"COVALENT_API_KEY": "first", "GOLDRUSH_API_KEY": "second"},
    )
    assert resolution.secret is not None
    assert resolution.secret.get_secret_value() == "first"


# ==============================================================================
# CREDENTIAL CONTAINMENT
# ==============================================================================

def test_key_never_appears_in_endpoint_as_dict():
    """
    as_dict() feeds doctor output and health snapshots, both of which get
    printed and logged. A key reaching either is a disclosure.
    """
    catalog = default_catalog()
    env = {"ALCHEMY_API_KEY": "SUPER-SECRET-VALUE"}
    for endpoint in catalog.available(ChainName.ETHEREUM, environ=env):
        assert "SUPER-SECRET-VALUE" not in str(endpoint.as_dict())


def test_key_never_appears_in_resolution_as_dict():
    resolution = resolve_key(keyspecs.ALCHEMY, environ={"ALCHEMY_API_KEY": "LEAKME"})
    assert "LEAKME" not in str(resolution.as_dict())


def test_coverage_report_carries_no_credentials():
    catalog = default_catalog()
    report = catalog.coverage(environ={"ALCHEMY_API_KEY": "LEAKME", "ETHERSCAN_API_KEY": "LEAKME2"})
    rendered = str(report)
    assert "LEAKME" not in rendered
    assert "LEAKME2" not in rendered


# ==============================================================================
# AVAILABILITY FILTERING
# ==============================================================================

def test_keyed_endpoint_is_dormant_without_its_key():
    catalog = default_catalog()
    providers = {e.provider for e in catalog.available(ChainName.ETHEREUM, environ=NO_ENV)}
    assert "alchemy" not in providers
    assert "infura" not in providers


def test_keyed_endpoint_activates_when_key_appears():
    """The whole point of the dormant design: a key, no code change."""
    catalog = default_catalog()
    before = {e.provider for e in catalog.available(ChainName.ETHEREUM, environ=NO_ENV)}
    after = {
        e.provider
        for e in catalog.available(ChainName.ETHEREUM, environ={"ALCHEMY_API_KEY": "k"})
    }
    assert "alchemy" not in before
    assert "alchemy" in after
    assert before < after


def test_blank_key_does_not_activate_a_provider():
    catalog = default_catalog()
    providers = {
        e.provider
        for e in catalog.available(ChainName.ETHEREUM, environ={"ALCHEMY_API_KEY": ""})
    }
    assert "alchemy" not in providers


def test_no_evm_archive_endpoint_exists_without_a_key():
    """
    Pins the constraint that governs DET-DORMANT-01 and every backtest: free
    public EVM endpoints serve recent state only. If this test ever starts
    failing because an open archive endpoint was added, the dormancy detector
    and the evaluation harness both gain a capability, and the change should
    be deliberate rather than incidental.
    """
    catalog = default_catalog()
    for chain in default_registry().list_evm_chains():
        archival = catalog.available(chain.name, require_archive=True, environ=NO_ENV)
        assert not archival, (
            f"{chain.name.value} now has open archive access via "
            f"{[e.provider for e in archival]}"
        )


def test_bitcoin_is_archival_without_a_key():
    """Bitcoin Esplora serves full history, so BTC dormancy is answerable free."""
    catalog = default_catalog()
    archival = catalog.available(ChainName.BITCOIN, require_archive=True, environ=NO_ENV)
    assert archival


def test_archive_filter_admits_alchemy_once_keyed():
    catalog = default_catalog()
    archival = catalog.available(
        ChainName.ETHEREUM, require_archive=True, environ={"ALCHEMY_API_KEY": "k"}
    )
    assert [e.provider for e in archival] == ["alchemy"]


def test_rendered_url_substitutes_the_key():
    catalog = default_catalog()
    (endpoint,) = catalog.available(
        ChainName.ETHEREUM, require_archive=True, environ={"ALCHEMY_API_KEY": "K1"}
    )
    assert endpoint.render_url({"ALCHEMY_API_KEY": "K1"}).endswith("/v2/K1")


def test_whole_url_credentials_are_used_verbatim():
    """QuickNode and Chainstack issue a URL, not a key; there is nothing to substitute."""
    catalog = default_catalog()
    env = {"QUICKNODE_URL": "https://tenant.quiknode.pro/abc/"}
    quicknode = [
        e for e in catalog.available(ChainName.ETHEREUM, environ=env) if e.provider == "quicknode"
    ]
    assert quicknode
    assert quicknode[0].render_url(env) == "https://tenant.quiknode.pro/abc/"


# ==============================================================================
# CREDENTIAL CARRIERS
# ==============================================================================
#
# Three providers carry a credential three different ways, and getting one
# wrong produces a request that fails a long way from its cause.

def test_header_keyed_endpoint_keeps_its_url_and_moves_the_key_to_a_header():
    """
    Regression. Inferring "no {key} placeholder" as "the credential is the
    whole URL" turned NowNodes -- which authenticates with an api-key header
    against a fixed URL -- into a bare key dispatched as an endpoint.
    """
    catalog = default_catalog()
    env = {"NOWNODES_API_KEY": "NNKEY"}
    nownodes = [
        e for e in catalog.available(ChainName.BITCOIN, environ=env) if e.provider == "nownodes"
    ]
    assert nownodes
    endpoint = nownodes[0]

    assert endpoint.render_url(env) == "https://btcbook.nownodes.io/api"
    assert endpoint.auth_headers(env) == {"api-key": "NNKEY"}


def test_url_keyed_endpoint_reports_no_auth_headers():
    """The secret is already in the URL; duplicating it into a header would leak it twice."""
    catalog = default_catalog()
    env = {"QUICKNODE_URL": "https://tenant.quiknode.pro/abc/"}
    (quicknode,) = [
        e for e in catalog.available(ChainName.ETHEREUM, environ=env) if e.provider == "quicknode"
    ]
    assert quicknode.auth_headers(env) == {}


def test_auth_headers_are_empty_without_a_key():
    catalog = default_catalog()
    nownodes = [e for e in catalog.for_chain(ChainName.BITCOIN) if e.provider == "nownodes"]
    assert nownodes[0].auth_headers(NO_ENV) == {}


def test_endpoint_with_two_credential_carriers_is_rejected():
    with pytest.raises(ValueError, match="exactly one credential carrier"):
        Endpoint(
            provider="broken",
            chain=ChainName.ETHEREUM,
            role=ProviderRole.NODE,
            protocol=Protocol.EVM_JSON_RPC,
            url_template="https://example.invalid/{key}",
            access=Access.KEYED_FREE,
            key_spec=keyspecs.ALCHEMY,
            key_header="x-api-key",
        )


def test_endpoint_with_no_credential_carrier_is_rejected():
    """A keyed endpoint that never applies its key would silently send anonymous requests."""
    with pytest.raises(ValueError, match="exactly one credential carrier"):
        Endpoint(
            provider="broken",
            chain=ChainName.ETHEREUM,
            role=ProviderRole.NODE,
            protocol=Protocol.EVM_JSON_RPC,
            url_template="https://example.invalid/rpc",
            access=Access.KEYED_FREE,
            key_spec=keyspecs.ALCHEMY,
        )


def test_key_is_url_requires_a_bare_placeholder_template():
    with pytest.raises(ValueError, match="must be exactly"):
        Endpoint(
            provider="broken",
            chain=ChainName.ETHEREUM,
            role=ProviderRole.NODE,
            protocol=Protocol.EVM_JSON_RPC,
            url_template="https://example.invalid/{key}",
            access=Access.KEYED_FREE,
            key_spec=keyspecs.QUICKNODE,
            key_is_url=True,
        )


def test_open_endpoint_cannot_declare_a_credential_carrier():
    with pytest.raises(ValueError, match="require keyed_free access"):
        Endpoint(
            provider="broken",
            chain=ChainName.ETHEREUM,
            role=ProviderRole.NODE,
            protocol=Protocol.EVM_JSON_RPC,
            url_template="https://example.invalid/rpc",
            access=Access.OPEN,
            key_header="x-api-key",
        )


def test_every_rendered_url_is_a_url():
    """
    Sweep the whole catalog with every key populated. This is the check that
    would have caught the NowNodes bug: a credential carrier applied the wrong
    way produces something that is not a URL at all.
    """
    catalog = default_catalog()
    env = {spec.primary_env_var: "https://tenant.example/rpc" for spec in keyspecs.ALL_KEY_SPECS}

    for endpoint in catalog.endpoints:
        url = endpoint.render_url(env)
        assert url is not None, endpoint.provider
        assert url.startswith(("http://", "https://")), f"{endpoint.provider} rendered {url!r}"


# ==============================================================================
# INTEGRATION WITH THE EXISTING RPC MACHINERY
# ==============================================================================

def test_overrides_populate_the_existing_rpc_registry():
    """
    chains.py ships no URLs and rpc_config.py already knows how to turn a URL
    sequence into prioritised endpoints. The catalog only supplies the
    sequence -- this test is the seam.
    """
    catalog = default_catalog()
    registry = build_default_rpc_registry(overrides=catalog.rpc_overrides(environ=NO_ENV))

    ethereum = registry.get(ChainName.ETHEREUM)
    assert ethereum.has_endpoints
    assert len(ethereum.endpoints) == len(catalog.available(ChainName.ETHEREUM, environ=NO_ENV))


def test_registry_endpoints_are_ordered_for_failover():
    catalog = default_catalog()
    registry = build_default_rpc_registry(overrides=catalog.rpc_overrides(environ=NO_ENV))
    ordered = registry.get(ChainName.ETHEREUM).ordered_endpoints

    priorities = [endpoint.priority for endpoint in ordered]
    assert priorities == sorted(priorities)
    assert len(set(priorities)) == len(priorities), "ties make failover order arbitrary"


def test_every_catalogued_url_is_accepted_by_rpc_validation():
    """
    RpcEndpoint validates scheme and netloc on construction. A malformed URL in
    the catalog would surface as an import-time crash somewhere far away, so
    catch it here instead.
    """
    catalog = default_catalog()
    env = {
        "ALCHEMY_API_KEY": "k",
        "INFURA_API_KEY": "k",
        "DRPC_API_KEY": "k",
        "BLOCKPI_API_KEY": "k",
        "GETBLOCK_API_KEY": "k",
        "HELIUS_API_KEY": "k",
        "NOWNODES_API_KEY": "k",
    }
    registry = build_default_rpc_registry(overrides=catalog.rpc_overrides(environ=env))
    for config in registry.all():
        for endpoint in config.endpoints:
            assert endpoint.transport is not None


def test_overrides_omit_chains_with_nothing_usable():
    """An empty URL list would build a chain config that cannot serve a request."""
    catalog = default_catalog()
    for chain, urls in catalog.rpc_overrides(environ=NO_ENV).items():
        assert urls, f"{chain.value} mapped to an empty URL list"


# ==============================================================================
# OPERATOR REPORTING
# ==============================================================================

def test_dormant_providers_lists_missing_keys_archive_first():
    """
    doctor uses this to tell an operator which key is worth getting. An
    archive provider unlocks whole detectors; another latest-state endpoint
    only adds redundancy, so ordering carries the recommendation.
    """
    catalog = default_catalog()
    dormant = catalog.dormant_providers(environ=NO_ENV)
    assert dormant

    archive_flags = [entry["unlocks_archive"] for entry in dormant]
    assert archive_flags == sorted(archive_flags, reverse=True)
    assert dormant[0]["unlocks_archive"] is True
    assert all(entry["env_var"] for entry in dormant)


def test_supplying_a_key_removes_it_from_the_dormant_list():
    catalog = default_catalog()
    dormant = catalog.dormant_providers(environ={"ALCHEMY_API_KEY": "k"})
    assert "alchemy" not in {entry["provider"] for entry in dormant}


def test_coverage_counts_are_self_consistent():
    catalog = default_catalog()
    for chain, info in catalog.coverage(environ=NO_ENV).items():
        assert info["usable"] <= info["catalogued"], chain
        assert info["open"] + info["keyed"] == info["usable"], chain
        assert info["archive"] <= info["usable"], chain
