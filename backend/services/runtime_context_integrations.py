"""Runtime-context → platform-integrations bridge (IRF-M3-T10).

Reads ``plan.runtime_context`` and returns the list of integration
keys each declared capability requires. Consumed by
``routers/platform_integrations.py`` so that server-side keys (FCM,
APNs, geocoding, etc.) automatically appear in
``/settings/integrations`` when the app declares the capability that
needs them.

Pure — no I/O beyond the cached bundle JSON reads (via
``runtime_context_wire``). Never raises; empty list on any failure."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.runtime_context_wire import compute_wire_plan


@dataclass(frozen=True)
class RequiredIntegration:
    """One integration-key requirement from an app's runtime_context.

    Fields mirror ``runtime_context_wire.IntegrationKey`` but adds
    the ``source_capability`` so the settings UI can group by
    "geo needs geocoding" vs "push_notifications needs FCM"."""
    source_capability: str
    provider: str
    env_var: str
    optional: bool
    docs: str


def required_integrations_for_plan(plan: dict[str, Any] | None) -> list[RequiredIntegration]:
    """Read ``plan.runtime_context``, return the flat list of
    integration-key requirements. Each entry carries which capability
    triggered it — the settings UI groups by capability.

    Ordering: preserves the plan's runtime_context declaration order,
    then within each capability preserves the bundle's declaration
    order. Deterministic.
    """
    if not isinstance(plan, dict):
        return []
    runtime_context = plan.get("runtime_context")
    if not isinstance(runtime_context, list) or not runtime_context:
        return []

    # Reconstruct capability → keys by walking one at a time, so we
    # can attribute each key to its source capability. (compute_wire_plan
    # flattens and loses that attribution.)
    out: list[RequiredIntegration] = []
    for cap in runtime_context:
        if not isinstance(cap, str):
            continue
        single = compute_wire_plan([cap])
        if not single.capabilities:  # unknown/missing bundle
            continue
        for k in single.integration_keys_required:
            out.append(RequiredIntegration(
                source_capability=cap,
                provider=k.provider,
                env_var=k.env_var,
                optional=k.optional,
                docs=k.docs,
            ))
    return out


def required_env_vars_for_plan(plan: dict[str, Any] | None) -> list[str]:
    """Convenience: return just the env_var names, deduplicated.
    Used by any pass that wants to warn about missing env vars."""
    seen: set[str] = set()
    out: list[str] = []
    for r in required_integrations_for_plan(plan):
        if r.env_var and r.env_var not in seen:
            seen.add(r.env_var)
            out.append(r.env_var)
    return out


def group_by_capability(
    requirements: list[RequiredIntegration],
) -> dict[str, list[RequiredIntegration]]:
    """Group requirements by source_capability for UI rendering."""
    groups: dict[str, list[RequiredIntegration]] = {}
    for r in requirements:
        groups.setdefault(r.source_capability, []).append(r)
    return groups
