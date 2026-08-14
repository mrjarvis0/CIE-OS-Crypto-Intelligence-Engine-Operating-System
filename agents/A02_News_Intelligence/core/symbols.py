"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.symbols

Purpose:
    Static registry of known financial symbols (stocks, crypto, forex)
    used for entity extraction. No network calls, no business logic.
"""

from __future__ import annotations

from typing import Final

# ==============================================================================
# STOCKS (curated majors — extend freely)
# ==============================================================================

STOCK_SYMBOLS: Final[dict[str, str]] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "AMZN": "Amazon",
    "NVDA": "NVIDIA",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    "JPM": "JPMorgan Chase",
    "BAC": "Bank of America",
    "WMT": "Walmart",
    "V": "Visa",
    "MA": "Mastercard",
    "UNH": "UnitedHealth",
    "LLY": "Eli Lilly",
    "AVGO": "Broadcom",
    "ORCL": "Oracle",
    "KO": "Coca-Cola",
    "PEP": "PepsiCo",
    "PFE": "Pfizer",
    "MRK": "Merck",
    "ABBV": "AbbVie",
    "TMO": "Thermo Fisher",
    "COST": "Costco",
    "CRM": "Salesforce",
    "AMD": "AMD",
    "INTC": "Intel",
    "QCOM": "Qualcomm",
    "NFLX": "Netflix",
    "DIS": "Disney",
    "BA": "Boeing",
    "GE": "General Electric",
    "CAT": "Caterpillar",
    "CVX": "Chevron",
    "PG": "Procter & Gamble",
    "HD": "Home Depot",
    "MCD": "McDonald's",
    "NKE": "Nike",
    "SBUX": "Starbucks",
    "VZ": "Verizon",
    "T": "AT&T",
    "CMCSA": "Comcast",
    "ADBE": "Adobe",
    "CSCO": "Cisco",
    "IBM": "IBM",
    "ABNB": "Airbnb",
    "UBER": "Uber",
    "SHOP": "Shopify",
    "PLTR": "Palantir",
    "SOFI": "SoFi",
    "COIN": "Coinbase",
    "MSTR": "MicroStrategy",
    "HOOD": "Robinhood",
    "RIVN": "Rivian",
    "LCID": "Lucid",
}

# ==============================================================================
# CRYPTO
# ==============================================================================

CRYPTO_SYMBOLS: Final[dict[str, str]] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "USDT": "Tether",
    "USDC": "USD Coin",
    "BNB": "BNB",
    "XRP": "XRP",
    "SOL": "Solana",
    "ADA": "Cardano",
    "DOGE": "Dogecoin",
    "AVAX": "Avalanche",
    "DOT": "Polkadot",
    "LINK": "Chainlink",
    "LTC": "Litecoin",
    "UNI": "Uniswap",
    "ATOM": "Cosmos",
    "XLM": "Stellar",
    "TRX": "TRON",
    "TON": "Toncoin",
    "SHIB": "Shiba Inu",
    "PEPE": "Pepe",
    "APT": "Aptos",
    "ARB": "Arbitrum",
    "OP": "Optimism",
    "SUI": "Sui",
    "NEAR": "NEAR Protocol",
    "FIL": "Filecoin",
    "ICP": "Internet Computer",
    "ETC": "Ethereum Classic",
    "HBAR": "Hedera",
    "AAVE": "Aave",
}

# ==============================================================================
# FOREX
# ==============================================================================

FOREX_PAIRS: Final[dict[str, str]] = {
    "EURUSD": "Euro / US Dollar",
    "GBPUSD": "Pound / US Dollar",
    "USDJPY": "US Dollar / Yen",
    "USDCHF": "US Dollar / Franc",
    "AUDUSD": "Aussie / US Dollar",
    "NZDUSD": "Kiwi / US Dollar",
    "USDCAD": "US Dollar / Canadian Dollar",
    "USDCNH": "US Dollar / Offshore Yuan",
    "EURGBP": "Euro / Pound",
    "EURJPY": "Euro / Yen",
}

# ==============================================================================
# NAME ALIASES (lowercase name -> symbol)
# ==============================================================================

NAME_ALIASES: Final[dict[str, str]] = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "meta": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "jpmorgan": "JPM",
    "netflix": "NFLX",
    "disney": "DIS",
    "boeing": "BA",
    "intel": "INTC",
    "amd": "AMD",
    "qualcomm": "QCOM",
    "coinbase": "COIN",
    "robinhood": "HOOD",
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "tether": "USDT",
    "binance coin": "BNB",
    "ripple": "XRP",
    "solana": "SOL",
    "cardano": "ADA",
    "dogecoin": "DOGE",
    "avalanche": "AVAX",
    "polkadot": "DOT",
    "chainlink": "LINK",
    "litecoin": "LTC",
    "uniswap": "UNI",
    "cosmos": "ATOM",
    "stellar": "XLM",
    "tron": "TRX",
    "toncoin": "TON",
    "shiba inu": "SHIB",
    "pepe": "PEPE",
    "aptos": "APT",
    "arbitrum": "ARB",
    "optimism": "OP",
    "sui": "SUI",
    "near protocol": "NEAR",
    "filecoin": "FIL",
    "internet computer": "ICP",
    "ethereum classic": "ETC",
    "hedera": "HBAR",
    "aave": "AAVE",
}

# ==============================================================================
# COMBINED LOOKUPS
# ==============================================================================

ALL_SYMBOLS: Final[dict[str, str]] = {
    **STOCK_SYMBOLS,
    **CRYPTO_SYMBOLS,
    **FOREX_PAIRS,
}

ALL_TYPES: Final[dict[str, str]] = {
    **{sym: "stock" for sym in STOCK_SYMBOLS},
    **{sym: "crypto" for sym in CRYPTO_SYMBOLS},
    **{sym: "forex" for sym in FOREX_PAIRS},
}


def entity_type_for(symbol: str) -> str | None:
    """Return entity type ('stock' | 'crypto' | 'forex') for a symbol."""

    return ALL_TYPES.get(symbol.upper())


def name_for(symbol: str) -> str | None:
    """Return canonical display name for a symbol."""

    return ALL_SYMBOLS.get(symbol.upper())


__all__ = [
    "STOCK_SYMBOLS",
    "CRYPTO_SYMBOLS",
    "FOREX_PAIRS",
    "NAME_ALIASES",
    "ALL_SYMBOLS",
    "ALL_TYPES",
    "entity_type_for",
    "name_for",
]
