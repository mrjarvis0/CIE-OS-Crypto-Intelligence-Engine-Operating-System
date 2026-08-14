"""
Tools :: Schemas Layer
======================

Canonical data contracts of the CIE-OS Tools Platform.

Every subsystem exchanges data through these structures instead of ad-hoc
dictionaries. The layer defines, in one place, the shape of tool requests,
responses, tool definitions, metadata, manifests, capabilities and registry
records. It never executes business logic -- it only describes data so that
core, discovery, routing, governance and lifecycle stay interoperable.
"""

from __future__ import annotations

from . import capability, manifest, metadata, registry, request, response, tool
from .capability import CAPABILITY, Capability, all_capabilities, capabilities_from
from .manifest import Checksum, Dependency, Manifest
from .metadata import ToolMetadata, metadata_dict
from .registry import RegistryEntry, RegistryStats
from .request import RequestContext, ToolRequest, new_request
from .response import ResponseMetadata, ToolResponse, failure, success
from .tool import ParameterSchema, ToolDefinition, ToolSchema, parameter

__all__ = [
    "Capability",
    "CAPABILITY",
    "all_capabilities",
    "capabilities_from",
    "Checksum",
    "Dependency",
    "Manifest",
    "ToolMetadata",
    "metadata_dict",
    "RegistryEntry",
    "RegistryStats",
    "RequestContext",
    "ToolRequest",
    "new_request",
    "ResponseMetadata",
    "ToolResponse",
    "success",
    "failure",
    "ParameterSchema",
    "ToolDefinition",
    "ToolSchema",
    "parameter",
]