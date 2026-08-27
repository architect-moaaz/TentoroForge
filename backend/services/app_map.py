"""App-map — deterministic mental model of a generated app for Smith.

Given a generated-app ``output_dir``, reads the contract files and
returns a compact structured view of the app's entities, pages, and
workflows. Pure function. No LLM. No filesystem writes.

Consumers:
  * ``services.smith_memory`` — injects the rendered skeleton into
    Smith's system prompt on every turn so he opens a turn already
    knowing the app instead of grep-hunting for it.
  * The warmup endpoint — pre-populates the cache when the chat panel
    mounts so the first turn is instant.

Sources (all under ``output_dir``):
  * ``contracts/resource-registry.json`` — entities + relationships.
  * ``contracts/action-contract.json``   — pages ↔ form_submit ↔ workflows.
  * ``contracts/generation-dossier.json`` — the user's original prompt.
  * ``src/schemas/**/*.json``            — page routes (deterministic).

Output shape::

    {
      "intent": "One-line summary of what the app is.",
      "entities": {
        "Candidate": {
          "table": "candidates",
          "slug": "candidates",
          "columns_count": 24,
          "fks_out": [{"col": "cvUploadId", "target_entity": "CVUpload"}],
          "fks_in":  [{"from_entity": "Application", "col": "candidateId"}],
        },
        ...
      },
      "pages": [
        {
          "route": "/candidates/new",
          "path":  "src/schemas/candidates/new.json",
          "archetype": "form",
          "entity":    "Candidate",
          "form_submit_workflow": "create-candidate",
        },
        ...
      ],
      "workflows": {
        "create-candidate":         {"target": "Candidate", "kind": "auto-crud", "op": "create"},
        "ShortlistingWorkflow":     {"target": "Application", "kind": "domain"},
        ...
      },
    }
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


_CONTRACT_FILES = (
    "contracts/resource-registry.json",
    "contracts/action-contract.json",
    "contracts/generation-dossier.json",
    "registry.json",
)

# In-process cache: {resolved_output_dir → (mtime_signature, app_map_dict)}.
# The signature is a tuple of mtimes for every contract file — any change
# to any file bumps at least one entry and triggers a rebuild. Missing
# files contribute a sentinel so their appearance also invalidates.
_APP_MAP_CACHE: dict[str, tuple[tuple[float, ...], dict[str, Any]]] = {}


def get_app_map(output_dir: str | Path) -> dict[str, Any]:
    """Return the app-map for ``output_dir``, using the cache when fresh.

    Two hits with unchanged contracts return the same dict *identity*.
    Any write to a contract file invalidates and forces a rebuild on the
    next call. Missing directories cache the empty result — but only
    until the underlying files appear (the signature includes 'missing'
    as a sentinel so file creation is detected)."""
    resolved = str(Path(output_dir).resolve())
    sig = _mtime_signature(resolved)
    hit = _APP_MAP_CACHE.get(resolved)
    if hit is not None and hit[0] == sig:
        return hit[1]
    fresh = build_app_map(output_dir)
    _APP_MAP_CACHE[resolved] = (sig, fresh)
    return fresh


def clear_app_map_cache() -> None:
    """Drop the entire cache. Tests + admin only."""
    _APP_MAP_CACHE.clear()


def _mtime_signature(resolved_output_dir: str) -> tuple[float, ...]:
    """One float per contract file; missing files contribute a sentinel."""
    root = Path(resolved_output_dir)
    out: list[float] = []
    for rel in _CONTRACT_FILES:
        try:
            st = os.stat(root / rel)
            out.append(st.st_mtime)
        except FileNotFoundError:
            out.append(-1.0)  # sentinel — file appearance flips this
        except OSError:
            out.append(-2.0)  # unreadable — treat as invalidation-triggering
    return tuple(out)


def build_app_map(output_dir: str | Path) -> dict[str, Any]:
    """Return the app-map for the generated app at ``output_dir``.

    Missing files degrade gracefully — any section that can't be
    populated comes back as an empty dict/list/string. This matters
    because Smith may see an app mid-generation or an incomplete
    imported project."""
    root = Path(output_dir)
    entities = _extract_entities(root)
    pages = _extract_pages(root, entities)
    workflows = _extract_workflows(root)
    intent = _extract_intent(root)
    # Detail-page relationship gaps — the signal that lets Smith reason
    # about "detail page doesn't show all information" asks. For each
    # detail page, lists the inbound relations and FK joins that ARE
    # NOT yet rendered in the schema. Smith reads this to know which
    # related tables / joins to suggest without asking the user to
    # narrow down. See services.detail_page_analyzer for the rules.
    try:
        from services.detail_page_analyzer import analyze_detail_pages, to_dict
        detail_gaps = to_dict(analyze_detail_pages(entities, pages, root))
    except Exception:  # noqa: BLE001 — analyzer must never break the map
        detail_gaps = []
    # Peer-shape inconsistencies — the class of bug where one page's
    # dataSource shape diverges from its archetype siblings (extra
    # ``filter`` clause, missing ``key``, etc). Catches the exact
    # Drive-detail-empty case Smith couldn't diagnose from a single-
    # page inspection. See services.peer_shape_analyzer.
    try:
        from services.peer_shape_analyzer import (
            find_peer_shape_inconsistencies,
            to_dict as peer_to_dict,
        )
        peer_inconsistencies = peer_to_dict(
            find_peer_shape_inconsistencies(pages, root)
        )
    except Exception:  # noqa: BLE001
        peer_inconsistencies = []
    return {
        "intent": intent,
        "entities": entities,
        "pages": pages,
        "workflows": workflows,
        "detail_gaps": detail_gaps,
        "peer_shape_inconsistencies": peer_inconsistencies,
    }


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #

def _extract_entities(root: Path) -> dict[str, dict]:
    """Read ``resource-registry.json``, return the entity map."""
    rr_path = root / "contracts" / "resource-registry.json"
    if not rr_path.exists():
        return {}
    try:
        rr = json.loads(rr_path.read_text())
    except Exception:
        return {}
    raw = rr.get("entities") or {}
    if not isinstance(raw, dict):
        return {}

    # Pass 1: outbound FKs and a slug → entity-name lookup.
    slug_to_name: dict[str, str] = {}
    for name, meta in raw.items():
        if meta.get("slug"):
            slug_to_name[meta["slug"]] = name
        for alt in _slug_variants(name):
            slug_to_name.setdefault(alt, name)

    out: dict[str, dict] = {}
    for name, meta in raw.items():
        cols = meta.get("columns") or []
        fks_out = []
        for c in cols:
            fk = c.get("fk")
            if not fk:
                continue
            target = slug_to_name.get(fk)
            fks_out.append({
                "col":           c.get("name"),
                "target_entity": target,     # None if unresolvable
                "target_slug":   fk,
            })
        out[name] = {
            "table":         meta.get("table"),
            "slug":          meta.get("slug"),
            "columns_count": len(cols),
            "fks_out":       fks_out,
            "fks_in":        [],  # filled in pass 2
        }

    # Pass 2: inbound FKs — walk every outbound, register the reverse.
    for src_name, meta in out.items():
        for fk in meta["fks_out"]:
            tgt_name = fk["target_entity"]
            if tgt_name and tgt_name in out:
                out[tgt_name]["fks_in"].append({
                    "from_entity": src_name,
                    "col":         fk["col"],
                })
    return out


def _slug_variants(name: str) -> list[str]:
    """Return possible dossier-style fk slug variants for an entity name.

    The dossier uses different slug conventions in different fields:
    ``CVUpload`` shows up as ``cv-uploads`` (registry) and ``c-v-upload``
    (fk-semantics), and sometimes as ``cvupload``. We generate all three
    so :func:`_extract_entities`'s slug→name lookup catches everything."""
    lower = name.lower()
    # kebab on capitals: CVUpload → cvupload → cv-upload
    hyphen_break = re.sub(r"(?<!^)(?=[A-Z][a-z])", "-", name).lower()
    # each capital becomes a dash: CVUpload → c-v-upload
    each_upper = re.sub(r"(?<!^)([A-Z])", r"-\1", name).lower()
    return list({lower, hyphen_break, each_upper})


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

_ARCHETYPE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"/new$"),                "form"),
    (re.compile(r"/apply$"),              "form"),
    (re.compile(r"/(?::id|\[id\])/edit$"), "form"),
    (re.compile(r"/(?::id|\[id\])$"),     "detail"),
    (re.compile(r"^/pipeline$"),          "dashboard"),
    (re.compile(r"^/dashboard$"),         "dashboard"),
    (re.compile(r"^/analytics$"),         "dashboard"),
    (re.compile(r"^/$"),                  "dashboard"),
]

def _archetype_for(route: str) -> str:
    """Return the archetype a route reads as (form|detail|list|dashboard).

    Route-based inference is deliberate: it's stable, deterministic, and
    matches the shape names in ``page_type_templates.py``. Content-based
    inference is left to future taks."""
    for rx, kind in _ARCHETYPE_RULES:
        if rx.search(route):
            return kind
    return "list"


def _extract_pages(root: Path, entities: dict[str, dict]) -> list[dict]:
    """Scan ``src/schemas/**/*.json`` and pair each with its form_submit
    workflow from ``action-contract.json``."""
    ac_path = root / "contracts" / "action-contract.json"
    actions_by_file: dict[str, dict] = {}
    if ac_path.exists():
        try:
            ac = json.loads(ac_path.read_text())
        except Exception:
            ac = {}
        for a in ac.get("actions") or []:
            if a.get("kind") == "form_submit" and a.get("file"):
                actions_by_file[a["file"]] = a

    schemas_root = root / "src" / "schemas"
    if not schemas_root.exists():
        return []

    slug_to_ent = {
        (meta.get("slug") or name.lower()): name
        for name, meta in entities.items()
    }

    pages: list[dict] = []
    for file in sorted(schemas_root.rglob("*.json")):
        try:
            data = json.loads(file.read_text())
        except Exception:
            continue
        route = data.get("route")
        if not isinstance(route, str) or not route.startswith("/"):
            continue
        rel = file.relative_to(root).as_posix()

        # Entity binding: leading route segment matched against entity slugs.
        first_seg = route.strip("/").split("/", 1)[0] if route != "/" else ""
        entity = slug_to_ent.get(first_seg)

        # Action-contract keys look like "candidates/new.json", not the full
        # "src/schemas/candidates/new.json" — strip the prefix.
        ac_key = rel.split("src/schemas/", 1)[-1]
        action = actions_by_file.get(ac_key)

        pages.append({
            "route":                 route,
            "path":                  rel,
            "archetype":             _archetype_for(route),
            "entity":                entity,
            "form_submit_workflow":  (action or {}).get("workflow_id"),
        })
    return pages


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #

def _extract_workflows(root: Path) -> dict[str, dict]:
    """Collect every unique workflow id referenced by any action or
    interaction and label its kind, op, and target entity."""
    ac_path = root / "contracts" / "action-contract.json"
    rr_path = root / "contracts" / "resource-registry.json"
    workflows: dict[str, dict] = {}

    if ac_path.exists():
        try:
            ac = json.loads(ac_path.read_text())
        except Exception:
            ac = {}
        for a in ac.get("actions") or []:
            wid = a.get("workflow_id")
            wref = a.get("workflow_ref") or ""
            if not wid:
                continue
            entry = workflows.setdefault(wid, {})
            m = re.match(r"^(create|update)-(.+)$", wid)
            if m:
                entry["op"] = m.group(1)
                entry["kind"] = "auto-crud"
                # workflow_ref shape: "CreateCandidate" / "UpdateInterview"
                cap_op = m.group(1).capitalize()
                if wref.startswith(cap_op):
                    entry["target"] = wref[len(cap_op):]
            else:
                entry.setdefault("kind", "domain")

    if rr_path.exists():
        try:
            rr = json.loads(rr_path.read_text())
        except Exception:
            rr = {}
        # Interactions tell us domain workflows' target entities via
        # targetEntityId (slug), which we upgrade to the Camel entity name.
        rr_ents = rr.get("entities") or {}
        slug_to_ent = {
            (meta.get("slug") or name.lower()): name
            for name, meta in rr_ents.items()
            if isinstance(meta, dict)
        }
        for i in rr.get("interactions") or []:
            wid = i.get("workflowId")
            target_slug = i.get("targetEntityId")
            if not wid:
                continue
            entry = workflows.setdefault(wid, {"kind": "domain"})
            if target_slug and not entry.get("target"):
                cand = slug_to_ent.get(target_slug)
                if not cand:
                    cand = _slug_to_camel(target_slug)
                entry["target"] = cand
    return workflows


def _slug_to_camel(slug: str | None) -> str | None:
    if not isinstance(slug, str) or not slug:
        return None
    return "".join(p.capitalize() for p in slug.split("-"))


# --------------------------------------------------------------------------- #
# Intent
# --------------------------------------------------------------------------- #

def _extract_intent(root: Path) -> str:
    """Read the raw user prompt from the dossier and collapse to one line."""
    dos_path = root / "contracts" / "generation-dossier.json"
    if not dos_path.exists():
        return ""
    try:
        dos = json.loads(dos_path.read_text())
    except Exception:
        return ""
    prompt = dos.get("prompt")
    if isinstance(prompt, str) and prompt.strip():
        collapsed = " ".join(prompt.split())
        return collapsed[:240] + ("…" if len(collapsed) > 240 else "")
    plan = dos.get("plan") or {}
    return str(plan.get("description") or plan.get("name") or "")
