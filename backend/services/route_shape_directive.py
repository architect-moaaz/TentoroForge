"""IRF-M4-T1 — per-route substrate directive for page_schema_agent.

Renders a HARD-CONSTRAINT prompt block naming:

  1. The effective shape at the route (plan.app_shape merged with any
     ArchetypeInstance.local_shape override that owns the route).
  2. The owning ArchetypeInstance's capabilities (if any) — read/write
     patterns, interactions, presentation.itemShape, state.realtime.
  3. plan.runtime_context — platform capabilities the app depends on
     (geo, camera, push, ...). These often gate what the page can render
     (e.g. a page can't call CameraCapture unless runtime_context includes
     ``camera``).

Empty string when the plan carries no ``app_shape`` — the page schema
agent then falls back to its pre-substrate prompt shape.
"""
from __future__ import annotations

from typing import Any

from services.route_context import route_context_for


_SHAPE_LAYOUT_LABELS = {
    "shell": "Persistent shell",
    "hero": "Hero treatment",
    "primaryInteraction": "Primary interaction",
    "density": "Density",
}
_SHAPE_NAV_LABELS = {"menu": "Global menu", "back": "Back affordance"}
_SHAPE_WORKFLOW_LABELS = {"executionMode": "Workflow execution"}
_SHAPE_DATA_LABELS = {"readShape": "Read shape", "denormalization": "Denormalization"}
_SHAPE_AUTH_LABELS = {"surface": "Auth surface", "gating": "Auth gating"}


def _render_slice(name: str, slice_dict: Any, labels: dict[str, str]) -> list[str]:
    if not isinstance(slice_dict, dict):
        return []
    lines: list[str] = []
    for key, label in labels.items():
        val = slice_dict.get(key)
        if val:
            lines.append(f"  - {label}: `{val}`")
    return lines


def build_directive(plan: Any, route: str) -> str:
    """Return a prompt block for the route's substrate context, or empty."""
    ctx = route_context_for(plan, route)
    shape = ctx.shape
    if not shape and not ctx.owning_archetype and not ctx.runtime_context:
        return ""

    lines = [
        "## Route Substrate (HARD CONSTRAINTS)",
        f"The following are non-negotiable for route `{route}`. They come from",
        "the app's four-axis shape + the owning archetype's capabilities +",
        "the app's declared runtime_context. Emit a page that HONORS them.",
        "",
    ]

    if shape:
        lines.append(f"### Effective shape at `{route}`")
        for slice_name, labels in (
            ("layout", _SHAPE_LAYOUT_LABELS),
            ("nav", _SHAPE_NAV_LABELS),
            ("workflows", _SHAPE_WORKFLOW_LABELS),
            ("data", _SHAPE_DATA_LABELS),
            ("auth", _SHAPE_AUTH_LABELS),
        ):
            block = _render_slice(slice_name, shape.get(slice_name), labels)
            if block:
                lines.append(f"- **{slice_name}**")
                lines.extend(block)
        lines.append("")

    module = ctx.owning_archetype
    if isinstance(module, dict):
        name = ctx.owning_module_name or "<unnamed>"
        recipe = module.get("recipe")
        lines.append(f"### Owning module: `{name}`" +
                     (f" (recipe: `{recipe}`)" if recipe else ""))
        caps = module.get("capabilities")
        if isinstance(caps, dict) and caps:
            for cap_key in ("read", "write", "interactions", "presentation", "state"):
                val = caps.get(cap_key)
                if isinstance(val, dict) and val:
                    for k, v in val.items():
                        lines.append(f"  - {cap_key}.{k}: `{v}`")
                elif isinstance(val, list) and val:
                    lines.append(f"  - {cap_key}: {', '.join(str(x) for x in val)}")
                elif val:
                    lines.append(f"  - {cap_key}: `{val}`")
        lines.append("")

    if ctx.runtime_context:
        lines.append("### App runtime_context (platform capabilities available)")
        lines.append("  - " + ", ".join(f"`{c}`" for c in ctx.runtime_context))
        lines.append("  Components that need one of these (CameraCapture → `camera`,")
        lines.append("  map widgets → `geo`) are AVAILABLE. Components that need one")
        lines.append("  NOT listed here MUST NOT be emitted.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["build_directive"]
