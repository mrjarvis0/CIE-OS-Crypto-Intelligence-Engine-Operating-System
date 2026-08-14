"""
Tools :: Core
==============

The runtime core of the tools layer.

Everything the calling layer needs to own a tool runtime in one place:

* :class:`~.tool.Tool` -- the abstract contract every implementation fills.
* :class:`~.registry.ToolRegistry` -- the authoritative tool index.
* :class:`~.executor.Executor` / :class:`~.manager.ToolManager` -- dispatch.
* :class:`~.result.ToolResult` -- the normalized outcome contract.
* :class:`~.context.ToolContext` -- structured runtime context.
* :class:`~.lifecycle.LifecycleMachine` -- per-tool state transitions.
* :class:`~.capability.CapabilitySet` -- coarse-grained routing vocabulary.
* :class:`~.permissions.ToolPermissionMap` -- executor-side authorization.
* :class:`~.metadata.MetadataStore` -- live metadata index.
* :class:`~.manifest.Manifest` -- workload manifests for loading.
* :class:`~.dependency.DependencyGraph` -- load-order resolution.
* :class:`~.loader.ToolLoader` -- declarative population of the registry.
* :class:`~.cache.ExecutionCache` -- result/TTL caching for the executor.
* :class:`~.version.Version` -- semantic-version helpers for tooling.

Sub-packages ``exceptions``, ``tool``, ``result``, ``context``, ``lifecycle``,
``metadata``, ``manifest``, ``dependency``, ``capability``, ``permissions``,
``registry``, ``loader``, ``cache`` and ``executor``/``manager`` implement the
details. The environment historically shipped this package as a de-facto JSON
API; the modern, package-level interface is what is exported here.
"""

from __future__ import annotations

from .exceptions import (
    ToolError,
    ToolNotFoundError,
    ToolNotEnabledError,
    PermissionDeniedError,
    ValidationError,
    ExecutionError,
    DependencyError,
    VersionError,
    TimeoutError,
    ConfigurationError,
    TransportError,
    LifecycleError,
    CircuitOpenError,
)
from .version import Version, parse_version, version, is_compatible, best_compatible, version_key
from .tool import Tool, ToolConfig, AbstractTool
from .result import ToolResult, build_result, Usage, TraceInfo
from .context import ToolContext, new_context
from .lifecycle import LifecycleMachine, ALL_STATES
from .metadata import MetadataStore, ToolMetadata
from .manifest import Manifest, build_manifest
from .dependency import DependencyGraph
from .capability import CapabilityId, CapabilitySet, resolve_capabilities, CAPABILITY
from .permissions import ToolPermissionMap, ActionSet
from .registry import ToolRegistry
from .loader import ToolLoader, CallableTool
from .cache import ExecutionCache, InFlightGuard
from .executor import Executor, ExecutionPolicy
from .manager import ToolManager
from .dependency import DependencyNode, DependencySpec
from .manifest import ManifestItem
from .lifecycle import ToolState, Transition

__all__ = [
    # exceptions
    "ToolError",
    "ToolNotFoundError",
    "ToolNotEnabledError",
    "PermissionDeniedError",
    "ValidationError",
    "ExecutionError",
    "DependencyError",
    "VersionError",
    "TimeoutError",
    "ConfigurationError",
    "TransportError",
    "LifecycleError",
    "CircuitOpenError",
    # versioning
    "Version",
    "parse_version",
    "version",
    "is_compatible",
    "best_compatible",
    "version_key",
    # tool
    "Tool",
    "ToolConfig",
    "AbstractTool",
    # result / context / lifecycle
    "ToolResult",
    "build_result",
    "Usage",
    "TraceInfo",
    "ToolContext",
    "new_context",
    "LifecycleMachine",
    "ALL_STATES",
    # metadata / manifest / dependency
    "ToolMetadata",
    "MetadataStore",
    "Manifest",
    "build_manifest",
    "ManifestItem",
    "DependencyGraph",
    "DependencyNode",
    "DependencySpec",
    # lifecycle machine internals
    "ToolState",
    "Transition",
    # capability / permissions
    "CapabilityId",
    "CapabilitySet",
    "resolve_capabilities",
    "CAPABILITY",
    "ToolPermissionMap",
    "ActionSet",
    # registry / loader / cache / executor / manager
    "ToolRegistry",
    "ToolLoader",
    "CallableTool",
    "ExecutionCache",
    "InFlightGuard",
    "Executor",
    "ExecutionPolicy",
    "ToolManager",
]