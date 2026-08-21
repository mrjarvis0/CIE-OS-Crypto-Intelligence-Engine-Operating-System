# AI Layer

## Overview

The **AI Layer** is the intelligence abstraction layer of the Tools subsystem.

It provides a unified interface for all Artificial Intelligence capabilities used by the CIE-OS Agent.

The AI Layer is **model independent**, **provider independent**, and **modality independent**.

It hides every provider-specific implementation behind a common execution interface.

The Planning Engine should never know whether a request is handled by:

* OpenAI
* Anthropic
* Gemini
* Grok
* DeepSeek
* Mistral
* Ollama
* Local Models
* Vision Models
* Speech Models

The Planner only requests an AI capability.

The AI Layer decides how that capability is fulfilled.

---

# Mission

The AI Layer is responsible for:

* Large Language Models
* Embedding Models
* Vision Models
* Speech Models
* Translation
* Moderation
* Model Routing
* Provider Abstraction
* Streaming
* Token Accounting
* Context Management
* Model Selection
* AI Result Normalization

---

# Architecture

```text
                     Planner
                        │
                        ▼
                  Tool Manager
                        │
                        ▼
                    AI Layer
                        │
 ┌──────────┬──────────┬──────────┬──────────┐
 ▼          ▼          ▼          ▼
LLM     Embedding   Vision    Speech
 │          │          │          │
 ▼          ▼          ▼          ▼
Provider Provider  Provider  Provider
 │
 ▼
Unified AI Response
```

---

# Design Principles

The AI Layer follows:

* Provider Independence
* Model Independence
* Capability First
* Async First
* Streaming Support
* Fault Tolerance
* Retry Safe Operations
* Token Awareness
* Cost Awareness
* Observability

Business logic must never exist inside this layer.

---

# Directory Structure

```text
ai/
│
├── __init__.py        contract, error model, capability factories
├── providers.py       credentials, HTTP transport, registry, failover
├── llm.py
├── embedding.py
├── reranker.py
├── vision.py
├── speech.py
├── translation.py
└── moderation.py
```

---

# AI Request Lifecycle

```text
Planner Request
      │
      ▼
Capability Detection
      │
      ▼
Model Selection
      │
      ▼
Provider Selection
      │
      ▼
Context Preparation
      │
      ▼
AI Inference
      │
      ▼
Normalization
      │
      ▼
Usage Metrics
      │
      ▼
Unified Response
```

---

# File Responsibilities

## providers.py

Purpose:

Everything a real provider needs that is not specific to one capability.

Responsible for:

* Credential resolution (environment only; a key never enters a log or a repr)
* HTTP transport, delegated to `tools.adapters.rest.RESTAdapter`
* Error translation (`AdapterError` -> `AIError`)
* Streaming decode (Server-Sent Events and JSON-lines)
* Multipart encoding for file uploads
* Cost estimation from published list prices
* The capability -> provider registry
* `ProviderChain` failover

A provider module never imports `urllib`, and this module never learns what a
completion or an embedding is.

---

## llm.py

Purpose:

Unified interface for all language models.

Supports:

* Chat Completion
* Structured Output
* Tool Calling
* Streaming
* Function Calling
* JSON Mode
* Multi-turn Conversation
* Reasoning Models

Shipped providers:

| Name | Class | Endpoint | Notes |
|---|---|---|---|
| `anthropic` | `AnthropicLLM` | `/v1/messages` | tool use, vision, SSE; drops `temperature` on models that removed sampling |
| `openai` | `OpenAILLM` | `/v1/chat/completions` | `max_tokens` field name is configurable |
| `deepseek` | `DeepSeekLLM` | OpenAI-compatible | |
| `mistral` | `MistralLLM` | OpenAI-compatible | |
| `grok` | `GrokLLM` | OpenAI-compatible | no default model id |
| `ollama` | `OllamaLLM` | `/api/chat` | local daemon, no key, JSON-lines streaming |
| `local` | `LocalLLM` | none | deterministic, offline |

Any other OpenAI-compatible gateway (Groq, Together, a self-hosted proxy)
works by pointing `OpenAICompatibleLLM` at its `base_url`.

---

## embedding.py

Purpose:

Generate vector embeddings.

Used by:

* Memory
* RAG
* Vector Search
* Semantic Similarity
* Clustering
* Recommendation
* Knowledge Retrieval

Capabilities:

* Batch Embeddings
* Cache
* Normalization
* Multi-provider Support

Shipped providers: `openai`, `voyage`, `ollama`, `local`.

A remote batch is one request per `batch_size` chunk, cache hits never leave
the process, and a text repeated inside one batch is embedded once. A response
that returns fewer vectors than it was given inputs is an error, not a
silently misaligned store.

---

## reranker.py

Purpose:

Improve retrieval quality.

Use Cases:

* RAG
* Search
* Document Ranking
* Evidence Ranking
* Result Prioritization

Pipeline:

Retrieve

↓

Score

↓

Re-rank

↓

Return Best Results

Shipped providers: `cohere` (hosted cross-encoder), `llm` (the configured
language model scores the batch in one JSON call), `local` (lexical).

The whole candidate set is scored in one request. Scoring one document per
request would multiply latency by the size of the page a reranker exists to
improve.

---

## vision.py

Purpose:

Image understanding.

Capabilities:

* OCR
* Object Detection
* Scene Analysis
* Diagram Understanding
* Screenshot Analysis
* Chart Interpretation
* Document Understanding
* Multi-image Reasoning

Use Cases:

* Wallet Screenshots
* Blockchain Dashboards
* Token Charts
* Scam Detection
* KYC Documents

Shipped providers: `llm` (any multimodal model registered in the layer),
`local` (metadata only).

There is no per-vendor vision class: the image is an attachment on a normal
chat message, and each LLM provider already knows how to serialize one.
Format and dimensions are still read from the bytes locally -- they are facts
about the file, not something worth asking a model to guess.

---

## speech.py

Purpose:

Speech Intelligence.

Supports:

* Speech-To-Text
* Text-To-Speech
* Voice Activity Detection
* Speaker Recognition
* Streaming Audio

Use Cases:

* Voice Assistant
* Meeting Analysis
* Audio Investigation
* Voice Commands

Shipped providers: `openai` (multipart upload for transcription, binary
response for synthesis), `local` (energy VAD, beep TTS, stub STT).

Voice activity detection stays local even on the hosted provider: it is an RMS
over PCM frames, and a round trip would be slower, dearer and no more correct.

---

## translation.py

Purpose:

Language translation.

Supports:

* Text Translation
* Multi-language Response
* Language Detection
* Localization
* Terminology Preservation

Shipped providers: `deepl`, `llm`, `local`.

Terminology preservation is the `llm` provider's: a translation endpoint has
no field for "leave `USDC` alone", and an engine that translates a ticker has
produced confident nonsense. Remote engines detect the source language
themselves; the stopword guess is not sent to override them.

---

## moderation.py

Purpose:

AI Safety.

Responsible for:

* Prompt Safety
* Toxicity Detection
* PII Detection
* Malware Detection
* Jailbreak Detection
* Policy Enforcement
* Output Filtering

Shipped providers: `openai` (hosted classifier), `llm` (bespoke policy),
`local` (patterns).

A hosted classifier judges *content* -- toxicity, hate, sexual, violence --
and says nothing about PII, jailbreaks or prompt injection, which are the
three this agent most needs. Remote moderation therefore keeps running the
local patterns for those flags and merges both verdicts, so enabling a flag
always means something checked it. A vendor category the layer has no flag
name for is reported rather than dropped.

---

# Choosing a Provider

Provider choice is a deployment decision, not a code change. Callers ask for a
capability:

```python
from tools import ai

llm = ai.get_llm()                  # whatever the environment configures
llm = ai.get_llm("anthropic")       # or one by name
llm = ai.get_llm("openai", model="gpt-4.1-mini", timeout=30.0)

embedder  = ai.get_embedder()
reranker  = ai.get_reranker("cohere")
moderator = ai.get_moderator("openai")

ai.provider_catalog()               # every registered provider, by capability
```

Failover is explicit:

```python
llm = ai.get_chain("llm", ["anthropic", "openai", "local"])
```

The chain tries each provider in order and returns the first normalized
success; the serving provider's own metadata comes back, with a
`fallback_from` entry recording what it stepped over. A provider that cannot
be constructed (no credential, no model id) is skipped with a warning, because
the chain exists so that a deployment missing one key still runs. Credential
and validation failures are *not* retried on the next provider: the same
request fails the same way everywhere, and retrying only spends another
vendor's quota.

## Configuration

| Variable | Meaning |
|---|---|
| `A01_AI_PROVIDER` | default provider for every capability (matches `AISettings`) |
| `A01_AI_MODEL_NAME` | default model id for that provider |
| `A01_AI_<CAPABILITY>_PROVIDER` | per-capability override, e.g. `A01_AI_EMBEDDING_PROVIDER` |
| `A01_AI_<CAPABILITY>_MODEL` | per-capability model id |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, ... | vendor credentials |
| `A01_AI_<PROVIDER>_API_KEY` | deployment-local key override, checked first |
| `OLLAMA_HOST` | Ollama daemon address |

A configured model id is only applied to the *configured* provider. A model id
is not portable between vendors, and a failover that carried one across would
fail at the far end for a reason invisible from here.

## Registering another provider

```python
from tools.ai import register_provider
from tools.ai.llm import OpenAICompatibleLLM

class GroqLLM(OpenAICompatibleLLM):
    provider = "groq"
    base_url = "https://api.groq.com/openai"
    default_model = "llama-3.3-70b-versatile"

register_provider("llm", "groq", GroqLLM, description="Groq (OpenAI-compatible)")
```

---

# Cross-Cutting Responsibilities

Every AI module should support:

* Async Execution
* Streaming
* Retry Policies
* Timeout Handling
* Cost Tracking
* Token Tracking
* Logging
* Metrics
* Tracing
* Health Checks

---

# Security Requirements

The AI Layer must:

* Protect API Keys
* Prevent Prompt Injection
* Sanitize Inputs
* Validate Outputs
* Enforce Rate Limits
* Support Secret Management
* Apply Content Safety Policies

---

# Performance Goals

The AI Layer should optimize for:

* Low Latency
* Model Routing
* Provider Failover
* Response Streaming
* Context Caching
* Token Efficiency
* Batch Processing

---

# Observability

Every AI request should generate:

* Request ID
* Provider
* Model Name
* Latency
* Token Usage
* Cost Estimate
* Retry Count
* Success Status
* Error Category

---

# Integration Points

The AI Layer integrates with:

* Planning Engine
* Tool Registry
* Memory System
* RAG System
* Knowledge Engine
* Blockchain Intelligence
* Reporting Engine
* Monitoring Layer

The AI Layer should never contain domain-specific business logic.

---

# Future Extensions

Planned capabilities:

* Multi-LLM Routing
* Ensemble Inference
* Agent-to-Agent Models
* Video Understanding
* Audio Understanding
* Code Models
* Scientific Models
* Domain Expert Models
* On-device AI
* Edge AI

---

# Module Status

Current status:

* Architecture defined
* Capability boundaries established
* Provider independent
* All seven capabilities implemented, with a local implementation each
* Real provider clients shipped for every capability
* Registry, environment-driven selection and failover in place
* Covered by `tools/tests/test_ai.py` (local) and
  `tools/tests/test_ai_providers.py` (providers, no sockets)

## Known limits

* Cost estimates use published list prices for the models in
  `providers.PRICES`; anything unlisted reports `0.0` rather than a guess, and
  Anthropic prompt-cache discounts are not modelled (a cached call reads high).
* `json_mode` on providers without a native JSON mode is a system instruction
  plus a lenient parse, not a schema guarantee.
* Streaming yields text deltas; streamed tool-call arguments are not
  reassembled (a tool call is read from the non-streaming response).
* DeepL glossaries are not provisioned from here, so `preserve_terms` is
  honoured by the `llm` translator only.
* Speaker recognition has no hosted implementation; only the local stub
  answers that mode.
