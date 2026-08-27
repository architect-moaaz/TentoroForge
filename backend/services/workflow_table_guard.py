"""Gen-time reconciler for workflow table names — heals what it can, reports the rest.

WHAT THIS GUARANTEES (register TG-1 — the previous first line claimed more than
this module delivers, and readers relied on the stronger claim):

  * It RECONCILES a `config.table` to a real declared table whenever it can do
    so unambiguously — exact, then case/separator-insensitive, then
    plurality-insensitive.
  * It REPORTS, at ERROR, every table it could not resolve, and returns them in
    `unresolved` with `blocking: True`.
  * It RAISES `SchemaNotFoundError` when there are workflows but no schema at
    all, rather than silently finding nothing.

WHAT IT DOES NOT GUARANTEE: that no workflow reaches runtime with a bad table.
By default an unresolved table does NOT fail the build — `post_generate_fixes`
logs it and generation continues. Set `FORGE_TABLE_GATE=strict` to make it
blocking, following the existing `FORGE_BINDING_GATE=strict` precedent.



Generated workflow definitions (`<output_dir>/workflows/*.json`) carry db_* action
nodes whose `config.table` names the table to insert/update/delete. The runtime
looks that name up in the Drizzle schema — if it doesn't match a real
`pgTable("<name>", ...)` declaration, the app throws `unknown table` at the user.

The commonest cause is casing drift: the planner emits a snake_case table name
(`knowledge_articles`) while the deterministic schema builder declares the table
in camelCase (`knowledgeArticles`). Those are the SAME table; the mismatch is
cosmetic. This guard reconciles them:

- `config.table` that EXACTLY matches a real table → left alone.
- No exact match but a unique CANONICAL match (case- and separator-insensitive)
  → the workflow JSON is REWRITTEN to the real table name (auto-heal).
- Still no match but a unique PLURALITY-INSENSITIVE match (via the naming
  authority's `entity_key`) → also auto-healed. `categorys`/`category` both
  reduce to `category` and reach the declared `categories`.
- Ambiguous match at either tier OR no match at all → left as-is and recorded
  under `unresolved` — a genuine gap that gets a LOUD log, never silent.

Schema location comes from :mod:`services.schema_tables`, and a tree with NO
schema at all now raises instead of yielding an empty table list. Globbing
`src/db/schema/*.ts` non-recursively used to miss both the single-file
`src/db/schema.ts` layout and any nested layout; with zero real tables every
lookup missed, so this guard healed nothing AND reported valid tables as
schema gaps (register finding TG-2, HIGH).
"""
from __future__ import annotations

import glob
import json
import logging
import os

from services.entity_names import EntityNameError, entity_key
from services.schema_tables import real_tables as _real_tables

logger = logging.getLogger(__name__)


def _canon(s: str) -> str:
    """Case- and separator-insensitive key for matching table names."""
    return s.lower().replace("_", "").replace("-", "")


def _plural_key(s: str) -> str | None:
    """Case-, separator- AND plurality-insensitive key, or None if unusable.

    This is the tier that heals irregular plurals. It delegates to the
    naming authority so the guard reduces names exactly the way the
    generators build them."""
    try:
        return entity_key(s)
    except EntityNameError:
        return None


def _canon_index(real_tables: list[str]) -> dict[str, list[str]]:
    """Map a canonical key → the real table(s) that reduce to it."""
    idx: dict[str, list[str]] = {}
    for t in real_tables:
        idx.setdefault(_canon(t), []).append(t)
    return idx


def _plural_index(real_tables: list[str]) -> dict[str, list[str]]:
    """Map a plurality-insensitive key → the real table(s) that reduce to it."""
    idx: dict[str, list[str]] = {}
    for t in real_tables:
        k = _plural_key(t)
        if k:
            idx.setdefault(k, []).append(t)
    return idx


def _resolve_table(
    table: str,
    real_set: set[str],
    canon_idx: dict[str, list[str]],
    plural_idx: dict[str, list[str]],
) -> tuple[str | None, str]:
    """Resolve `table` to a real table name.

    Returns ``(real_name_or_None, reason)``. Tiers are tried in order of
    decreasing confidence and each REFUSES to guess when more than one
    real table matches — an ambiguous remap silently writes to the wrong
    table, which is worse than leaving the name alone and reporting it.
    """
    if table in real_set:
        return table, "exact"

    candidates = canon_idx.get(_canon(table), [])
    if len(candidates) == 1:
        return candidates[0], "canonical"
    if len(candidates) > 1:
        return None, f"ambiguous canonical match ({len(candidates)} tables)"

    key = _plural_key(table)
    if key is None:
        return None, "table name has no alphanumeric characters"
    plural_candidates = plural_idx.get(key, [])
    if len(plural_candidates) == 1:
        return plural_candidates[0], "plural"
    if len(plural_candidates) > 1:
        return None, f"ambiguous plural match ({len(plural_candidates)} tables)"

    return None, "no table in the schema reduces to this name"


def _reconcile_node(
    obj,
    real_set: set[str],
    canon_idx: dict[str, list[str]],
    plural_idx: dict[str, list[str]],
    file_name: str,
    remapped: list,
    unresolved: list,
) -> bool:
    """Recurse a JSON structure; heal any `config.table` string in place.

    Returns True if the structure was mutated (so the caller re-persists).
    """
    mutated = False
    if isinstance(obj, dict):
        # A `config` object carrying a `table` string is the thing we reconcile.
        cfg = obj.get("config")
        if isinstance(cfg, dict) and isinstance(cfg.get("table"), str):
            table = cfg["table"]
            real, reason = _resolve_table(table, real_set, canon_idx, plural_idx)
            if real is None:
                unresolved.append((file_name, table))
                # The old message said "genuine schema gap", which points the
                # reader at the plan or the schema builder. That is usually the
                # WRONG place: when the schema declares `categories` and the
                # workflow says `categorys`, the schema is correct and the
                # generator is at fault. Name both possibilities and say which
                # tables actually exist, so the reader can tell them apart.
                logger.error(
                    "workflow_table_guard: UNRESOLVED table %r in %s — %s. "
                    "This workflow WILL fail at runtime with `unknown table`. "
                    "Either (a) the schema really lacks this table, or (b) the "
                    "generator that emitted this name disagrees with "
                    "services.entity_names — compare against the declared "
                    "tables: %s",
                    table, file_name, reason, sorted(real_set) or "(none)",
                )
            elif real != table:
                cfg["table"] = real
                mutated = True
                remapped.append((file_name, table, real))
                logger.warning(
                    "workflow_table_guard: remapped table %r -> %r in %s (%s match)",
                    table, real, file_name, reason,
                )
        for v in obj.values():
            if _reconcile_node(v, real_set, canon_idx, plural_idx, file_name,
                               remapped, unresolved):
                mutated = True
    elif isinstance(obj, list):
        for v in obj:
            if _reconcile_node(v, real_set, canon_idx, plural_idx, file_name,
                               remapped, unresolved):
                mutated = True
    return mutated


def reconcile_workflow_tables(output_dir: str) -> dict:
    """Reconcile every workflow `config.table` to a real schema table.

    Returns {real_tables, remapped, unresolved, files_scanned}. Loud logging on
    every remap and every unresolved — this must never be silent.

    Raises :class:`services.schema_tables.SchemaNotFoundError` when the tree
    declares no schema. Without that, "the schema is empty" and "I looked in
    the wrong place" were the same result, and the guard reported valid
    tables as gaps (TG-2).
    """
    remapped: list = []
    unresolved: list = []
    files_scanned = 0

    wdir = os.path.join(output_dir, "workflows")
    if not os.path.isdir(wdir):
        # No workflows to reconcile — do not demand a schema for nothing.
        return {
            "real_tables": [],
            "remapped": remapped,
            "unresolved": unresolved,
            "files_scanned": files_scanned,
        }

    # There ARE workflows, so there must be a schema to check them against.
    real_tables = _real_tables(output_dir)
    real_set = set(real_tables)
    canon_idx = _canon_index(real_tables)
    plural_idx = _plural_index(real_tables)

    for fp in sorted(glob.glob(os.path.join(wdir, "*.json"))):
        files_scanned += 1
        file_name = os.path.basename(fp)
        try:
            with open(fp, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            logger.error(
                "workflow_table_guard: could not parse %s: %s — its tables are "
                "UNCHECKED and may not exist", file_name, e,
            )
            unresolved.append((file_name, f"<unparseable: {e}>"))
            continue

        mutated = _reconcile_node(
            data, real_set, canon_idx, plural_idx, file_name, remapped, unresolved
        )
        if mutated:
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
            except OSError as e:  # noqa: BLE001
                logger.warning("workflow_table_guard: could not write %s: %s", file_name, e)

    return {
        "real_tables": real_tables,
        "remapped": remapped,
        "unresolved": unresolved,
        "files_scanned": files_scanned,
    }
