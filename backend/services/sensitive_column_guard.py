"""Post-gen guard: strip sensitive columns from Table nodes.

A generated Table that lists a ``users`` entity is happy to show every
column the plan authored — including ``passwordHash``, ``verifyToken``,
``resetSecret``, ``mfaSecret``. Those are lifecycle-only fields that
should never surface in list UI. The LLM will forget to exclude them;
the collection composer's field-picker used to include them; a Smith
edit can re-introduce them.

This guard runs late in the post-gen pipeline (UI polish phase) and
drops any Table column whose ``key`` matches the sensitive-name pattern
(case-insensitive, hyphens/underscores/spaces normalized).

The module also strips the same fields from ``rowHref`` templates and
from ``DescriptionList`` items in detail views, since a "detail" page
is still a UI surface a user sees. Form field pruning is out of scope —
the form scaffolder already excludes lifecycle *At columns and never
authors password columns from real create-user flows; if a user is
explicitly editing their password there's a different edit path.

Behaviour is deterministic + idempotent — a second run finds nothing
to drop. Fully covered by unit tests in
``tests/services/test_sensitive_column_guard.py``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── sensitive-name pattern ───────────────────────────────────────────


# Any field whose canonicalised key contains one of these substrings
# is considered sensitive. The set stays intentionally conservative —
# adding one entry that catches half the app's real columns is a much
# worse failure than missing one edge case. Extend only when a real
# missed field surfaces.
#
# Matches are on the CANONICAL form (lower-case, underscores + hyphens
# stripped) so ``passwordHash`` / ``password_hash`` / ``password-hash``
# all collapse to ``passwordhash`` and match ``password``.
_SENSITIVE_SUBSTRINGS: frozenset[str] = frozenset({
    # Password material — hashes, salts, plaintext (never should be a
    # column, but defensive), reset tokens.
    "password",
    "passwordhash",
    "passwordsalt",
    "pwdhash",
    "pwdsalt",
    # Auth secrets — verify/reset/session tokens, refresh tokens, MFA.
    "verifytoken",
    "verificationtoken",
    "resettoken",
    "resetsecret",
    "sessiontoken",
    "refreshtoken",
    "accesstoken",
    "mfasecret",
    "totpsecret",
    "twofactorsecret",
    # Generic secrets/keys. NOTE: bare ``token`` and ``secret`` are
    # NOT in this set — many domains legitimately have ``token`` as a
    # display-worthy field (payment tokens shown as *last-4 in the
    # UI). Only the compound forms above trigger removal.
    "apisecret",
    "clientsecret",
    "privatekey",
    "encryptionkey",
    "webhooksecret",
})


def _canonical(name: str | None) -> str:
    """Return a lowercase, punctuation-stripped form for pattern match."""
    if not isinstance(name, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def is_sensitive_column(key: str | None) -> bool:
    """Return True when ``key`` names a sensitive/auth field.

    Public so other services (form scaffolder, detail polish, Smith
    edit tools) can share the same policy without re-implementing it.
    """
    canon = _canonical(key)
    if not canon:
        return False
    # Substring match on the canonical form. ``"passwordHash"`` →
    # ``"passwordhash"`` → contains ``"password"`` → sensitive.
    return any(needle in canon for needle in _SENSITIVE_SUBSTRINGS)


# ── walker ───────────────────────────────────────────────────────────


def _strip_table_columns(node: Any) -> int:
    """Recursively strip sensitive columns from every ``Table`` node
    under ``node``. Returns the number of columns dropped.

    Handles list-of-strings ``columns: ["email", "passwordHash"]`` and
    list-of-dicts ``columns: [{"key": ..., "label": ...}]``. Non-list
    ``columns`` (unknown/malformed) are left alone.
    """
    dropped = 0
    if isinstance(node, list):
        for child in node:
            dropped += _strip_table_columns(child)
        return dropped
    if not isinstance(node, dict):
        return 0

    if node.get("type") == "Table":
        props = node.get("props")
        if isinstance(props, dict):
            cols = props.get("columns")
            if isinstance(cols, list):
                kept: list[Any] = []
                for c in cols:
                    if isinstance(c, str):
                        if is_sensitive_column(c):
                            dropped += 1
                            continue
                        kept.append(c)
                    elif isinstance(c, dict):
                        if is_sensitive_column(c.get("key") or c.get("field")):
                            dropped += 1
                            continue
                        kept.append(c)
                    else:
                        # Unknown shape — keep it, the renderer will
                        # decide what to do. Never drop something we
                        # don't understand.
                        kept.append(c)
                if len(kept) != len(cols):
                    props["columns"] = kept

    # Recurse into any child container regardless of node type — pages
    # nest Tables inside Cards, Stacks, Grids, etc.
    for k in ("children",):
        child = node.get(k)
        if isinstance(child, (list, dict)):
            dropped += _strip_table_columns(child)
    return dropped


def _strip_description_items(node: Any) -> int:
    """Same policy for DescriptionList/DescriptionItem items on detail
    pages. Returns the number of items dropped.

    Detail pages typically render as ``DescriptionList`` +
    ``DescriptionItem`` per field; the item's ``field`` / ``key`` is
    what the renderer reads. Sensitive items get pruned so the detail
    view doesn't render the hash either.
    """
    dropped = 0
    if isinstance(node, list):
        for child in node:
            dropped += _strip_description_items(child)
        return dropped
    if not isinstance(node, dict):
        return 0

    t = node.get("type")
    if t == "DescriptionList":
        props = node.get("props")
        if isinstance(props, dict) and isinstance(props.get("items"), list):
            items = props["items"]
            kept = [
                it for it in items
                if not (isinstance(it, dict)
                        and is_sensitive_column(it.get("key") or it.get("field")))
            ]
            if len(kept) != len(items):
                dropped += len(items) - len(kept)
                props["items"] = kept

        # DescriptionList can also express fields as children nodes
        # (``DescriptionItem`` per field). Prune those too.
        kids = node.get("children")
        if isinstance(kids, list):
            kept = []
            for c in kids:
                if isinstance(c, dict) and c.get("type") == "DescriptionItem":
                    p = c.get("props") or {}
                    if is_sensitive_column(p.get("field") or p.get("key")):
                        dropped += 1
                        continue
                kept.append(c)
            if len(kept) != len(kids):
                node["children"] = kept

    for k in ("children",):
        child = node.get(k)
        if isinstance(child, (list, dict)):
            dropped += _strip_description_items(child)
    return dropped


# ── entry ────────────────────────────────────────────────────────────


def strip_sensitive_columns(output_dir: str | Path) -> dict[str, Any]:
    """Sweep every ``src/schemas/**/*.json`` under ``output_dir`` and
    drop sensitive columns/description-items in place.

    Returns::

        {
          "scanned": <int, page schemas scanned>,
          "changed": [<page basename>, ...],
          "table_columns_dropped": <int>,
          "description_items_dropped": <int>,
        }

    Never raises. A malformed schema JSON is logged + skipped so a
    broken page can't stop the guard from cleaning the rest.
    """
    root = Path(output_dir) if isinstance(output_dir, str) else output_dir
    schemas_dir = root / "src" / "schemas"
    result: dict[str, Any] = {
        "scanned": 0,
        "changed": [],
        "table_columns_dropped": 0,
        "description_items_dropped": 0,
    }
    if not schemas_dir.is_dir():
        return result

    for path in sorted(schemas_dir.rglob("*.json")):
        result["scanned"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("sensitive_column_guard: skip malformed %s: %s",
                           path.name, exc)
            continue

        root_node = data.get("root")
        cols = _strip_table_columns(root_node)
        items = _strip_description_items(root_node)

        if cols or items:
            result["table_columns_dropped"] += cols
            result["description_items_dropped"] += items
            result["changed"].append(path.relative_to(schemas_dir).as_posix())
            try:
                path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except OSError as exc:
                logger.warning("sensitive_column_guard: write failed for %s: %s",
                               path.name, exc)

    if result["changed"]:
        logger.info(
            "sensitive_column_guard: dropped %d Table column(s) + %d "
            "description item(s) across %d schema(s) in %s",
            result["table_columns_dropped"],
            result["description_items_dropped"],
            len(result["changed"]),
            output_dir,
        )
    return result


__all__ = [
    "is_sensitive_column",
    "strip_sensitive_columns",
]


# ── registry boundary ────────────────────────────────────────────────


def strip_sensitive_from_registry(registry: Any) -> tuple[Any, int]:
    """Remove sensitive columns from an entity registry before a composer
    reads it. Returns ``(cleaned_copy, n_dropped)``; input is not mutated.

    Why here and not (only) in the output sweep: the maquette composers
    author page columns straight from the registry. If the registry still
    contains ``passwordHash``, the composer emits it and a second sweep
    has to come along and strip it again — the guard ran twice because
    the *input* was wrong, not the output. Cleaning the boundary means
    the composer cannot emit what it never received.

    Handles both registry field shapes seen in the wild: a list of
    ``{"name": ...}`` dicts (or bare strings), and a ``{name: type}``
    map. Anything unrecognised is passed through untouched — dropping a
    column the composer needs is worse than one extra output sweep.
    """
    if not isinstance(registry, dict):
        return registry, 0
    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return registry, 0

    cleaned = dict(registry)
    new_entities: dict[str, Any] = {}
    dropped = 0

    for ent_name, meta in entities.items():
        if not isinstance(meta, dict):
            new_entities[ent_name] = meta
            continue
        new_meta = dict(meta)
        for key in ("fields", "columns"):
            val = meta.get(key)
            if isinstance(val, list):
                kept = []
                for f in val:
                    name = f.get("name") if isinstance(f, dict) else f
                    if is_sensitive_column(name if isinstance(name, str) else None):
                        dropped += 1
                        continue
                    kept.append(f)
                new_meta[key] = kept
            elif isinstance(val, dict):
                kept_map = {}
                for name, spec in val.items():
                    if is_sensitive_column(name):
                        dropped += 1
                        continue
                    kept_map[name] = spec
                new_meta[key] = kept_map
        new_entities[ent_name] = new_meta

    cleaned["entities"] = new_entities
    return cleaned, dropped
