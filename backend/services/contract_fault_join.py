"""SV-STRICT-2b — join Faults (runtime observations) to ComponentContracts
(gen-time authoritative promises).

The two extractors use different id schemes for widgets:

  interaction_extractor  →  ``button:/candidates:root.children[0]``  (JSON-path)
  component_contract     →  ``button:/candidates:new-candidate``     (label-slug)

Both are stable within their own extractor but don't collide. This
module bridges them by joining on the invariants they share:

  * ``kind`` on the interaction matches ``component_type`` on the contract
  * ``route`` is identical when both live on a page
  * a disambiguating signal (label / dataSource / param) tiebreaks
    within a route when multiple contracts of that type exist

Pure function. Deterministic. Missing matches return ``None`` — never
raises, never fabricates.
"""
from __future__ import annotations

from typing import Iterable

from services.component_contract import ComponentContract
from services.fault_report import Fault
from services.interaction_extractor import (
    ButtonInteraction,
    DetailInteraction,
    FormInteraction,
    Interaction,
    ListInteraction,
    RouteInteraction,
)


# Runtime Interaction.kind → authority ComponentContract.component_type
_KIND_TO_TYPE: dict[str, tuple[str, ...]] = {
    "route":  ("page", "detail"),   # RouteInteraction → page (or detail if bracket-param)
    "button": ("button",),
    "form":   ("form",),
    "list":   ("table",),
    "detail": ("detail",),
}


def join_faults_to_contracts(
    faults: Iterable[Fault],
    contracts: Iterable[ComponentContract],
) -> dict[str, str | None]:
    """Return ``{fault.id: contract.id | None}`` — one entry per fault.

    A ``None`` value means the fault referenced a component the contract
    layer didn't know about (rare — usually a schema-shape the extractor
    doesn't yet cover). Callers should treat it as a diagnostic hint,
    not an error.
    """
    contracts_list = list(contracts)
    # Index once for O(1) route+type lookups.
    by_type_route: dict[tuple[str, str], list[ComponentContract]] = {}
    for c in contracts_list:
        if c.route is None:
            continue
        by_type_route.setdefault((c.component_type, c.route), []).append(c)

    out: dict[str, str | None] = {}
    for fault in faults:
        out[fault.id] = _match(fault.interaction, by_type_route)
    return out


def _match(
    interaction: Interaction,
    by_type_route: dict[tuple[str, str], list[ComponentContract]],
) -> str | None:
    kind = getattr(interaction, "kind", None)
    route = getattr(interaction, "route", None)
    if not kind or not route:
        return None

    candidate_types = _KIND_TO_TYPE.get(kind, ())
    # For a plain "route" interaction on a bracket-param route, prefer
    # 'page' over 'detail' — the detail-typed contract exists as a
    # narrower promise that a *DetailInteraction* is the right way to
    # falsify.
    if kind == "route":
        candidate_types = ("page",)
    if kind == "detail":
        candidate_types = ("detail",)

    all_candidates: list[ComponentContract] = []
    for t in candidate_types:
        all_candidates.extend(by_type_route.get((t, route), []))
    if not all_candidates:
        return None
    if len(all_candidates) == 1:
        return all_candidates[0].id

    # Multiple contracts on the same (type, route). Try to narrow by a
    # per-kind disambiguator.
    if isinstance(interaction, ButtonInteraction):
        label = (interaction.label or "").strip().lower()
        if label:
            for c in all_candidates:
                if (c.label or "").strip().lower() == label:
                    return c.id
    if isinstance(interaction, ListInteraction):
        ds = (interaction.dataSource or "").strip().lower()
        if ds:
            for c in all_candidates:
                # table contract id looks like "table:{route}:{ds-slug}"
                if ds in c.id.lower():
                    return c.id

    # Fall back to the first candidate — deterministic because the
    # contract extractor sorts (component_type, id) up-stream.
    return all_candidates[0].id
