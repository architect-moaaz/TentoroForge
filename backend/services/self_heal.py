"""Self-heal: regenerate deterministically-regenerable missing artifacts.

The reference resolver can *repair* a wrong name and *neutralize* a dead one, but
it can't conjure a missing target. For the one class where the target IS
deterministically regenerable — a `Create/Update/Delete<Entity>` workflow for a
real entity that a button references but that was never written — this regenerates
it (via the existing idempotent CRUD generator) instead of leaving the button dead.

Entity regeneration is deliberately NOT done here: materializing a Drizzle table +
data-init registration is 4-file surgery where one bad line breaks the whole app,
so a genuinely-missing entity stays flagged/neutralized rather than fabricated.
"""
from __future__ import annotations

import glob
import json
import os
import re

from services.form_scaffold import _ent_key, _iter_nodes, _load_registry

_CRUD_RE = re.compile(r"^(Create|Update|Delete)([A-Z]\w+)$")


def _workflow_names(output_dir: str) -> set[str]:
    wdir = os.path.join(output_dir, "workflows")
    out: set[str] = set()
    for fp in glob.glob(os.path.join(wdir, "*.json")):
        try:
            with open(fp, encoding="utf-8") as fh:
                d = json.load(fh)
            for k in ("name", "id"):
                if d.get(k):
                    out.add(str(d[k]))
        except Exception:
            continue
    return out


def _referenced_workflows(output_dir: str) -> set[str]:
    """Every workflow name referenced by a Button/rowAction/Form across schemas."""
    refs: set[str] = set()
    for fp in glob.glob(os.path.join(output_dir, "src", "schemas", "**", "*.json"), recursive=True):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        for node in _iter_nodes(schema):
            p = node.get("props") if isinstance(node.get("props"), dict) else {}
            w = p.get("workflow")
            if isinstance(w, str) and w and "." not in w:
                refs.add(w)
            ra = p.get("rowActions")
            if isinstance(ra, list):
                for r in ra:
                    act = r.get("action") if isinstance(r, dict) else None
                    if isinstance(act, dict) and isinstance(act.get("workflow"), str):
                        refs.add(act["workflow"])
    return refs


def heal_missing_workflows(output_dir: str) -> dict:
    """Regenerate missing CRUD workflows for real entities referenced in the UI.
    Returns {healed: [names], entities: [names]}."""
    reg = _load_registry(output_dir)
    entities = reg.get("entities") or {}
    if not entities:
        return {"healed": [], "entities": []}
    ent_by_key = {_ent_key(n): n for n in entities}

    have = _workflow_names(output_dir)
    missing = _referenced_workflows(output_dir) - have

    # Which missing refs are a CRUD workflow for a REAL entity → regenerable.
    need_entities: set[str] = set()
    for ref in missing:
        m = _CRUD_RE.match(ref)
        if not m:
            continue
        canon = ent_by_key.get(_ent_key(m.group(2)))
        if canon:
            need_entities.add(canon)

    if not need_entities:
        return {"healed": [], "entities": []}

    scoped_plan = {"entities": {n: entities[n] for n in need_entities}}
    try:
        from services.crud_workflow_generator import generate_crud_workflows
        written = generate_crud_workflows(scoped_plan, output_dir)
    except Exception:
        written = []
    return {"healed": written, "entities": sorted(need_entities)}
