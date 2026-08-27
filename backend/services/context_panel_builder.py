"""Spec B4 — Context side-rail for create/edit forms.

Symptom the spec calls out (property-mgmt "Add Rent Payment"):
    Users see an empty right rail on a form that fundamentally references
    a parent record (payment → lease, appointment → patient, invoice →
    customer). They must remember or hunt for context they need to fill
    the form correctly.

Cure (deterministic post-generate pass):
    For every create/edit form whose Form container has EXACTLY ONE FK
    dropdown (or one field flagged ``_primary: true`` in the plan), wrap
    the form's root in a ``Split[ratio="2:1"]`` layout. Left = the form
    as-authored. Right = a ``Card`` with a ``Heading`` + a
    ``DescriptionList`` bound to the parent record's key fields via
    ``{{form.<fkColumn>}}`` template.

No new library components — composed from ``Split`` + ``Card`` +
``Heading`` + ``DescriptionList``, all already registered.

Rollout: gated by ``FORGE_FORM_CONTEXT_PANEL`` env flag (default off).

Idempotent: sets ``props.__b4_context_panel = "1"`` on the Split node so
re-runs skip.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The label field a parent-record DescriptionList prefers — first match wins.
# Same list the FK label resolver uses so the panel stays consistent with
# the dropdown text.
_LABEL_CANDIDATES = (
    "name", "title", "label", "displayName", "unitNumber",
    "unit_number", "number", "code", "email", "identifier",
)


def _load_registry(output_dir: str) -> dict:
    p = Path(output_dir) / "registry.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _iter_form_pages(output_dir: str):
    """Yield (path, schema_dict) for every /new or /edit form page."""
    sdir = Path(output_dir) / "src" / "schemas"
    if not sdir.is_dir():
        return
    for p in sorted(sdir.glob("**/*.json")):
        base = p.name
        if base in ("shell.json", "nav-flow.json"):
            continue
        if base.startswith(("login", "signup", "register")):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        route = str(data.get("route") or "")
        # Only /edit forms — /new forms have an unpicked FK, so every
        # ``{{form.<col>}}`` binding in the panel resolves to empty and the
        # right column renders as a blank vertical band next to the fields.
        # (Spec B5's onChange-fetch runtime would populate the panel the
        # moment a user picks the FK. Until that ships, gating to /edit
        # prevents the "empty right column" symptom on create modals.)
        if "/edit" not in route:
            continue
        yield p, data


def _find_form_container(node: Any) -> dict | None:
    """DFS: return the first Form node under ``node``."""
    if isinstance(node, dict):
        if node.get("type") == "Form":
            return node
        for v in node.values():
            found = _find_form_container(v)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_form_container(item)
            if found is not None:
                return found
    return None


def _iter_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


def _detect_primary_fk(form_container: dict) -> dict | None:
    """Return ``{name, target, label_column}`` for the form's primary FK.

    Rules (first match wins):
      1. A Select/Combobox field with prop ``_primary: true``.
      2. If exactly ONE FK field exists (Select node with an
         ``optionsFrom.source`` pointing at a resource + name ending in
         ``id``/``Id``), it's the primary.
      3. Otherwise ambiguous → return None (skip the form).
    """
    fk_fields: list[dict] = []
    primary_flagged: dict | None = None
    for n in _iter_nodes(form_container):
        if not isinstance(n, dict):
            continue
        p = n.get("props") if isinstance(n.get("props"), dict) else None
        if not p:
            continue
        name = p.get("name")
        if not isinstance(name, str) or not name:
            continue
        opts_from = p.get("optionsFrom")
        if not isinstance(opts_from, dict):
            continue
        source = opts_from.get("source")
        if not isinstance(source, str) or not source:
            continue
        # Only Select-family nodes with an FK-shaped name.
        node_type = n.get("type")
        if node_type not in ("Select", "Combobox"):
            continue
        low = name.lower()
        if not (low.endswith("id") and low != "id"):
            continue
        fk_info = {
            "name": name,
            "target": source,
            "label_column": opts_from.get("label") or "name",
        }
        if p.get("_primary") is True:
            primary_flagged = fk_info
            break
        fk_fields.append(fk_info)
    if primary_flagged:
        return primary_flagged
    if len(fk_fields) == 1:
        return fk_fields[0]
    return None


def _summary_columns_for(target_entity: str, registry: dict) -> list[str]:
    """Return up to 4 informative column names to show in the panel.

    Preference order:
      1. Label-family (name/title/etc.) column, if present.
      2. Any user-friendly scalar column that isn't a system/audit field
         (excludes: id, *Id/*ID, *At, ownerId, userId).
    """
    ent = (registry.get("entities") or {}).get(target_entity)
    if not isinstance(ent, dict):
        return []
    fields = ent.get("fields")
    if not isinstance(fields, dict):
        return []
    # Choose the primary label first.
    label = None
    for cand in _LABEL_CANDIDATES:
        if cand in fields:
            label = cand
            break
    out: list[str] = []
    if label:
        out.append(label)
    for col_name in fields:
        low = col_name.lower()
        if col_name in out:
            continue
        if low == "id" or low.endswith(("id", "at")):
            continue
        if low in ("ownerid", "userid", "orgid", "tenantid",
                    "createdby", "updatedby", "deletedby"):
            continue
        out.append(col_name)
        if len(out) >= 4:
            break
    return out


def _humanize(col: str) -> str:
    """Convert `unitNumber` / `unit_number` → `Unit Number`."""
    import re
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", col)
    parts = re.split(r"[\s_\-]+", spaced)
    return " ".join(p[:1].upper() + p[1:] for p in parts if p)


def _build_context_card(fk: dict, target_entity: str, registry: dict) -> dict:
    """Compose the right-side context Card node.

    The DescriptionList's ``items`` bind to ``{{form.<fkColumn>}}``-scoped
    templates for now — Spec B5's onChange-fetch runtime populates the
    parent record's real values into the form scope, at which point the
    same bindings resolve to the actual field values.
    """
    cols = _summary_columns_for(target_entity, registry)
    # Fallback: at minimum, show the FK's own value so users see WHAT
    # they've selected even before B5's fetch runtime lights up.
    if not cols:
        items = [{
            "label": _humanize(target_entity),
            "value": f"{{{{form.{fk['name']}}}}}",
        }]
    else:
        items = [
            {"label": _humanize(col), "value": f"{{{{form.{col}}}}}"}
            for col in cols
        ]
    return {
        "type": "Card",
        "props": {"variant": "surface", "padding": "md"},
        "children": [
            {
                "type": "Heading",
                "props": {"level": 3, "text": f"Selected {_humanize(target_entity)}"},
            },
            {
                "type": "DescriptionList",
                "props": {"items": items, "orientation": "horizontal"},
            },
        ],
    }


def inject_context_panels(output_dir: str) -> dict:
    """Post-generate pass. Returns ``{wrapped, files}``.

    Silently no-ops when ``FORGE_FORM_CONTEXT_PANEL`` is not set to a
    truthy value (default off — this slice ships behind a flag per the
    spec's rollout order).
    """
    flag = os.getenv("FORGE_FORM_CONTEXT_PANEL", "0")
    if flag.strip().lower() not in ("1", "true", "yes", "on"):
        return {"wrapped": 0, "files": 0}

    registry = _load_registry(output_dir)
    wrapped = 0
    files = 0

    for path, schema in _iter_form_pages(output_dir):
        root = schema.get("root")
        if not isinstance(root, dict):
            continue
        form = _find_form_container(root)
        if not form:
            continue
        # Idempotency: the wrapping Split carries a marker prop.
        already = False
        for n in _iter_nodes(root):
            if isinstance(n, dict) and n.get("type") == "Split":
                p = n.get("props") if isinstance(n.get("props"), dict) else None
                if p and p.get("__b4_context_panel"):
                    already = True
                    break
        if already:
            continue

        fk = _detect_primary_fk(form)
        if not fk:
            continue

        card = _build_context_card(fk, fk["target"], registry)
        # Replace the root with a Split that holds the (existing) root + panel.
        # Deep-copy the original root as-is so children/props stay intact.
        original_root = root
        new_root = {
            "type": "Split",
            "props": {
                "ratio": "2:1",
                "breakpoint": "lg",
                "__b4_context_panel": "1",
            },
            "children": [original_root, card],
        }
        schema["root"] = new_root

        try:
            path.write_text(
                json.dumps(schema, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            wrapped += 1
            files += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[context-panel] write failed for %s: %s", path, exc)

    return {"wrapped": wrapped, "files": files}


__all__ = ["inject_context_panels"]
