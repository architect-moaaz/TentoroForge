"""Smith's view of the Blueprint the engine actually writes.

There are two Blueprint stores. `services/blueprint/` (the 20-node DAG) writes
``.forge/blueprint/current.json``; Smith's own `Blueprint` reads
``.forge/blueprint.json``. Different files, and nothing writes the second — so
on a project with a fully generated application Smith loaded an EMPTY
blueprint, concluded there was nothing to reason about, and routed every
message to bootstrap.

That is why a rename answered with the bootstrap seam message even after
`understand_ask` and `move_dispatcher` were wired: iteration was never reached.
§8's memory layer 2 pointed at a file that does not exist, which quietly
disabled §16's clarification and §114's Prompt-to-Change along with it.

This maps one into the other. An adapter rather than a second writer: the
engine's document stays authoritative and Smith reads a projection of it, so
the two cannot drift into disagreeing about what the application is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def engine_doc_path(output_dir: str) -> Path:
    return Path(output_dir) / ".forge" / "blueprint" / "current.json"


def load_engine_doc(output_dir: str) -> dict[str, Any] | None:
    """The engine's Blueprint, or None when this project has no generated app."""
    path = engine_doc_path(output_dir)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Unreadable is treated as absent: Smith falls back to its own file
        # and, failing that, to an empty blueprint — which is what it did
        # before this adapter existed.
        return None
    return doc if isinstance(doc, dict) else None


def _live(items: Any) -> list[dict]:
    return [i for i in (items or [])
            if isinstance(i, dict) and i.get("status") != "SUPERSEDED"]


def to_smith_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """The engine's document in the shape Smith's `Blueprint` holds.

    Only what Smith reasons over: the domain it is working in, the entities,
    the workflows, and the pages. `pick_relevant_slice` and
    `blueprint_to_context` read these, and `understand_ask` needs the pages
    most of all — its `target_file` has to name a route that exists.
    """
    app = doc.get("application") or {}
    product = doc.get("product") or {}
    entities = (doc.get("data") or {}).get("entities")

    domain = {
        "name": app.get("domain") or product.get("domain") or "",
        "primary_actors": [
            str(r.get("name") or r.get("id") or "")
            for r in _live(doc.get("roles"))
        ],
        "core_verbs": [
            str(w.get("name") or "") for w in _live(doc.get("workflows"))
        ][:8],
        "distinctive_shape": app.get("description") or "",
        "why": app.get("description") or "",
    }

    return {
        "domain": domain,
        "entities": [
            {
                "name": e.get("name"),
                "table": e.get("table"),
                "purpose": e.get("purpose") or "",
                "key_fields": [f.get("name") for f in (e.get("fields") or [])
                               if isinstance(f, dict) and f.get("name")],
                "why_shaped_this_way": e.get("purpose") or "",
            }
            for e in _live(entities)
        ],
        "workflows": [
            {
                "name": w.get("name"),
                "purpose": w.get("purpose") or "",
                "trigger": (w.get("trigger") or {}).get("kind") or "manual",
                "why": w.get("purpose") or "",
            }
            for w in _live(doc.get("workflows"))
        ],
        "pages": [
            {
                "route": p.get("route"),
                # The path the projection writes, which is what
                # `understand_ask` returns as `target_file` and what the move
                # scopes against. Derived the same way the projection derives
                # it, so the two agree.
                "schema_path": _schema_path(str(p.get("route") or "")),
                "role": p.get("name") or p.get("id") or "",
                "notable_choices": [],
            }
            for p in _live(doc.get("pages"))
        ],
    }


def _schema_path(route: str) -> str:
    body = (route or "/").strip("/")
    return f"src/schemas/{body or 'home'}.json"
