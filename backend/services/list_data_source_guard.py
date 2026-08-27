"""Gen-time guard so a page's LIST/table can never bind to data that isn't there.

A list page loads its rows through a dataSource (`{"name": ..., "entity": ...,
"op": "list"}`). The renderer resolves every dataSource and stores the result in
a map keyed by the dataSource's `name`; a Table/Repeat then reads its rows from
that map via a `{{name}}` binding. Two independent naming drifts break this:

1. **binding ↔ name drift** (the real wj83u270 bug). An LLM-authored list page
   names the dataSource off the ENTITY plural (`recruitmentDrives`) but binds the
   Table's `rows` off the ROUTE slug (`{{drives}}`). The deterministic builder
   uses one token for both, so single-word entities match by luck; a multi-word
   entity (`RecruitmentDrive` on `/drives`) diverges and the table renders EMPTY —
   the create succeeds, the row exists, but nothing binds it.

2. **source ↔ table drift**. A dataSource carries an explicit routing key
   (`source`/`table`/`from`) naming a slug the data-engine never registered
   (`recruitment-drives` vs the registered `recruitmentDrives`) → a 404 / empty
   list. Same casing/separator drift `workflow_table_guard` heals for workflows.

This guard reconciles both, idempotently and loudly:

- An explicit dataSource `source`/`table`/`from` that EXACTLY matches a registered
  slug → left alone; a unique CANONICAL match → rewritten to the real slug;
  otherwise flagged `source_unresolved` (never silently changed).
- A Table/Repeat/List rows-binding `{{X}}` that matches NO dataSource name on the
  page → repointed to the list dataSource it obviously means (a unique canonical
  match, else the page's sole list dataSource); otherwise flagged
  `binding_unresolved`.

The data-engine registers entities under their Drizzle EXPORT name
(`registerEntity(name, table, { slug: name })`), so the set of real registered
slugs is the `export const <NAME> = pgTable(...)` names, not the pgTable() arg.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# `export const recruitmentDrives = pgTable("recruitmentDrives", ...` — the const
# name is the data-engine registration slug (registerEntity(name, ..., {slug:name})).
_EXPORT_TABLE_RE = re.compile(r"export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*pgTable\(")

# A pure single-token binding: "{{ recruitmentDrives }}" -> "recruitmentDrives".
# Rejects dotted / indexed / expression bindings ({{a.b}}, {{arr[0]}}) — those
# reference a field of a source, not the source itself.
_SINGLE_TOKEN_RE = re.compile(r"^\{\{\s*([A-Za-z_][\w]*)\s*\}\}$")

# Keys whose value is a rows-collection binding on a list-ish node.
_LIST_BINDING_KEYS = ("rows", "items", "bind", "source")
# DataSource keys that explicitly route to a table/slug (vs the `entity` label).
_SOURCE_KEYS = ("source", "table", "from")
# ops we treat as a collection load.
_LIST_OPS = ("list", "table", "grid", "index")


def _canon(s: str) -> str:
    """Case- and separator-insensitive key for matching slugs/names."""
    return s.lower().replace("_", "").replace("-", "")


def _registered_slugs(output_dir: str) -> list[str]:
    """Every `export const <NAME> = pgTable(...)` slug the data-engine registers."""
    sdir = os.path.join(output_dir, "src", "db", "schema")
    names: list[str] = []
    if not os.path.isdir(sdir):
        return names
    for fp in sorted(glob.glob(os.path.join(sdir, "*.ts"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        names.extend(_EXPORT_TABLE_RE.findall(text))
    seen: set[str] = set()
    uniq: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _canon_index(items: list[str]) -> dict[str, list[str]]:
    """Map a canonical key → the item(s) that reduce to it."""
    idx: dict[str, list[str]] = {}
    for t in items:
        idx.setdefault(_canon(t), []).append(t)
    return idx


def _is_list_source(ds) -> bool:
    if not isinstance(ds, dict):
        return False
    op = str(ds.get("op", "")).strip().lower()
    return op in _LIST_OPS


def _reconcile_source_keys(
    data_sources: list,
    slug_set: set[str],
    slug_canon: dict[str, list[str]],
    file_name: str,
    source_remapped: list,
    source_unresolved: list,
) -> bool:
    """Heal explicit `source`/`table`/`from` slugs on list dataSources."""
    mutated = False
    for ds in data_sources:
        if not _is_list_source(ds):
            continue
        for key in _SOURCE_KEYS:
            val = ds.get(key)
            if not isinstance(val, str) or not val:
                continue
            if val in slug_set:
                continue  # exact — OK
            candidates = slug_canon.get(_canon(val), [])
            if len(candidates) == 1:
                real = candidates[0]
                ds[key] = real
                mutated = True
                source_remapped.append((file_name, key, val, real))
                logger.warning(
                    "list_data_source_guard: remapped dataSource %s %r -> %r in %s",
                    key, val, real, file_name,
                )
            else:
                source_unresolved.append((file_name, key, val))
                logger.warning(
                    "list_data_source_guard: UNRESOLVED dataSource %s %r in %s "
                    "(%d registered-slug match(es))",
                    key, val, file_name, len(candidates),
                )
    return mutated


def _reconcile_bindings(
    node,
    ds_names: set[str],
    list_names: list[str],
    list_canon: dict[str, list[str]],
    file_name: str,
    binding_remapped: list,
    binding_unresolved: list,
) -> bool:
    """Recurse the node tree; repoint rows-bindings to a real list dataSource."""
    mutated = False
    if isinstance(node, dict):
        for key, val in list(node.items()):
            if key in _LIST_BINDING_KEYS and isinstance(val, str):
                m = _SINGLE_TOKEN_RE.match(val)
                if m:
                    token = m.group(1)
                    if token not in ds_names:
                        target = None
                        canon_hits = list_canon.get(_canon(token), [])
                        if len(canon_hits) == 1:
                            target = canon_hits[0]
                        elif len(list_names) == 1:
                            target = list_names[0]
                        if target is not None:
                            node[key] = "{{" + target + "}}"
                            mutated = True
                            binding_remapped.append((file_name, key, token, target))
                            logger.warning(
                                "list_data_source_guard: rebound %s {{%s}} -> {{%s}} in %s",
                                key, token, target, file_name,
                            )
                        else:
                            binding_unresolved.append((file_name, key, token))
                            logger.warning(
                                "list_data_source_guard: UNRESOLVED binding %s {{%s}} in %s "
                                "(%d list dataSource(s))",
                                key, token, file_name, len(list_names),
                            )
            if _reconcile_bindings(
                val, ds_names, list_names, list_canon,
                file_name, binding_remapped, binding_unresolved,
            ):
                mutated = True
    elif isinstance(node, list):
        for v in node:
            if _reconcile_bindings(
                v, ds_names, list_names, list_canon,
                file_name, binding_remapped, binding_unresolved,
            ):
                mutated = True
    return mutated


def reconcile_list_sources(output_dir: str) -> dict:
    """Reconcile every page's list/table dataSource + its rows-binding.

    Returns {registered_slugs, source_remapped, source_unresolved,
    binding_remapped, binding_unresolved, files_scanned, files_changed}. Loud
    logging on every remap and every unresolved — never silent. Idempotent.
    """
    registered = _registered_slugs(output_dir)
    slug_set = set(registered)
    slug_canon = _canon_index(registered)

    source_remapped: list = []
    source_unresolved: list = []
    binding_remapped: list = []
    binding_unresolved: list = []
    files_scanned = 0
    files_changed = 0

    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {
            "registered_slugs": registered,
            "source_remapped": source_remapped,
            "source_unresolved": source_unresolved,
            "binding_remapped": binding_remapped,
            "binding_unresolved": binding_unresolved,
            "files_scanned": files_scanned,
            "files_changed": files_changed,
        }

    # Phase 6a (Collection Authority) — when a schema is composer-authored
    # (collection maquette marker) AND the collection flag is on, skip
    # rewriting. The composer's dataSource names are the authority.
    from services.artifact_authority import should_assert_only_any as should_assert_only

    asserts_logged = 0
    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
        files_scanned += 1
        file_name = os.path.relpath(fp, sdir)
        try:
            with open(fp, encoding="utf-8") as fh:
                page = json.load(fh)
        except (OSError, ValueError) as e:
            logger.warning("list_data_source_guard: could not parse %s: %s", file_name, e)
            continue
        if not isinstance(page, dict):
            continue

        if should_assert_only(page):
            asserts_logged += 1
            logger.info(
                "[list_data_source_guard] ASSERT %s: composer-authored — "
                "skipping source/binding reconciliation (authority)",
                file_name,
            )
            continue

        data_sources = page.get("dataSources")
        if not isinstance(data_sources, list):
            data_sources = []

        ds_names = {
            ds["name"] for ds in data_sources
            if isinstance(ds, dict) and isinstance(ds.get("name"), str)
        }
        list_names = [
            ds["name"] for ds in data_sources
            if _is_list_source(ds) and isinstance(ds.get("name"), str)
        ]
        list_canon = _canon_index(list_names)

        mutated = _reconcile_source_keys(
            data_sources, slug_set, slug_canon, file_name,
            source_remapped, source_unresolved,
        )
        # Rebind against the (possibly just-healed) dataSource names.
        if _reconcile_bindings(
            page.get("root"), ds_names, list_names, list_canon,
            file_name, binding_remapped, binding_unresolved,
        ):
            mutated = True

        if mutated:
            files_changed += 1
            try:
                with open(fp, "w", encoding="utf-8") as fh:
                    json.dump(page, fh, indent=2)
            except OSError as e:  # noqa: BLE001
                logger.warning("list_data_source_guard: could not write %s: %s", file_name, e)

    return {
        "registered_slugs": registered,
        "source_remapped": source_remapped,
        "source_unresolved": source_unresolved,
        "binding_remapped": binding_remapped,
        "binding_unresolved": binding_unresolved,
        "files_scanned": files_scanned,
        "files_changed": files_changed,
        "asserts_logged": asserts_logged,
    }
