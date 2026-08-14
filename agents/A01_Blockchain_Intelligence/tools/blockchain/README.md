# Blockchain Layer

## Overview

The **Blockchain Layer** is the blockchain intelligence interface of the Tools subsystem.

It provides a unified abstraction over multiple blockchain networks, RPC providers, explorers, indexers, smart contracts, wallets, tokens, NFTs, bridges, and decentralized finance protocols.

The Planning Engine never communicates directly with Ethereum nodes, RPC endpoints, blockchain explorers, or smart contracts.

Instead, every blockchain operation flows through this layer.

---

# Mission

The Blockchain Layer is responsible for:

* Multi-chain abstraction
* Chain discovery
* RPC communication
* Explorer integration
* Wallet analysis
* Transaction analysis
* Token intelligence
* NFT intelligence
* Smart contract interaction
* DeFi protocol access
* Bridge intelligence
* Blockchain metadata
* Event decoding
* Blockchain normalization

Business logic must never exist inside this layer.

---

# Architecture

```text
                     Planner
                        │
                        ▼
                  Tool Manager
                        │
                        ▼
                Blockchain Layer
                        │
 ┌──────────┬──────────┬──────────┬──────────┐
 ▼          ▼          ▼          ▼
Wallet    Token     Contract   Explorer
 │          │          │          │
 ▼          ▼          ▼          ▼
RPC      Indexer    ABI/API     Explorer
 │
 ▼
Blockchain Network
```

---

# Design Principles

The Blockchain Layer follows:

* Chain Independence
* Provider Independence
* Read/Write Separation
* Async First
* Stateless Design
* Capability Based Interfaces
* Event Driven Processing
* High Throughput
* Fault Tolerant RPC
* Extensible Network Support

---

# Directory Structure

```text
blockchain/
│
├── __init__.py
├── ethereum.py
├── evm.py
├── explorer.py
├── wallet.py
├── transaction.py
├── token.py
├── nft.py
├── contract.py
├── defi.py
└── bridge.py
```

---

# Blockchain Request Lifecycle

```text
Planner Request
      │
      ▼
Capability Detection
      │
      ▼
Network Selection
      │
      ▼
RPC / Explorer Selection
      │
      ▼
Request Validation
      │
      ▼
Blockchain Query
      │
      ▼
Data Normalization
      │
      ▼
Evidence Collection
      │
      ▼
Unified Response
```

---

# File Responsibilities

## ethereum.py

Purpose:

Ethereum-specific implementation.

Responsibilities:

* Ethereum Mainnet
* Sepolia
* Network metadata
* Gas estimation
* Block information
* Fee history
* Chain configuration

---

## evm.py

Purpose:

Shared implementation for every EVM-compatible chain.

Supported examples:

* Ethereum
* BNB Chain
* Polygon
* Arbitrum
* Optimism
* Base
* Avalanche C-Chain
* Linea
* Scroll
* zkSync Era

Responsibilities:

* ABI encoding
* Transaction building
* Event decoding
* Address validation
* Block parsing
* Log parsing

---

## explorer.py

Purpose:

Explorer abstraction.

Supported providers:

* Etherscan
* Blockscout
* OKLink
* Routescan
* Chain explorers

Capabilities:

* Address lookup
* Transaction lookup
* Contract lookup
* Token lookup
* Block lookup

---

## wallet.py

Purpose:

Wallet intelligence.

Capabilities:

* Native balance
* Token balances
* NFT holdings
* Portfolio summary
* Wallet labeling
* Counterparty analysis
* Risk indicators
* Behavioral profiling

---

## transaction.py

Purpose:

Transaction intelligence.

Capabilities:

* Transaction decoding
* Internal transfers
* Event logs
* Status tracking
* Fee analysis
* Trace analysis
* Simulation hooks

---

## token.py

Purpose:

Token intelligence.

Supports:

* ERC-20
* ERC-721
* ERC-1155

Capabilities:

* Metadata
* Supply
* Holders
* Transfers
* Price references
* Liquidity references
* Verification status

---

## nft.py

Purpose:

NFT intelligence.

Capabilities:

* Collection metadata
* Ownership
* Transfers
* Floor price hooks
* Marketplace references
* Royalty metadata

---

## contract.py

Purpose:

Smart contract interaction.

Capabilities:

* ABI loading
* Read calls
* Write transaction preparation
* Event decoding
* Proxy detection
* Bytecode inspection
* Interface detection

---

## defi.py

Purpose:

DeFi protocol abstraction.

Capabilities:

* DEX interaction
* Lending protocols
* Liquidity pools
* Yield farming
* Staking
* TVL references
* Position analysis

---

## bridge.py

Purpose:

Cross-chain intelligence.

Capabilities:

* Supported routes
* Cross-chain transfers
* Bridge monitoring
* Transfer status
* Message verification
* Chain mapping

---

# Cross-Cutting Responsibilities

Every blockchain module should support:

* Async execution
* Connection pooling
* Retry policies
* RPC failover
* Explorer fallback
* Structured logging
* Metrics
* Tracing
* Health checks

---

# Security Requirements

Every blockchain operation must include:

* Address validation
* Chain ID verification
* Replay protection awareness
* ABI validation
* Input sanitization
* RPC endpoint validation
* Rate limiting
* Secure secret handling

Private keys must never be stored inside this layer.

Signing must remain outside this module.

---

# Performance Goals

The Blockchain Layer should optimize:

* Parallel RPC calls
* Batch requests
* Connection reuse
* Response caching
* Block range optimization
* Lazy loading
* Event indexing
* Provider failover

---

# Observability

Every blockchain request should record:

* Request ID
* Chain ID
* Network
* Provider
* RPC Endpoint
* Explorer
* Block Number
* Latency
* Retry Count
* Result Status

---

# Integration Points

The Blockchain Layer integrates with:

* Planning Engine
* Tool Registry
* Tool Router
* Memory System
* Knowledge Engine
* AI Layer
* Reporting Engine
* Monitoring Layer

The Blockchain Layer should never contain business-specific investigation logic.

---

# Future Extensions

Planned capabilities:

* Solana Support
* Cosmos Ecosystem
* Bitcoin Support
* Starknet
* Sui
* Aptos
* Substrate Chains
* Layer-2 Native Features
* MEV Analysis
* Mempool Intelligence
* On-chain Simulation
* Intent-Based Execution
* Cross-chain Analytics

---

# Implementation Order

Recommended build sequence:

1. evm.py
2. ethereum.py
3. explorer.py
4. wallet.py
5. transaction.py
6. token.py
7. contract.py
8. nft.py
9. defi.py
10. bridge.py
11. **init**.py

---

# Module Status

Current Status:

* Architecture Defined
* Multi-chain Design Established
* Provider Independent
* Ready for Implementation
