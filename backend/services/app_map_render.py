"""Render the app-map dict as a compact prompt block for Smith.

The block is injected into Smith's system prompt on every turn so he
opens each conversation already knowing the shape of the app —
entities, page routes, workflows, and the original intent.

Size target: under 4 KB for a realistic app (~7 entities, ~20 pages,
~15 workflows). Every design choice here is 'what would keep this
under budget while still answering the questions Smith wastes iters
hunting for?'"""
from __future__ import annotations

from typing import Any


_HEADER = "# APP MAP (deterministic view over contracts — always in memory)"


def render_app_map_skeleton(app_map: dict[str, Any]) -> str:
    """Return the prompt block. Pure. Order deterministic.

    Sections:
      1. intent      — the user's original one-line ask
      2. entities    — one line per entity: name, col count, FK arrows
      3. pages       — one line per page:   route, archetype, workflow
      4. workflows   — one line per workflow: name → target entity
    """
    parts: list[str] = [_HEADER, ""]

    intent = (app_map.get("intent") or "").strip()
    if intent:
        parts.append(f"intent: {intent}")
    else:
        parts.append("intent: (not known)")
    parts.append("")

    parts.append("entities:")
    ents = app_map.get("entities") or {}
    if not ents:
        parts.append("  (no entities registered yet)")
    else:
        for name in sorted(ents):
            parts.append("  " + _render_entity_line(name, ents[name]))
    parts.append("")

    parts.append("pages:")
    pages = app_map.get("pages") or []
    if not pages:
        parts.append("  (no pages registered yet)")
    else:
        for p in pages:
            parts.append("  " + _render_page_line(p))
    parts.append("")

    parts.append("workflows:")
    wfs = app_map.get("workflows") or {}
    if not wfs:
        parts.append("  (no workflows registered yet)")
    else:
        for wid in sorted(wfs):
            parts.append("  " + _render_workflow_line(wid, wfs[wid]))
    parts.append("")

    # Detail-page relationship gaps — what related data Smith could add
    # to each detail page without being asked to specify. The bulk of
    # "detail page not showing all information" asks resolve to one of
    # these entries. Smith reads this before punting with "please share
    # the specific screen."
    gaps_list = app_map.get("detail_gaps") or []
    gaps_list = [g for g in gaps_list if (g.get("gaps") or [])]
    if gaps_list:
        parts.append("detail-page relationship gaps:")
        for g in gaps_list:
            parts.append(f"  {g['route']}  ({g['entity']}):")
            for gap in g["gaps"]:
                parts.append("    " + _render_gap_line(gap))
        parts.append("")

    # Peer-shape inconsistencies — pages whose dataSource shape diverges
    # from the mode of their archetype. Names the specific keys that
    # differ + gives Smith 3 peer pages it can cross-reference. When the
    # user says "detail page is empty" or "not binding," this is where
    # the odd-one-out lives.
    peer_incs = app_map.get("peer_shape_inconsistencies") or []
    if peer_incs:
        parts.append("peer-shape inconsistencies (odd one out vs archetype siblings):")
        for i in peer_incs:
            parts.append("  " + _render_peer_inconsistency_line(i))
        parts.append("")

    # Trailing routing hint that reminds Smith what the map exists FOR —
    # otherwise the LLM occasionally treats it as decorative context.
    parts.append(
        "USE THE MAP FIRST. Never grep-hunt for a file the map can name. "
        "For details behind a name (columns, page tree, workflow steps), "
        "call read_entity / read_page / read_workflow. "
        "When a user asks 'the X detail page isn't showing all information,' "
        "consult the detail-page relationship gaps ABOVE before asking them "
        "to narrow — the entries there name the exact tables/joins that would "
        "answer the ask. "
        "When a user says 'the X page is empty' or 'nothing binds,' consult "
        "the peer-shape inconsistencies ABOVE — the odd-shape dataSource is "
        "almost always the culprit (extra `filter` clause, missing `key`, etc). "
        "Compare the observed_shape to peer_shape to know the exact edit."
    )
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Line renderers
# --------------------------------------------------------------------------- #

def _render_entity_line(name: str, meta: dict) -> str:
    """Ex: ``Candidate (24 cols)  out: cvUploadId→CVUpload``.

    ``sink`` when no outbound FKs (the User pattern) so Smith reads it as
    intentional, not truncated."""
    cols = meta.get("columns_count", 0)
    outs = meta.get("fks_out") or []
    if outs:
        arrows = ", ".join(
            f"{fk['col']}→{fk.get('target_entity') or fk.get('target_slug') or '?'}"
            for fk in outs
        )
        return f"{name} ({cols} cols)  out: {arrows}"
    return f"{name} ({cols} cols)  sink (no fks out)"


def _render_page_line(page: dict) -> str:
    """Ex: ``/candidates/new  form  → create-candidate  (Candidate)``.

    All four pieces (route, archetype, workflow, entity) are the
    questions Smith asks before mutating a page; putting them on one line
    kills 3–4 tool calls per turn."""
    route = page.get("route", "?")
    arch = page.get("archetype", "?")
    wf = page.get("form_submit_workflow")
    entity = page.get("entity")
    tail_parts: list[str] = []
    if wf:
        tail_parts.append(f"→ {wf}")
    if entity:
        tail_parts.append(f"({entity})")
    tail = "  " + "  ".join(tail_parts) if tail_parts else ""
    return f"{route:32s}  {arch}{tail}"


def _render_workflow_line(wid: str, meta: dict) -> str:
    """Ex: ``create-candidate  auto-crud/create → Candidate``."""
    kind = meta.get("kind", "?")
    op = meta.get("op")
    target = meta.get("target") or "?"
    kind_str = f"{kind}/{op}" if op else kind
    return f"{wid:34s}  {kind_str} → {target}"


def _render_gap_line(gap: dict) -> str:
    """Ex: ``inbound_relation  Application (via driveId) — add Table``.

    Compact enough that a dozen gaps stay under budget, explicit enough
    that Smith knows the entity + column + suggested component without
    additional tool calls."""
    kind = gap.get("kind", "?")
    ent = gap.get("related_entity", "?")
    col = gap.get("related_via_column", "?")
    comp = gap.get("suggested_component", "?")
    return f"{kind}  {ent} (via {col}) — add {comp}"


def _render_peer_inconsistency_line(inc: dict) -> str:
    """Ex: ``/drives/[id]  detail  get: observed [entity,filter,name,op]
    vs peer [entity,name,op] (peers: /applications/[id], /pipeline/[id])``.

    Puts everything Smith needs to diff on one line: route, archetype,
    op, observed shape, peer shape, and a couple example peer routes."""
    route = inc.get("route", "?")
    arch = inc.get("archetype", "?")
    op = inc.get("op", "?")
    obs = ",".join(inc.get("observed_shape") or [])
    peer = ",".join(inc.get("peer_shape") or [])
    peers = ", ".join(inc.get("peer_pages") or [])
    return (
        f"{route}  {arch}  {op}:  observed [{obs}]  vs peer [{peer}]"
        f"  (peers: {peers})"
    )
