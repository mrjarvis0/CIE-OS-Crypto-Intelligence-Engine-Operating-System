"""Base chain adapter."""

from config.rpc.chains import ChainName, ChainType
from chains.base import EvmAdapter

adapter = EvmAdapter(ChainName.BASE)
