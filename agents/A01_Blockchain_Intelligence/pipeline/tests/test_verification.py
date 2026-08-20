"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for label verification and corroboration.
"""

from __future__ import annotations

import pytest

from database import Database
from pipeline.verification import LabelVerifier, VerificationReport
from tiers.ledger import (
    CONFIDENCE,
    CORROBORATED,
    EVM_SCOPE,
    UNVERIFIED,
    VERIFIED,
    Label,
    LabelRepository,
)

BINANCE = "0x28c6c06298d514db089934071355e5743bf21d60"
COINBASE = "0x71660c4005ba85c37ccec55d0c4493e66fe775d3"
OKX = "0x5041ed759dd4afc3a72b8192c143f72f4724081a"


@pytest.fixture
def db():
    with Database() as database:
        yield database


@pytest.fixture
def repo(db):
    return LabelRepository(db)


@pytest.fixture
def verifier(db):
    return LabelVerifier(db)


def _label(address: str, entity: str, source: str, **kwargs) -> Label:
    return Label(
        chain=EVM_SCOPE,
        address=address,
        label=entity,
        entity=entity,
        category="exchange",
        source=source,
        confidence=kwargs.get("confidence", CONFIDENCE[UNVERIFIED]),
        verification_status=kwargs.get("verification_status", UNVERIFIED),
    )


# ==============================================================================
# CORROBORATION
# ==============================================================================


def test_single_source_is_not_corroborated(repo, verifier):
    repo.save(_label(BINANCE, "Binance", "source_a"))

    result = verifier.corroborate(EVM_SCOPE, BINANCE)

    assert result is None


def test_two_sources_same_entity_corroborates(repo, verifier):
    repo.save(_label(BINANCE, "Binance", "source_a"))
    repo.save(_label(BINANCE, "Binance", "source_b"))

    result = verifier.corroborate(EVM_SCOPE, BINANCE)

    assert result is not None
    assert result.new_status == CORROBORATED
    assert result.new_confidence == CONFIDENCE[CORROBORATED]
    assert result.old_status == UNVERIFIED
    assert "source_a" in result.sources
    assert "source_b" in result.sources


def test_two_sources_different_entity_does_not_corroborate(repo, verifier):
    repo.save(_label(BINANCE, "Binance", "source_a"))
    repo.save(_label(BINANCE, "Coinbase", "source_b"))

    result = verifier.corroborate(EVM_SCOPE, BINANCE)

    assert result is None


def test_already_corroborated_is_not_re_upgraded(repo, verifier):
    repo.save(_label(
        BINANCE, "Binance", "source_a",
        confidence=CONFIDENCE[CORROBORATED],
        verification_status=CORROBORATED,
    ))
    repo.save(_label(
        BINANCE, "Binance", "source_b",
        confidence=CONFIDENCE[CORROBORATED],
        verification_status=CORROBORATED,
    ))

    result = verifier.corroborate(EVM_SCOPE, BINANCE)

    assert result is None


def test_corroboration_persists_in_database(repo, verifier):
    repo.save(_label(BINANCE, "Binance", "source_a"))
    repo.save(_label(BINANCE, "Binance", "source_b"))

    verifier.corroborate(EVM_SCOPE, BINANCE)

    labels = repo.lookup(EVM_SCOPE, BINANCE)
    assert all(l.verification_status == CORROBORATED for l in labels)
    assert all(l.confidence == CONFIDENCE[CORROBORATED] for l in labels)


# ==============================================================================
# MANUAL VERIFICATION
# ==============================================================================


def test_verify_upgrades_to_verified(repo, verifier):
    repo.save(_label(BINANCE, "Binance", "source_a"))

    result = verifier.verify(
        EVM_SCOPE, BINANCE,
        evidence="operator published address on binance.com/wallet-addresses",
    )

    assert result is not None
    assert result.new_status == VERIFIED
    assert result.new_confidence == CONFIDENCE[VERIFIED]


def test_verify_already_verified_returns_none(repo, verifier):
    repo.save(_label(
        BINANCE, "Binance", "source_a",
        confidence=CONFIDENCE[VERIFIED],
        verification_status=VERIFIED,
    ))

    result = verifier.verify(
        EVM_SCOPE, BINANCE,
        evidence="operator published it",
    )

    assert result is None


def test_verify_unknown_address_returns_none(repo, verifier):
    result = verifier.verify(
        EVM_SCOPE, "0x0000000000000000000000000000000000000001",
        evidence="proof",
    )

    assert result is None


# ==============================================================================
# BATCH SCAN
# ==============================================================================


def test_scan_finds_corroborations(repo, verifier):
    repo.save(_label(BINANCE, "Binance", "source_a"))
    repo.save(_label(BINANCE, "Binance", "source_b"))
    repo.save(_label(COINBASE, "Coinbase", "source_a"))

    report = verifier.scan(EVM_SCOPE)

    assert isinstance(report, VerificationReport)
    assert report.scanned == 2
    assert report.corroborated == 1
    assert report.unchanged == 1
    assert len(report.changes) == 1
    assert report.changes[0].address == BINANCE


def test_scan_skips_already_verified(repo, verifier):
    repo.save(_label(
        BINANCE, "Binance", "source_a",
        confidence=CONFIDENCE[VERIFIED],
        verification_status=VERIFIED,
    ))

    report = verifier.scan(EVM_SCOPE)

    assert report.already_verified == 1
    assert report.corroborated == 0


# ==============================================================================
# STATUS
# ==============================================================================


def test_status_reports_distribution(repo, verifier):
    repo.save(_label(BINANCE, "Binance", "source_a"))
    repo.save(_label(COINBASE, "Coinbase", "source_a",
                     confidence=CONFIDENCE[CORROBORATED],
                     verification_status=CORROBORATED))

    status = verifier.status(EVM_SCOPE)

    assert status["total"] == 2
    assert status["unverified"] == 1
    assert status["corroborated"] == 1
    assert status["verified"] == 0
    assert status["coverage"] == 0.5
