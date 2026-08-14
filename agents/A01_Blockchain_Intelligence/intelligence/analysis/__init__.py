"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.analysis

Purpose:
    Domain analyzers that convert raw subject data into structured
    analysis results and supporting evidence.

Submodules
----------
base           Shared Analyzer base and result model.
wallet         Wallet profiling.
token          Token analysis.
contract       Contract analysis.
protocol       Protocol analysis.
dex            DEX analysis.
dormant        Dormant wallet reactivation.
nft            NFT analysis.
bridge         Bridge analysis.
exchange       Directional flow against labelled exchange addresses.
governance     Governance analysis.
transaction    Transaction analysis.
whale          Whale activity analysis.
liquidity      Liquidity analysis.
gas            Gas analysis.
market         Market analysis.
"""

from __future__ import annotations

from .anomaly import AnomalyAnalyzer
from .base import Analyzer, AnalyzerResult, BaseAnalyzer
from .bridge import BridgeAnalyzer
from .contract import ContractAnalyzer
from .dex import DexAnalyzer
from .dormant import DormantAnalyzer
from .exchange import ExchangeFlowAnalyzer
from .gas import GasAnalyzer
from .governance import GovernanceAnalyzer
from .liquidity import LiquidityAnalyzer
from .market import MarketAnalyzer
from .nft import NftAnalyzer
from .protocol import ProtocolAnalyzer
from .token import TokenAnalyzer
from .transaction import TransactionAnalyzer
from .wallet import WalletAnalyzer
from .whale import WhaleAnalyzer

__all__ = [
    "Analyzer",
    "AnalyzerResult",
    "AnomalyAnalyzer",
    "BaseAnalyzer",
    "WalletAnalyzer",
    "TokenAnalyzer",
    "ContractAnalyzer",
    "ProtocolAnalyzer",
    "DexAnalyzer",
    "DormantAnalyzer",
    "NftAnalyzer",
    "BridgeAnalyzer",
    "ExchangeFlowAnalyzer",
    "GovernanceAnalyzer",
    "TransactionAnalyzer",
    "WhaleAnalyzer",
    "LiquidityAnalyzer",
    "GasAnalyzer",
    "MarketAnalyzer",
]
