"""Alias unknown page-schema component types to their nearest registered
equivalents so the renderer doesn't drop them as "unknown component".

The page-schema LLM sometimes emits component names the library doesn't
ship — the classic offender is ``DateTimePicker`` (the library ships
``DatePicker`` + ``TimePicker`` separately, no combined widget). Any
node whose ``type`` is unknown to the compiled library registry
(``packages/registry/dist/starter.json``) is silently dropped by the
renderer, producing empty form cards AND a red "unknown component" hint
that reads as a broken app.

Only aliases that map to a KNOWN registered component are applied — this
never rewrites to a name the renderer would also drop. The alias table
is intentionally small; we prefer fixing the emitter at the source when
possible, and use this as a defence-in-depth backstop for whatever
still slips through.

Runs as a ``post_generate_fixes`` pass. Idempotent — a second run over
already-aliased schemas is a no-op.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Alias table: LLM-emitted name -> library-registered name. Each mapping is
# a "closest valid" translation. Applied only when (a) the source name is
# NOT in the registry AND (b) the target name IS. This last check means
# ``Checkbox`` (which IS registered) is never rewritten to ``Switch``.
_ALIASES: dict[str, str] = {
    "DateTimePicker": "DatePicker",  # no combined widget; DatePicker is closest
    "DateField":      "DatePicker",
    "TimeField":      "TimePicker",
    "TextField":      "Input",
    "TextArea":       "Textarea",   # correct casing
    "NumberField":    "NumberInput",
    "TimelineList":   "Timeline",   # LLM notification feeds; Timeline is the shipped list-shape
    # Checkbox → Switch is intentionally NOT included: Checkbox IS in the
    # library registry (verified 2026-08-13). Adding it would rewrite valid
    # nodes to a different semantic (single-choice → toggle).
}


def _load_registry_names(root: Path) -> set[str]:
    """Set of component names the library actually ships.

    Reads ``packages/registry/dist/starter.json`` — the compiled component
    map used by the renderer. Returns an empty set if the file is missing
    or malformed; callers should treat an empty set as "don't alias
    anything" (the pass becomes a no-op rather than mis-rewriting).
    """
    # Walk up from output_dir to find the repo root's packages/registry.
    # In practice output_dir is `.../design2ui-forge-v3/output/<id>`, so
    # `../../packages/registry/dist/starter.json` from output_dir hits it.
    candidates = [
        root.parent.parent / "packages" / "registry" / "dist" / "starter.json",
        Path.cwd() / "packages" / "registry" / "dist" / "starter.json",
    ]
    for path in candidates:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return set(data.keys())
        except Exception as e:  # noqa: BLE001
            logger.warning("alias_unknown_components: failed to read %s: %s", path, e)
    return set()


def _walk_and_alias(node: Any, registered: set[str], stats: dict[str, int]) -> Any:
    """Recursively walk a schema node, rewriting unknown ``type`` fields
    to their alias when the alias target is registered.

    Mutates dicts in-place. Returns the (possibly mutated) node so callers
    can reassign at the top level idiomatically. Increments ``stats`` for
    logging.
    """
    if isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and t not in registered:
            target = _ALIASES.get(t)
            if target and target in registered:
                node["type"] = target
                stats["aliased"] += 1
                stats.setdefault(f"_{t}->{target}", 0)
                stats[f"_{t}->{target}"] += 1
        for v in node.values():
            _walk_and_alias(v, registered, stats)
    elif isinstance(node, list):
        for item in node:
            _walk_and_alias(item, registered, stats)
    return node


def run(output_dir: str) -> dict[str, int]:
    """Rewrite unknown component names to registered aliases across every
    ``src/schemas/**/*.json`` in ``output_dir``.

    Returns ``{"aliased": total_rewrites, "files": files_touched}``. An
    empty registry (registry file missing) short-circuits to a no-op.
    """
    root = Path(output_dir)
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return {"aliased": 0, "files": 0}

    registered = _load_registry_names(root)
    if not registered:
        logger.warning("alias_unknown_components: registry starter.json not found; skipping")
        return {"aliased": 0, "files": 0}

    total = {"aliased": 0}
    files_touched = 0

    for schema_path in schemas_dir.rglob("*.json"):
        try:
            data = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("alias_unknown_components: failed to read %s: %s", schema_path, e)
            continue
        before = total["aliased"]
        _walk_and_alias(data, registered, total)
        if total["aliased"] > before:
            files_touched += 1
            try:
                schema_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                rel = schema_path.relative_to(root)
                # One line per file so a large run stays scannable.
                logger.info(
                    "alias_unknown_components: rewrote %d node(s) in %s",
                    total["aliased"] - before, rel,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("alias_unknown_components: failed to write %s: %s", schema_path, e)

    # Log per-alias breakdown at INFO so the run log tells you WHICH aliases
    # actually fired (helps decide when to remove one from the table).
    for k, v in total.items():
        if k.startswith("_") and v:
            logger.info("alias_unknown_components: %s x%d", k[1:], v)

    return {"aliased": total["aliased"], "files": files_touched}
