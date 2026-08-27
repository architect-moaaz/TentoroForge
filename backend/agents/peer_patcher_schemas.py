"""Pydantic shapes for the writeArtifacts LLM tool.

Mirrors @forge/patches Artifacts type for round-trip compatibility.
The JSON Schema export from these models is fed to Claude as the
input_schema for a single 'writeArtifacts' tool call.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field

from contracts.nav_flow import NavFlow


class SchemaNode(BaseModel):
    """One node in a page schema tree. Recursive via children + slots."""
    id: str
    type: str
    props: dict[str, Any] = Field(default_factory=dict)
    children: list["SchemaNode"] = Field(default_factory=list)
    slots: dict[str, list["SchemaNode"]] = Field(default_factory=dict)
    visibleIf: Optional[str] = None


class PageSchema(BaseModel):
    """One page in the artifact set."""
    schemaVersion: str = "2"
    id: str
    route: Optional[str] = None
    layout: Optional[str] = None
    meta: dict = Field(default_factory=dict)
    dataSources: list[dict] = Field(default_factory=list)
    root: SchemaNode


class Tokens(BaseModel):
    """Design tokens artifact."""
    color: dict = Field(default_factory=dict)
    typography: dict = Field(default_factory=dict)
    spacing: dict = Field(default_factory=dict)
    radius: dict = Field(default_factory=dict)
    shadow: dict = Field(default_factory=dict)
    motion: dict = Field(default_factory=dict)
    breakpoints: dict = Field(default_factory=dict)


class Artifacts(BaseModel):
    """The full artifact bundle the LLM produces in one tool call.

    pageSchemas is a map keyed by page id (Tentoro convention: N files
    on disk, one per page). The peer_patcher writes each entry to
    src/schemas/<pageId>.json post-commit.
    """
    pageSchemas: dict[str, PageSchema]
    navFlow: NavFlow
    tokens: Tokens


def artifacts_json_schema() -> dict:
    """Used as the writeArtifacts tool's input_schema."""
    schema = Artifacts.model_json_schema()
    # Inline $ref-resolution for cleaner LLM consumption (Claude tools
    # support $ref but inlining shrinks the system-prompt footprint).
    # For v1, leave $defs intact — the LLM handles standard JSON Schema.
    return schema
