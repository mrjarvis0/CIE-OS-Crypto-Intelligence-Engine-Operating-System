# Adapters Layer

## Overview

The **Adapters Layer** is the protocol translation and integration bridge of the Tools subsystem.

It enables the AI Agent to communicate with heterogeneous external systems through a unified internal interface without exposing protocol-specific implementation details to the Planning Engine or Tool Runtime.

The Adapter Layer follows the **Adapter Design Pattern**, where every external technology is wrapped behind a common execution contract.

The Planning Engine never communicates directly with REST APIs, RPC nodes, MCP servers, Docker containers, CLI programs, WebSocket services, or gRPC endpoints.

Instead, every interaction passes through an appropriate adapter.

---

# Mission

The primary mission of the Adapter Layer is to provide:

* Protocol abstraction
* Uniform execution interface
* Request normalization
* Response normalization
* Error translation
* Authentication handling
* Retry management
* Timeout management
* Streaming abstraction
* Transport independence

The Adapter Layer should never contain business logic.

---

# Why Adapters Exist

Without adapters:

```text
Planner
   │
   ├── REST API
   ├── RPC
   ├── MCP
   ├── CLI
   ├── Docker
   ├── WebSocket
   ├── gRPC
   └── Python Functions
```

Every module would need to understand every protocol.

With adapters:

```text
Planner
    │
    ▼
Tool Manager
    │
    ▼
Adapter Layer
    │
 ┌──┼────┬────┬────┬────┬────┐
 ▼  ▼    ▼    ▼    ▼    ▼
REST RPC MCP CLI Docker WS gRPC
```

This keeps the Planning Engine protocol-agnostic and allows transport implementations to evolve independently.

---

# Architecture

```text
                        Planner
                           │
                           ▼
                    Tool Manager
                           │
                           ▼
                     Tool Executor
                           │
                           ▼
                    Adapter Manager
                           │
      ┌────────────────────┼────────────────────┐
      ▼                    ▼                    ▼
 REST Adapter         RPC Adapter         MCP Adapter
      │                    │                    │
      ▼                    ▼                    ▼
 External API        Blockchain RPC      MCP Server
```

---

# Design Principles

Every adapter must follow:

* Single Responsibility
* Open/Closed Principle
* Transport Isolation
* Stateless Design
* Retry Safe Operations
* Typed Interfaces
* Structured Errors
* Observable Execution
* Async First
* Thread Safe Behavior

---

# Directory Structure

```text
adapters/
│
├── __init__.py
├── python.py
├── rest.py
├── rpc.py
├── grpc.py
├── websocket.py
├── mcp.py
├── cli.py
├── docker.py
└── subprocess.py
```

---

# Adapter Lifecycle

Every adapter follows the same lifecycle.

```text
Tool Request
      │
      ▼
Input Validation
      │
      ▼
Authentication
      │
      ▼
Connection
      │
      ▼
Request Conversion
      │
      ▼
Transport Execution
      │
      ▼
Response Parsing
      │
      ▼
Normalization
      │
      ▼
Structured Result
      │
      ▼
Return to Tool Manager
```

---

# Adapter Contract

Every adapter should expose a consistent interface.

Required capabilities:

* connect()
* execute()
* stream()
* health_check()
* validate_request()
* normalize_response()
* close()

The Tool Manager should be able to switch adapters without changing Planner logic.

---

# File Responsibilities

## python.py

Purpose:

Execute local Python callables safely.

Typical use cases:

* Internal utilities
* AI pipelines
* Data processing
* Mathematical operations
* Local algorithms

---

## rest.py

Responsible for HTTP-based APIs.

Supports:

* GET
* POST
* PUT
* PATCH
* DELETE

Features:

* Headers
* Authentication
* Retry
* Rate limiting
* Pagination
* Streaming
* JSON parsing

---

## rpc.py

Responsible for Remote Procedure Call protocols.

Primary use cases:

* Ethereum JSON-RPC
* Blockchain nodes
* Internal RPC services

Capabilities:

* Batch requests
* Connection pooling
* Retry
* Endpoint failover

---

## grpc.py

Responsible for gRPC services.

Supports:

* Unary
* Streaming
* Bidirectional streaming

Use cases:

* High-performance microservices
* Internal enterprise APIs

---

## websocket.py

Responsible for persistent real-time communication.

Supports:

* Live subscriptions
* Event streams
* Real-time blockchain feeds
* Live market data

Features:

* Auto reconnect
* Heartbeat
* Subscription recovery
* Message buffering

---

## mcp.py

Responsible for Model Context Protocol servers.

Capabilities:

* Tool discovery
* Resource discovery
* Prompt discovery
* Tool execution
* Session management
* Capability negotiation

The MCP adapter enables integration with standardized AI tool ecosystems.

---

## cli.py

Executes trusted command-line applications.

Use cases:

* Git
* Docker CLI
* FFmpeg
* Foundry
* Hardhat
* Security scanners

Features:

* Sandboxed execution
* Output capture
* Timeout handling

---

## docker.py

Responsible for container execution.

Supports:

* Container startup
* Container shutdown
* Resource limits
* Volume mounts
* Network isolation

Ideal for executing untrusted or isolated tools.

---

## subprocess.py

Executes external programs.

Capabilities:

* Process creation
* Environment variables
* Signal handling
* Exit code processing
* Output streaming

---

# Cross-Cutting Responsibilities

Every adapter should provide:

* Structured logging
* Metrics
* Tracing
* Timeouts
* Retry policies
* Cancellation support
* Error normalization
* Health checks

---

# Security Requirements

Every adapter must support:

* Authentication
* Authorization
* TLS where applicable
* Secret management
* Input validation
* Output sanitization
* Least-privilege execution
* Audit logging

Adapters must never expose secrets to higher layers.

---

# Error Model

Transport-specific failures should never leak upward.

Instead they should be translated into a unified error model.

Examples:

* ConnectionError
* AuthenticationError
* AuthorizationError
* TimeoutError
* ValidationError
* TransportError
* ExecutionError
* RetryableError
* FatalError

---

# Performance Goals

The Adapter Layer should prioritize:

* Connection reuse
* Async I/O
* Request batching
* Streaming support
* Low latency
* Efficient serialization
* Backpressure handling
* Resource cleanup

---

# Observability

Every adapter execution should produce:

* Request ID
* Correlation ID
* Execution Time
* Retry Count
* Status
* Error Code
* Resource Usage
* Transport Type

---

# Integration Points

The Adapter Layer integrates with:

* Planning Engine
* Tool Registry
* Tool Executor
* Security Layer
* Monitoring System
* Logging System
* Blockchain Tools
* Web Tools
* AI Tools

It should never depend directly on business-domain modules.

---

# Future Extensions

Planned capabilities include:

* GraphQL Adapter
* Kafka Adapter
* AMQP Adapter
* MQTT Adapter
* OPC-UA Adapter
* S3/Object Storage Adapter
* SQL Adapter
* NoSQL Adapter
* Browser Automation Adapter
* Edge Device Adapter

---

# Implementation Order

Recommended development sequence:

1. python.py
2. rest.py
3. rpc.py
4. websocket.py
5. mcp.py
6. grpc.py
7. cli.py
8. subprocess.py
9. docker.py
10. **init**.py

---

# Module Status

Current Status:

* Architecture Defined
* Protocol Boundaries Established
* Ready for Implementation
