"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    sensors

Purpose:
    The capture layer. Everything A01 knows about a chain enters here.

Layer contract
--------------
Sensors decide *how to obtain* an observation and nothing else. They do not
score, rank, classify, or interpret; a sensor that returns "this looks like a
whale transfer" has taken a decision belonging to ``intelligence/``, and the
boundary exists so that decision can be reviewed in one place.

Two properties are established here and cannot be recovered later:

* **Provenance.** Which provider served a payload is known only at the moment
  it is served. Attaching it afterwards is a reconstruction, which is exactly
  what the evidence standard forbids.
* **Determinacy.** "The chain says there is nothing" and "A01 could not ask"
  are different facts. Every read returns a :class:`SensorResult` so a caller
  cannot silently collapse the second into the first.

See ``docs/architecture/folder-architecture.md`` and ``identity/design_rules.md``
DR-01 for the layer rules.
"""

from __future__ import annotations

from .base import Capability, Sensor, chain_str
from .envelope import (
    CaptureGap,
    Provenance,
    RawRecord,
    RecordKind,
    SensorResult,
    content_id,
)
from .evm.rpc_sensor import (
    DEFAULT_LOG_RANGE,
    EvmRpcSensor,
    parse_quantity,
    to_quantity,
)
from .market.price_sensor import (
    DEFAULT_CACHE_TTL,
    DEFILLAMA_COINS_BASE,
    HttpMarketClient,
    MarketResponse,
    PriceFeedSensor,
)
from .registry import SensorRegistry, default_registry

__all__ = [
    "DEFAULT_CACHE_TTL",
    "DEFAULT_LOG_RANGE",
    "DEFILLAMA_COINS_BASE",
    "Capability",
    "CaptureGap",
    "EvmRpcSensor",
    "HttpMarketClient",
    "MarketResponse",
    "PriceFeedSensor",
    "Provenance",
    "RawRecord",
    "RecordKind",
    "Sensor",
    "SensorRegistry",
    "SensorResult",
    "chain_str",
    "content_id",
    "default_registry",
    "parse_quantity",
    "to_quantity",
]
