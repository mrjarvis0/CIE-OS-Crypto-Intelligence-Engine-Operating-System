# Planning Engine

## Overview

The **Planning Engine** is the cognitive orchestration layer of the A01 Blockchain Intelligence Agent.

It transforms user goals into structured execution plans, decomposes complex objectives into executable tasks, coordinates tool usage, manages execution flow, validates intermediate results, performs self-reflection, and dynamically replans when necessary.

Unlike a traditional task scheduler, this planning system is designed as an autonomous decision-making framework capable of coordinating multiple internal modules and external tools while maintaining execution state, checkpoints, and recovery information.

---

# Core Responsibilities

The Planning Engine is responsible for:

* Goal interpretation
* Objective management
* Constraint analysis
* Task decomposition
* Dependency resolution
* Planning strategies
* Tool routing
* Agent routing
* Workflow orchestration
* Task scheduling
* Parallel execution planning
* Sequential execution planning
* Runtime coordination
* Validation
* Reflection
* Replanning
* Retry policies
* Checkpoint management
* Progress monitoring
* Metrics collection

---

# High-Level Architecture

```text
                User Request
                      │
                      ▼
              Goal Interpreter
                      │
                      ▼
            Constraint Analyzer
                      │
                      ▼
            Objective Generator
                      │
                      ▼
             Task Decomposer
                      │
                      ▼
              Dependency Graph
                      │
                      ▼
             Planning Strategy
                      │
                      ▼
              Tool Selection
                      │
                      ▼
              Execution Plan
                      │
                      ▼
                 Executor
                      │
                      ▼
                 Validator
                      │
                      ▼
             Reflection Engine
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
     Success                 Replanner
```

---

# Directory Structure

```text
planning/
│
├── README.md
├── __init__.py
│
├── core/          # context, planner, dispatcher, executor, lifecycle,
│                  # coordinator, orchestrator, runtime
├── goals/         # goal, objective, constraints, assumptions, success
├── tasks/         # tasks, task_graph, dependency, decomposition,
│                  # prioritizer, scheduler, workflow, planner_state
├── routing/       # strategy, policy, router, selector
├── execution/     # state_machine, executor, runners, checkpoint, recovery
├── reasoning/     # critic, evaluator, reflection, replanner, retry,
│                  # validator, verifier
├── monitoring/    # events, metrics, tracing, timeline, progress, diagnostics
├── schemas/       # base, goal, task, plan, state, execution
├── utils/         # constants, helpers, serialization, hashing, ids,
│                  # timers, validation, graph, decorators
└── tests/         # per-module test scripts (utils, schemas, goals, tasks,
                   # routing, execution, reasoning, monitoring, core)
```

---

# Module Overview

## core/

Contains the central planning engine.

Responsibilities:

* Planner lifecycle
* Runtime management
* Global planning state
* Coordination
* Dispatching
* Orchestration
* Configuration

Main files:

```
context.py planner.py dispatcher.py executor.py lifecycle.py
coordinator.py orchestrator.py runtime.py
```

---

## goals/

Responsible for transforming user intent into structured planning goals.

Includes:

* Goal
* Objective
* Constraints
* Priorities
* Success Criteria
* Assumptions

---

## tasks/

Responsible for generating executable work.

Includes:

* Task creation
* Task graph
* Dependency graph
* Workflow generation
* Scheduling
* Queue management
* Checkpoints

---

## routing/

Responsible for deciding **what should execute each task**.

Includes:

* Tool routing
* Agent routing
* Strategy selection
* Model selection
* Chain selection
* Fallback logic

---

## execution/

Responsible for executing plans.

Supports:

* Sequential execution
* Parallel execution
* Async execution
* Rollback
* Recovery
* Sandbox execution

---

## reasoning/

Responsible for improving execution quality.

Includes:

* Reflection
* Self-critique
* Validation
* Verification
* Retry
* Replanning
* Confidence estimation

---

## monitoring/

Responsible for observing planner health.

Tracks:

* Progress
* Timeline
* Diagnostics
* Metrics
* Profiling
* Events
* Health

---

## schemas/

Contains shared data models.

Examples:

* Goal Schema
* Task Schema
* Plan Schema
* Execution Schema
* Workflow Schema

---

## utils/

Shared utilities.

Examples:

* Graph utilities
* Hashing
* IDs
* Validation
* Serialization
* Timers
* Decorators

---

# Planning Lifecycle

```
Goal
  ↓
Planning
  ↓
Task Decomposition
  ↓
Dependency Resolution
  ↓
Routing
  ↓
Scheduling
  ↓
Execution
  ↓
Validation
  ↓
Reflection
  ↓
Retry / Replan
  ↓
Completion
```

---

# Planning Strategies

The Planning Engine supports multiple planning strategies:

* Rule-Based Planning
* Hierarchical Planning
* Goal-Oriented Planning
* Dynamic Planning
* Reactive Planning
* Workflow Planning
* Parallel Planning
* Multi-Agent Planning

---

# Integration Points

The planner communicates with:

* Memory System
* Blockchain Intelligence Layer
* Tool Framework
* Knowledge Base
* Retrieval Engine
* Reporting Engine
* Monitoring System

The planner never performs blockchain analysis directly. Instead, it orchestrates specialized components responsible for those capabilities.

---

# Design Principles

The Planning Engine follows these principles:

* Modular architecture
* Separation of concerns
* Deterministic execution
* Pluggable strategies
* Event-driven coordination
* Fault tolerance
* Checkpoint recovery
* Scalable orchestration
* Observable runtime
* Extensible interfaces

---

# Future Extensions

The architecture is designed to support future capabilities such as:

* Multi-agent collaboration
* Distributed planning
* Long-running workflows
* Human-in-the-loop approvals
* Autonomous optimization
* Adaptive strategy selection
* Learning-based planning
* Cloud-native execution

---

# Development Roadmap

Recommended implementation order:

1. README
2. core/
3. goals/
4. tasks/
5. routing/
6. execution/
7. reasoning/
8. monitoring/
9. schemas/
10. utils/
11. tests/

This order was followed; Phases 0-10 are complete.

---

# Current Status

Planning Engine Status:

* Architecture Defined
* Folder Structure Finalized
* Implementation Complete (Phases 0-10)
* Tested (352 assertions passing)

## Implemented modules

| Subpackage  | Status | Modules |
| ----------- | ------ | ------- |
| `utils/`    | done   | constants, helpers, serialization, hashing, ids, timers, validation, graph, decorators |
| `schemas/`  | done   | base, goal, task, plan, state, execution |
| `goals/`    | done   | goal, objective, assumptions, constraints, success |
| `tasks/`    | done   | task, task_graph, dependency, decomposition, prioritizer, scheduler, workflow, planner_state |
| `routing/`  | done   | strategy, policy, router, selector |
| `execution/`| done   | state_machine, executor, runners, checkpoint, recovery |
| `reasoning/`| done   | critic, evaluator, reflection, replanner, retry, validator, verifier |
| `monitoring/`| done  | events, metrics, tracing, timeline, progress, diagnostics |
| `core/`     | done   | context, planner, dispatcher, executor, lifecycle, coordinator, orchestrator, runtime |
| `tests/`    | done   | test_utils, test_schemas, test_goals, test_tasks, test_routing, test_execution, test_reasoning, test_monitoring, test_core |

## Test suite

Each `test_*.py` runs as a plain Python script (stdlib only) from the
`planning/` package root; the suite is executed as:

```text
python planning/tests/test_utils.py
python planning/tests/test_schemas.py
python planning/tests/test_goals.py
python planning/tests/test_tasks.py
python planning/tests/test_routing.py
python planning/tests/test_execution.py
python planning/tests/test_reasoning.py
python planning/tests/test_monitoring.py
python planning/tests/test_core.py
```

The `integrations/` subpackage from the original design was
intentionally dropped; integration with the rest of the agent happens
through the `planning.core` runtime entry point instead.

---

# License

This Planning Engine is part of the CIE-OS (Cognitive Intelligence Engine Operating System) architecture and is intended to serve as the orchestration layer for autonomous blockchain intelligence agents.
