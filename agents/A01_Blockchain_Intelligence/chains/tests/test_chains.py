"""
Tests for the 15-chain directory structure.

Verifies that every chain in the registry has a numbered directory with
the required files, that adapters are importable and correctly typed, and
that Bitcoin does not claim to be account-based.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from config.rpc.chains import ChainName, ChainType

from chains import CHAIN_ORDER, CHAINS_DIR
from chains.base import ChainAdapter, EvmAdapter, SolanaAdapter, UtxoAdapter


REQUIRED_FILES = ("README.md", "endpoints.yaml", "limits.yaml", "adapter.py")

NUMBERED_DIRS = tuple(
    f"{i:02d}_{name}" for i, name in enumerate(CHAIN_ORDER, 1)
)


def _read_yaml_field(path: Path, field: str) -> str | None:
    """Read a top-level YAML field value from a file (simple parser)."""
    pattern = re.compile(rf"^{re.escape(field)}\s*:\s*(.+)$", re.MULTILINE)
    text = path.read_text(encoding="utf-8")
    m = pattern.search(text)
    if m:
        val = m.group(1).strip()
        if "#" in val:
            val = val[:val.index("#")].strip()
        val = val.strip('"').strip("'")
        return val
    return None


def _yaml_has_field(path: Path, field: str) -> bool:
    """Check if a top-level YAML field exists."""
    pattern = re.compile(rf"^{re.escape(field)}\s*:", re.MULTILINE)
    text = path.read_text(encoding="utf-8")
    return bool(pattern.search(text))


def _count_providers(path: Path) -> int:
    """Count provider entries in endpoints.yaml by '- name:' lines."""
    text = path.read_text(encoding="utf-8")
    return len(re.findall(r"^\s+-\s+name:", text, re.MULTILINE))


def test_all_15_chain_directories_exist():
    for d in NUMBERED_DIRS:
        path = CHAINS_DIR / d
        assert path.is_dir(), f"missing chain directory: {d}"


def test_exactly_15_chains():
    assert len(CHAIN_ORDER) == 15
    assert len(NUMBERED_DIRS) == 15


def test_chain_order_matches_registry():
    registry_names = tuple(c.value for c in ChainName)
    assert CHAIN_ORDER == registry_names


def test_each_directory_has_required_files():
    for d in NUMBERED_DIRS:
        chain_dir = CHAINS_DIR / d
        for fname in REQUIRED_FILES:
            fpath = chain_dir / fname
            assert fpath.is_file(), f"{d} missing {fname}"
            assert fpath.stat().st_size > 0, f"{d}/{fname} is empty"


def test_endpoints_yaml_has_chain_and_providers():
    for d in NUMBERED_DIRS:
        path = CHAINS_DIR / d / "endpoints.yaml"
        assert _yaml_has_field(path, "chain"), f"{d}/endpoints.yaml missing 'chain'"
        assert _yaml_has_field(path, "providers"), f"{d}/endpoints.yaml missing 'providers'"
        assert _count_providers(path) > 0, f"{d}/endpoints.yaml has no providers"


def test_limits_yaml_has_required_fields():
    for d in NUMBERED_DIRS:
        path = CHAINS_DIR / d / "limits.yaml"
        for field in ("chain", "has_sensor", "finality", "reorg_depth", "limits"):
            assert _yaml_has_field(path, field), f"{d}/limits.yaml missing '{field}'"


def test_all_adapters_importable():
    for d in NUMBERED_DIRS:
        mod_name = f"chains.{d}.adapter"
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, "adapter"), f"{mod_name} has no 'adapter' attribute"
        assert isinstance(mod.adapter, ChainAdapter), (
            f"{mod_name}.adapter is not a ChainAdapter"
        )


def test_evm_chains_use_evm_adapter():
    evm_dirs = NUMBERED_DIRS[:13]  # 01-13 are EVM
    for d in evm_dirs:
        mod = importlib.import_module(f"chains.{d}.adapter")
        assert isinstance(mod.adapter, EvmAdapter), (
            f"{d} should use EvmAdapter, got {type(mod.adapter).__name__}"
        )
        assert mod.adapter.chain_type == ChainType.EVM
        assert mod.adapter.is_account_based is True
        assert mod.adapter.is_utxo is False
        assert mod.adapter.has_sensor is True
        assert mod.adapter.sensor_family == "evm"


def test_solana_adapter():
    mod = importlib.import_module("chains.14_solana.adapter")
    assert isinstance(mod.adapter, SolanaAdapter)
    assert mod.adapter.chain == ChainName.SOLANA
    assert mod.adapter.chain_type == ChainType.SOLANA_LIKE
    assert mod.adapter.has_sensor is False
    assert mod.adapter.sensor_family == "solana"


def test_bitcoin_adapter_is_utxo():
    mod = importlib.import_module("chains.15_bitcoin.adapter")
    assert isinstance(mod.adapter, UtxoAdapter)
    assert mod.adapter.chain == ChainName.BITCOIN
    assert mod.adapter.chain_type == ChainType.BITCOIN_LIKE
    assert mod.adapter.is_utxo is True
    assert mod.adapter.is_account_based is False
    assert mod.adapter.has_sensor is False
    assert mod.adapter.sensor_family == "utxo"


def test_bitcoin_adapter_does_not_claim_evm_features():
    """Bitcoin must never claim account-based features."""
    mod = importlib.import_module("chains.15_bitcoin.adapter")
    a = mod.adapter
    assert a.is_account_based is False
    assert a.is_utxo is True
    assert a.has_sensor is False
    limits_path = CHAINS_DIR / "15_bitcoin" / "limits.yaml"
    chain_type = _read_yaml_field(limits_path, "chain_type")
    assert chain_type == "bitcoin_like"
    has_sensor = _read_yaml_field(limits_path, "has_sensor")
    assert has_sensor == "false"


def test_endpoints_yaml_chain_names_match_directory():
    for i, name in enumerate(CHAIN_ORDER, 1):
        d = f"{i:02d}_{name}"
        path = CHAINS_DIR / d / "endpoints.yaml"
        chain_val = _read_yaml_field(path, "chain")
        assert chain_val == name, (
            f"{d}/endpoints.yaml chain is {chain_val!r}, expected {name!r}"
        )


def test_limits_yaml_chain_names_match_directory():
    for i, name in enumerate(CHAIN_ORDER, 1):
        d = f"{i:02d}_{name}"
        path = CHAINS_DIR / d / "limits.yaml"
        chain_val = _read_yaml_field(path, "chain")
        assert chain_val == name, (
            f"{d}/limits.yaml chain is {chain_val!r}, expected {name!r}"
        )


def test_adapter_chain_names_match_directory():
    for i, name in enumerate(CHAIN_ORDER, 1):
        d = f"{i:02d}_{name}"
        mod = importlib.import_module(f"chains.{d}.adapter")
        assert mod.adapter.chain.value == name, (
            f"{d}/adapter.py chain is {mod.adapter.chain.value!r}, expected {name!r}"
        )


def test_no_api_keys_in_endpoints_yaml():
    """No endpoint file should contain an actual API key value."""
    for d in NUMBERED_DIRS:
        path = CHAINS_DIR / d / "endpoints.yaml"
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("env_var:"):
                value = stripped.split(":", 1)[1].strip()
                assert not value.startswith("alch_"), f"{d} contains a real key"
                assert not value.startswith("sk-"), f"{d} contains a real key"


def test_chain_adapter_repr():
    mod = importlib.import_module("chains.01_ethereum.adapter")
    assert "ethereum" in repr(mod.adapter)


def test_readme_exists_and_nonempty():
    for d in NUMBERED_DIRS:
        readme = CHAINS_DIR / d / "README.md"
        content = readme.read_text(encoding="utf-8")
        assert len(content) > 50, f"{d}/README.md is too short"
        assert "Observable" in content or "observable" in content.lower() or "sensor" in content.lower(), (
            f"{d}/README.md does not mention observability"
        )
