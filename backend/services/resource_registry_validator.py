"""Build-time validator for the canonical resource registry (spec P5).

Symmetric to ``binding_validator`` (which gates UI bindings), this asserts the
canonical registry itself is internally consistent: every relationship, foreign
key, and interaction reference resolves to a REAL registry entity id, and every
interaction workflow resolves to a REAL generated workflow. A malformed registry
— the naming authority the whole pipeline reads from — is caught here rather than
surfacing later as a runtime ``unknown table`` / dead button.

``validate_registry(output_dir) -> {"ok": bool, "errors": [...], "warnings": [...]}``

Additive and defensive: a missing/unparseable registry returns ``ok:True`` with
a warning, and the function NEVER raises (an internal bug degrades to a warning).
Errors and warnings are dicts ``{"kind","detail"}`` (except the not-found warning,
which is the plain string ``"resource-registry.json not found"``), deterministically
sorted by ``(kind, detail)``.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


def _canon(s) -> str:
    """Case- and separator-insensitive key for matching workflow ids/names."""
    import re
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _entity_ids(registry: dict) -> set[str]:
    """The set of real entity ids = every ``entities[*].id``."""
    ids: set[str] = set()
    entities = registry.get("entities")
    if isinstance(entities, dict):
        for spec in entities.values():
            if isinstance(spec, dict) and spec.get("id"):
                ids.add(str(spec["id"]))
    return ids


def _workflow_keys(output_dir: str) -> set[str] | None:
    """Canonical keys (id + filename stem) for every real workflow.

    Returns ``None`` when the workflows dir is absent (so callers downgrade the
    workflow-existence check to a warning). Reuses ``binding_validator``'s reader
    for the canonical id/name/stem set; falls back to a local scan on any issue.
    """
    wdir = os.path.join(output_dir, "workflows")
    if not os.path.isdir(wdir):
        return None
    try:
        from services.binding_validator import _read_workflows
        idx = _read_workflows(output_dir)
        if idx:
            return set(idx.keys())
    except Exception:  # noqa: BLE001 — fall back to a local scan
        pass
    keys: set[str] = set()
    try:
        for fn in os.listdir(wdir):
            if not fn.endswith(".json"):
                continue
            keys.add(_canon(fn[:-5]))
            try:
                with open(os.path.join(wdir, fn), encoding="utf-8") as fh:
                    doc = json.load(fh)
                if isinstance(doc, dict):
                    for key in (doc.get("id"), doc.get("name")):
                        if key:
                            keys.add(_canon(key))
            except Exception:  # noqa: BLE001 — a bad file must not break the scan
                continue
    except OSError:
        return None
    return keys


def validate_registry(output_dir: str) -> dict:
    """Assert the canonical registry references only real ids / workflows.

    Returns ``{"ok": bool, "errors": [{kind, detail}], "warnings": [...]}``.
    Never raises.
    """
    errors: list = []
    warnings: list = []
    try:
        path = os.path.join(output_dir, "contracts", "resource-registry.json")
        if not os.path.isfile(path):
            return {"ok": True, "errors": [],
                    "warnings": ["resource-registry.json not found"]}
        try:
            with open(path, encoding="utf-8") as fh:
                registry = json.load(fh)
        except (OSError, ValueError):
            return {"ok": True, "errors": [],
                    "warnings": ["resource-registry.json not found"]}
        if not isinstance(registry, dict):
            return {"ok": True, "errors": [],
                    "warnings": ["resource-registry.json not found"]}

        ids = _entity_ids(registry)
        wf_keys = _workflow_keys(output_dir)  # None ⇒ workflows dir absent

        # relationship_unresolved: from/to must be real entity ids.
        for rel in (registry.get("relationships") or []):
            if not isinstance(rel, dict):
                continue
            for end in ("from", "to"):
                ref = rel.get(end)
                if ref and str(ref) not in ids:
                    errors.append({
                        "kind": "relationship_unresolved",
                        "detail": f"relationship {rel.get('from')!r}->{rel.get('to')!r} "
                                  f"{end} {str(ref)!r} is not a registered entity id",
                    })

        # fk_target_unresolved: columns[].fk and fks[].targetEntityId must resolve.
        entities = registry.get("entities")
        if isinstance(entities, dict):
            for name, spec in sorted(entities.items()):
                if not isinstance(spec, dict):
                    continue
                for col in (spec.get("columns") or []):
                    if not isinstance(col, dict):
                        continue
                    fk = col.get("fk")
                    if fk and str(fk) not in ids:
                        errors.append({
                            "kind": "fk_target_unresolved",
                            "detail": f"entity {str(name)!r} column {str(col.get('name'))!r} "
                                      f"fk target {str(fk)!r} is not a registered entity id",
                        })
                for fk in (spec.get("fks") or []):
                    if not isinstance(fk, dict):
                        continue
                    tgt = fk.get("targetEntityId")
                    if tgt and str(tgt) not in ids:
                        errors.append({
                            "kind": "fk_target_unresolved",
                            "detail": f"entity {str(name)!r} fk column {str(fk.get('column'))!r} "
                                      f"target {str(tgt)!r} is not a registered entity id",
                        })

        # interactions: entity + workflow references.
        for inter in (registry.get("interactions") or []):
            if not isinstance(inter, dict):
                continue
            iid = inter.get("id") or ""
            tgt = inter.get("targetEntityId")
            if tgt is None:
                warnings.append({
                    "kind": "interaction_entity_missing",
                    "detail": f"interaction {str(iid)!r} has no inferred targetEntityId",
                })
            elif str(tgt) not in ids:
                errors.append({
                    "kind": "interaction_entity_unresolved",
                    "detail": f"interaction {str(iid)!r} targetEntityId {str(tgt)!r} "
                              f"is not a registered entity id",
                })

            wf = inter.get("workflowId")
            if wf:
                if wf_keys is None:
                    # workflows dir absent → cannot verify; warn rather than fail.
                    warnings.append({
                        "kind": "interaction_workflow_unresolved",
                        "detail": f"interaction {str(iid)!r} workflowId {str(wf)!r} "
                                  f"cannot be verified (no workflows dir)",
                    })
                elif _canon(wf) not in wf_keys:
                    errors.append({
                        "kind": "interaction_workflow_unresolved",
                        "detail": f"interaction {str(iid)!r} workflowId {str(wf)!r} "
                                  f"resolves to no real workflow",
                    })
    except Exception as e:  # noqa: BLE001 — the validator must never break generation
        logger.exception("resource_registry_validator: internal error (degrading to warning)")
        warnings.append({"kind": "validator_error",
                         "detail": f"resource_registry_validator internal error: {e}"})
        return {"ok": True, "errors": errors, "warnings": warnings}

    errors.sort(key=lambda e: (e.get("kind", ""), e.get("detail", "")))
    warnings.sort(key=lambda w: (w.get("kind", ""), w.get("detail", ""))
                  if isinstance(w, dict) else ("", str(w)))
    return {"ok": not errors, "errors": errors, "warnings": warnings}
