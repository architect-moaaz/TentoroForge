"""Shape profile — the four-axis substrate for intelligent+rich Forge.

Reads vocabularies from ``backend/{shapes,archetypes,runtime}/*.json`` and
provides pure, testable types + parsers + validators the planner and every
downstream stage share. See docs/superpowers/specs/2026-08-11-intelligent-rich-forge.md.

This module owns:

- **Types** — ShapeProfile, ArchetypeInstance, CoverageVerdict, and slice
  dataclasses. All dicts-in / dicts-out at the boundary; typed structs
  inside.
- **Vocabulary loaders** — cached JSON reads with a single source of truth
  per primitive value set.
- **Validators** — pure functions returning ``list[Finding]``. Same shape
  as plan_completeness_validator's Violation, kept separate so this
  module has no upstream dependencies.
- **Fallback detectors** — safe conservative defaults for the "LLM output
  invalid AND no signal" case. Never authors on the hot path; only fills
  when the LLM output is unusable.

Not owned here: the planner prompt (planner.py), the pipeline gate
(coverage_verdict_gate.py in M2), the downstream stage integrations
(various files in M3/M4).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal


# ══════════════════════════════════════════════════════════════════
# Paths
# ══════════════════════════════════════════════════════════════════

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SHAPES_DIR = _BACKEND_ROOT / "shapes"
_ARCHETYPES_DIR = _BACKEND_ROOT / "archetypes"
_RUNTIME_DIR = _BACKEND_ROOT / "runtime"


# ══════════════════════════════════════════════════════════════════
# Types — dataclasses for parsed profiles
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LayoutSlice:
    shell: str
    hero: str
    primaryInteraction: str
    density: str


@dataclass(frozen=True)
class AuthSlice:
    surface: str
    gating: str


@dataclass(frozen=True)
class NavSlice:
    menu: str
    back: str


@dataclass(frozen=True)
class WorkflowSlice:
    executionMode: str


@dataclass(frozen=True)
class DataSlice:
    readShape: str
    denormalization: str


@dataclass(frozen=True)
class IdentitySlice:
    usageMode: str


@dataclass(frozen=True)
class ShapeProfile:
    """Full outer shape of an app. Every primitive is required and
    validated against ``shapes/vocabulary.json``. See spec P1."""
    layout: LayoutSlice
    auth: AuthSlice
    nav: NavSlice
    workflows: WorkflowSlice
    data: DataSlice
    identity: IdentitySlice
    label: str | None = None  # optional human descriptor; pipeline never reads


@dataclass(frozen=True)
class ReadSlice:
    pattern: str
    grouping: str = "none"


@dataclass(frozen=True)
class WriteSlice:
    pattern: str
    integrity: str = "direct"


@dataclass(frozen=True)
class PresSlice:
    itemShape: str


@dataclass(frozen=True)
class StateSlice:
    realtime: str


@dataclass(frozen=True)
class Capabilities:
    read: ReadSlice
    write: WriteSlice
    interactions: tuple[str, ...]
    presentation: PresSlice
    state: StateSlice


@dataclass(frozen=True)
class ArchetypeInstance:
    """One module within an app. Uses either a recipe (from
    ``archetypes/recipes.json``) OR composed capabilities OR both."""
    name: str
    entities: tuple[str, ...]
    routes: tuple[str, ...]
    recipe: str | None = None
    capabilities: Capabilities | None = None
    local_shape: dict[str, Any] | None = None  # partial override
    label: str | None = None


@dataclass(frozen=True)
class CoverageVerdict:
    """Planner's honest assessment of whether the brief fits the
    substrate. See spec P1 "Coverage verdicts" subsection."""
    status: Literal["in_scope", "extension_needed", "out_of_scope"]
    reason: str
    missing_dimensions: tuple[str, ...] = ()
    suggested_extensions: tuple[str, ...] = ()
    nearest_supported: str | None = None


# ══════════════════════════════════════════════════════════════════
# Findings — same shape as plan_completeness_validator.Violation but
# kept separate so this module has no dependency on that file.
# ══════════════════════════════════════════════════════════════════


@dataclass
class Finding:
    """A single validation problem. Fields deliberately named to match
    the Violation contract elsewhere in the codebase so callers can
    interop without a converter."""
    rule: str
    message: str
    severity: Literal["error", "warning", "info"] = "error"
    axis: str = ""  # "app_shape" | "archetypes" | "runtime_context" | "coverage_verdict"


# ══════════════════════════════════════════════════════════════════
# Vocabulary loaders — cached per-process reads
# ══════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _shapes_vocabulary() -> dict[str, Any]:
    return _read_json(_SHAPES_DIR / "vocabulary.json")


@lru_cache(maxsize=1)
def _capability_vocabulary() -> dict[str, Any]:
    return _read_json(_ARCHETYPES_DIR / "capability_vocabulary.json")


@lru_cache(maxsize=1)
def _recipes() -> dict[str, Any]:
    return _read_json(_ARCHETYPES_DIR / "recipes.json")


@lru_cache(maxsize=1)
def _signature_moves() -> dict[str, Any]:
    return _read_json(_ARCHETYPES_DIR / "signature_moves.json")


@lru_cache(maxsize=1)
def _context_vocabulary() -> dict[str, Any]:
    return _read_json(_RUNTIME_DIR / "context_vocabulary.json")


@lru_cache(maxsize=1)
def _reference_apps() -> dict[str, Any]:
    return _read_json(_SHAPES_DIR / "reference_apps.json")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"vocabulary file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def clear_vocabulary_cache() -> None:
    """Test hook — reset cached JSON reads. Production code never calls."""
    for fn in (
        _shapes_vocabulary,
        _capability_vocabulary,
        _recipes,
        _signature_moves,
        _context_vocabulary,
        _reference_apps,
    ):
        fn.cache_clear()


def shape_primitive_values(primitive: str) -> tuple[str, ...]:
    """Return the closed value set for a shape primitive
    (e.g. ``"layout.shell"``)."""
    prims = _shapes_vocabulary()["primitives"]
    if primitive not in prims:
        raise KeyError(f"unknown shape primitive: {primitive}")
    return tuple(prims[primitive]["values"])


def capability_primitive_values(primitive: str) -> tuple[str, ...]:
    prims = _capability_vocabulary()["primitives"]
    if primitive not in prims:
        raise KeyError(f"unknown capability primitive: {primitive}")
    return tuple(prims[primitive]["values"])


def runtime_capabilities() -> tuple[str, ...]:
    return tuple(_context_vocabulary()["capabilities"].keys())


def known_recipes() -> tuple[str, ...]:
    return tuple(_recipes()["recipes"].keys())


def recipe_capabilities(recipe: str) -> Capabilities | None:
    entry = _recipes()["recipes"].get(recipe)
    if entry is None:
        return None
    return _parse_capabilities(entry["capabilities"])


# ══════════════════════════════════════════════════════════════════
# Parsers — dict → typed
# ══════════════════════════════════════════════════════════════════


def parse_shape_profile(raw: dict[str, Any]) -> ShapeProfile:
    """Parse a raw dict into ShapeProfile. Raises KeyError on missing
    fields — callers should validate first with :func:`validate_shape_profile`
    to get structured findings instead."""
    return ShapeProfile(
        layout=LayoutSlice(**raw["layout"]),
        auth=AuthSlice(**raw["auth"]),
        nav=NavSlice(**raw["nav"]),
        workflows=WorkflowSlice(**raw["workflows"]),
        data=DataSlice(**raw["data"]),
        identity=IdentitySlice(**raw["identity"]),
        label=raw.get("label"),
    )


def _parse_capabilities(raw: dict[str, Any]) -> Capabilities:
    return Capabilities(
        read=ReadSlice(**raw["read"]),
        write=WriteSlice(**raw["write"]),
        interactions=tuple(raw.get("interactions", [])),
        presentation=PresSlice(**raw["presentation"]),
        state=StateSlice(**raw["state"]),
    )


def parse_archetype_instance(raw: dict[str, Any]) -> ArchetypeInstance:
    caps = _parse_capabilities(raw["capabilities"]) if raw.get("capabilities") else None
    return ArchetypeInstance(
        name=raw["name"],
        entities=tuple(raw.get("entities", [])),
        routes=tuple(raw.get("routes", [])),
        recipe=raw.get("recipe"),
        capabilities=caps,
        local_shape=raw.get("local_shape"),
        label=raw.get("label"),
    )


def parse_coverage_verdict(raw: dict[str, Any]) -> CoverageVerdict:
    return CoverageVerdict(
        status=raw["status"],
        reason=raw["reason"],
        missing_dimensions=tuple(raw.get("missing_dimensions", [])),
        suggested_extensions=tuple(raw.get("suggested_extensions", [])),
        nearest_supported=raw.get("nearest_supported"),
    )


# ══════════════════════════════════════════════════════════════════
# Validators — IRF-M1-T2 / T3 / T4 / T5
# All return list[Finding]. Never raise on invalid values; that's the
# caller's decision.
# ══════════════════════════════════════════════════════════════════


def validate_shape_profile(raw: dict[str, Any] | None) -> list[Finding]:
    """IRF-M1-T2. Validate every primitive in ``plan.app_shape`` against
    ``shapes/vocabulary.json``. Missing slices, missing fields, out-of-set
    values all surface as ``error`` findings."""
    findings: list[Finding] = []
    if raw is None:
        findings.append(Finding(
            rule="shape_profile.missing",
            message="plan.app_shape is required but missing",
            severity="error",
            axis="app_shape",
        ))
        return findings

    required = {
        "layout": {"shell", "hero", "primaryInteraction", "density"},
        "auth": {"surface", "gating"},
        "nav": {"menu", "back"},
        "workflows": {"executionMode"},
        "data": {"readShape", "denormalization"},
        "identity": {"usageMode"},
    }
    for slice_name, fields in required.items():
        section = raw.get(slice_name)
        if not isinstance(section, dict):
            findings.append(Finding(
                rule=f"shape_profile.{slice_name}.missing",
                message=f"plan.app_shape.{slice_name} is required",
                axis="app_shape",
            ))
            continue
        for field_name in fields:
            value = section.get(field_name)
            primitive = f"{slice_name}.{field_name}"
            if value is None:
                findings.append(Finding(
                    rule=f"shape_profile.{primitive}.missing",
                    message=f"plan.app_shape.{primitive} is required",
                    axis="app_shape",
                ))
                continue
            allowed = shape_primitive_values(primitive)
            if value not in allowed:
                findings.append(Finding(
                    rule=f"shape_profile.{primitive}.invalid_value",
                    message=(
                        f"plan.app_shape.{primitive} = {value!r} is not one of "
                        f"{list(allowed)}"
                    ),
                    axis="app_shape",
                ))
    return findings


def validate_archetypes(raw: list[dict[str, Any]] | None) -> list[Finding]:
    """IRF-M1-T3. Validate ``plan.archetypes``: at least one entry; each
    entry has a name; each has either recipe (from recipes.json) or
    capabilities (from vocabulary) — or both."""
    findings: list[Finding] = []
    if not raw:
        findings.append(Finding(
            rule="archetypes.missing",
            message="plan.archetypes must contain at least one ArchetypeInstance",
            axis="archetypes",
        ))
        return findings

    if not isinstance(raw, list):
        findings.append(Finding(
            rule="archetypes.wrong_type",
            message=f"plan.archetypes must be a list; got {type(raw).__name__}",
            axis="archetypes",
        ))
        return findings

    valid_recipes = set(known_recipes())
    seen_names: set[str] = set()
    for idx, instance in enumerate(raw):
        prefix = f"archetypes[{idx}]"
        if not isinstance(instance, dict):
            findings.append(Finding(
                rule=f"{prefix}.wrong_type",
                message=f"{prefix} must be an object",
                axis="archetypes",
            ))
            continue
        name = instance.get("name")
        if not name or not isinstance(name, str):
            findings.append(Finding(
                rule=f"{prefix}.name_missing",
                message=f"{prefix}.name is required",
                axis="archetypes",
            ))
        else:
            if name in seen_names:
                findings.append(Finding(
                    rule=f"{prefix}.name_duplicate",
                    message=f"archetype name {name!r} appears more than once",
                    axis="archetypes",
                ))
            seen_names.add(name)

        recipe = instance.get("recipe")
        caps = instance.get("capabilities")
        if not recipe and not caps:
            findings.append(Finding(
                rule=f"{prefix}.recipe_or_capabilities_required",
                message=(
                    f"{prefix} must set 'recipe' (from recipes.json) or "
                    "'capabilities' (composed primitives) or both"
                ),
                axis="archetypes",
            ))
        if recipe and recipe not in valid_recipes:
            findings.append(Finding(
                rule=f"{prefix}.recipe_unknown",
                message=(
                    f"{prefix}.recipe = {recipe!r} is not in recipes.json. "
                    f"Known: {sorted(valid_recipes)}"
                ),
                axis="archetypes",
            ))
        if caps:
            findings.extend(_validate_capabilities(caps, prefix))
    return findings


def _validate_capabilities(raw: dict[str, Any], prefix: str) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(raw, dict):
        return [Finding(
            rule=f"{prefix}.capabilities.wrong_type",
            message=f"{prefix}.capabilities must be an object",
            axis="archetypes",
        )]

    def _check(section: str, field_name: str, primitive: str, *, multi: bool = False, optional: bool = False) -> None:
        section_val = raw.get(section)
        if not isinstance(section_val, dict):
            findings.append(Finding(
                rule=f"{prefix}.capabilities.{section}.missing",
                message=f"{prefix}.capabilities.{section} required",
                axis="archetypes",
            ))
            return
        value = section_val.get(field_name)
        if value is None:
            if optional:
                return  # dataclass supplies a default; absent is fine
            findings.append(Finding(
                rule=f"{prefix}.capabilities.{section}.{field_name}.missing",
                message=f"{prefix}.capabilities.{section}.{field_name} required",
                axis="archetypes",
            ))
            return
        allowed = capability_primitive_values(primitive)
        if multi:
            if not isinstance(value, list):
                findings.append(Finding(
                    rule=f"{prefix}.capabilities.{section}.wrong_type",
                    message=f"{prefix}.capabilities.{section} must be a list",
                    axis="archetypes",
                ))
                return
            for item in value:
                if item not in allowed:
                    findings.append(Finding(
                        rule=f"{prefix}.capabilities.{section}.invalid_value",
                        message=(
                            f"{prefix}.capabilities.{section} contains "
                            f"{item!r} which is not in {list(allowed)}"
                        ),
                        axis="archetypes",
                    ))
        else:
            if value not in allowed:
                findings.append(Finding(
                    rule=f"{prefix}.capabilities.{section}.{field_name}.invalid_value",
                    message=(
                        f"{prefix}.capabilities.{section}.{field_name} = "
                        f"{value!r} is not in {list(allowed)}"
                    ),
                    axis="archetypes",
                ))

    _check("read", "pattern", "read.pattern")
    _check("read", "grouping", "read.grouping", optional=True)  # dataclass default: "none"
    _check("write", "pattern", "write.pattern")
    _check("write", "integrity", "write.integrity", optional=True)  # dataclass default: "direct"
    interactions = raw.get("interactions")
    if interactions is None:
        findings.append(Finding(
            rule=f"{prefix}.capabilities.interactions.missing",
            message=f"{prefix}.capabilities.interactions required (may be [])",
            axis="archetypes",
        ))
    elif not isinstance(interactions, list):
        findings.append(Finding(
            rule=f"{prefix}.capabilities.interactions.wrong_type",
            message=f"{prefix}.capabilities.interactions must be a list",
            axis="archetypes",
        ))
    else:
        allowed = set(capability_primitive_values("interactions"))
        for item in interactions:
            if item not in allowed:
                findings.append(Finding(
                    rule=f"{prefix}.capabilities.interactions.invalid_value",
                    message=(
                        f"{prefix}.capabilities.interactions contains "
                        f"{item!r} which is not in {sorted(allowed)}"
                    ),
                    axis="archetypes",
                ))
    _check("presentation", "itemShape", "presentation.itemShape")
    _check("state", "realtime", "state.realtime")
    return findings


def validate_runtime_context(raw: list[str] | None) -> list[Finding]:
    """IRF-M1-T4. Every declared capability must exist in
    ``context_vocabulary.json``. Empty list is valid (an app that needs
    no runtime capabilities). Unknown values reject (no fallback — the
    LLM shouldn't hallucinate runtime permissions)."""
    findings: list[Finding] = []
    if raw is None:
        # Absent field is legal — same effect as empty list. Planner emits
        # explicit empty list to match spec, but pipeline is tolerant.
        return findings
    if not isinstance(raw, list):
        findings.append(Finding(
            rule="runtime_context.wrong_type",
            message=f"plan.runtime_context must be a list; got {type(raw).__name__}",
            axis="runtime_context",
        ))
        return findings
    valid = set(runtime_capabilities())
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            findings.append(Finding(
                rule="runtime_context.item_wrong_type",
                message=f"plan.runtime_context items must be strings; got {item!r}",
                axis="runtime_context",
            ))
            continue
        if item in seen:
            findings.append(Finding(
                rule="runtime_context.duplicate",
                message=f"plan.runtime_context contains duplicate {item!r}",
                severity="warning",
                axis="runtime_context",
            ))
        seen.add(item)
        if item not in valid:
            findings.append(Finding(
                rule="runtime_context.unknown_capability",
                message=(
                    f"plan.runtime_context contains {item!r} which is not in "
                    f"context_vocabulary.json. Known: {sorted(valid)}"
                ),
                axis="runtime_context",
            ))
    return findings


def validate_coverage_verdict(raw: dict[str, Any] | None) -> list[Finding]:
    """IRF-M1-T5. Verdict must have valid status; nearest_supported
    populated when status != in_scope; missing_dimensions populated
    when status == extension_needed."""
    findings: list[Finding] = []
    if raw is None:
        findings.append(Finding(
            rule="coverage_verdict.missing",
            message="plan.coverage_verdict is required",
            axis="coverage_verdict",
        ))
        return findings
    if not isinstance(raw, dict):
        findings.append(Finding(
            rule="coverage_verdict.wrong_type",
            message="plan.coverage_verdict must be an object",
            axis="coverage_verdict",
        ))
        return findings

    status = raw.get("status")
    valid = {"in_scope", "extension_needed", "out_of_scope"}
    if status not in valid:
        findings.append(Finding(
            rule="coverage_verdict.status.invalid",
            message=(
                f"plan.coverage_verdict.status = {status!r} must be one of "
                f"{sorted(valid)}"
            ),
            axis="coverage_verdict",
        ))
        return findings

    reason = raw.get("reason")
    if not reason or not isinstance(reason, str):
        findings.append(Finding(
            rule="coverage_verdict.reason.missing",
            message="plan.coverage_verdict.reason must be a non-empty string",
            axis="coverage_verdict",
        ))

    if status != "in_scope":
        if not raw.get("nearest_supported"):
            findings.append(Finding(
                rule="coverage_verdict.nearest_supported.missing",
                message=(
                    f"plan.coverage_verdict.nearest_supported must be set when "
                    f"status={status!r} (user needs an alternative to redirect to)"
                ),
                axis="coverage_verdict",
            ))
    if status == "extension_needed":
        if not raw.get("missing_dimensions"):
            findings.append(Finding(
                rule="coverage_verdict.missing_dimensions.empty",
                message=(
                    "plan.coverage_verdict.missing_dimensions must list what "
                    "the axes don't capture when status='extension_needed'"
                ),
                axis="coverage_verdict",
            ))
    return findings


def validate_all(plan: dict[str, Any]) -> list[Finding]:
    """Convenience: run all four axis validators on a plan dict, return
    the concatenated findings list. Order = coverage / shape / archetypes /
    runtime_context (coverage first because an out_of_scope verdict makes
    the other validations irrelevant for user feedback purposes)."""
    findings: list[Finding] = []
    findings.extend(validate_coverage_verdict(plan.get("coverage_verdict")))
    findings.extend(validate_shape_profile(plan.get("app_shape")))
    findings.extend(validate_archetypes(plan.get("archetypes")))
    findings.extend(validate_runtime_context(plan.get("runtime_context")))
    return findings


# ══════════════════════════════════════════════════════════════════
# Fallback detectors — used only when validator rejects LLM output
# (M1-T6 / T7). Return the safe conservative default; caller logs
# LLM_UNAVAILABLE finding separately.
# ══════════════════════════════════════════════════════════════════


def safe_default_shape_profile() -> dict[str, Any]:
    """Return the shape defaults from vocabulary.json — sidebar shell +
    on-load auth + list read + multi-user identity. Matches today's
    implicit default output shape."""
    return json.loads(json.dumps(_shapes_vocabulary()["safe_defaults"]))


def safe_default_capabilities() -> dict[str, Any]:
    """Return the conservative crud-like capability defaults."""
    return json.loads(json.dumps(_capability_vocabulary()["safe_defaults"]))


# ══════════════════════════════════════════════════════════════════
# Helpers exported for the planner prompt renderer (M1-T1, next slice)
# ══════════════════════════════════════════════════════════════════


def render_planner_prompt_vocabulary() -> str:
    """Return the human-readable "PICK ONE VALUE PER PRIMITIVE" block
    the planner prompt injects. Rendering here (not in the planner
    module) means the vocabulary JSON is the sole source of truth."""
    lines = ["APP SHAPE — compose the profile by picking one value per primitive:", ""]
    prims = _shapes_vocabulary()["primitives"]
    for primitive, spec in prims.items():
        values = " | ".join(spec["values"])
        lines.append(f"  {primitive}: {values}")
    return "\n".join(lines)


def render_planner_prompt_capabilities() -> str:
    lines = ["ARCHETYPE CAPABILITIES — for LLM-composed modules:", ""]
    prims = _capability_vocabulary()["primitives"]
    for primitive, spec in prims.items():
        values = " | ".join(spec["values"])
        lines.append(f"  {primitive}: {values}")
    lines.append("")
    lines.append(f"KNOWN RECIPES: {', '.join(known_recipes())}")
    return "\n".join(lines)


def render_planner_prompt_runtime_capabilities() -> str:
    caps = _context_vocabulary()["capabilities"]
    lines = ["RUNTIME CONTEXT — multi-select platform capabilities:", ""]
    for name, gloss in caps.items():
        lines.append(f"  {name}  — {gloss}")
    return "\n".join(lines)
