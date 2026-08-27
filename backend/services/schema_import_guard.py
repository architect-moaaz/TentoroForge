"""Reconcile the dynamic `import("@/db/schema/<X>")` lines in the two generated
data-engine files to the schema files that ACTUALLY exist on disk.

The live BUILD break: `runtime_injector._generate_data_init_module` and
`_generate_data_api_route` GLOB `src/db/schema/*.ts` and emit one
`import("@/db/schema/<stem>")` per file. They run BEFORE `schema_dedup_guard`
removes duplicate/plural schema files (e.g. both `customer.ts` AND `customers.ts`).
After dedup deletes `customers.ts`, those two files still carry
`import("@/db/schema/customers")`. `Promise.allSettled` tolerates the reject at
RUNTIME, but webpack resolves module paths at BUILD time and hard-fails with
`Module not found: Can't resolve '@/db/schema/customers'`.

This post-generate backstop, run AFTER dedup, prunes every import that no longer
maps to a real schema file and (for completeness) adds an import for any real
schema module the file is missing. Additive, idempotent, never raises.
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

# Names that live in the schema dir but are NOT importable table modules.
_NON_MODULE_STEMS = {"index", "relations"}

# One dynamic import line: `<indent>import("@/db/schema/<stem>"),`
_IMPORT_LINE_RE = re.compile(r'^(?P<indent>[ \t]*)import\(\s*["\']@/db/schema/(?P<stem>[^"\']+)["\']\s*\),?\s*$')
# Inline (for prune-detection anywhere in a line).
_IMPORT_STEM_RE = re.compile(r'import\(\s*["\']@/db/schema/([^"\']+)["\']\s*\)')

_TARGETS = (
    os.path.join("src", "lib", "data-init.ts"),
    os.path.join("src", "app", "api", "data", "[...path]", "route.ts"),
)


def _real_stems(schema_dir: str) -> set[str]:
    """The authoritative set of importable schema module stems on disk.

    Keeps `_forge_*` (real modules); excludes only `index`/`relations`.
    """
    stems = set()
    for f in os.listdir(schema_dir):
        if not f.endswith(".ts"):
            continue
        stem = f[:-3]
        if stem in _NON_MODULE_STEMS:
            continue
        stems.add(stem)
    return stems


def _reconcile_file(path: str, real_stems: set[str]) -> tuple[bool, int, int]:
    """Prune dead imports + add missing real ones in a single target file.

    Returns (changed, removed, added). Never raises.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            original = fh.read()
    except OSError as e:  # pragma: no cover - defensive
        logger.warning("schema_import_guard: could not read %s: %s", path, e)
        return (False, 0, 0)

    lines = original.split("\n")

    # --- PRUNE: drop import lines whose stem is not a real schema module. ---
    kept: list[str] = []
    removed = 0
    import_indices: list[int] = []  # indices (into `kept`) of surviving import lines
    present_stems: set[str] = set()
    for line in lines:
        m = _IMPORT_LINE_RE.match(line)
        if m:
            stem = m.group("stem")
            if stem not in real_stems:
                removed += 1
                continue
            present_stems.add(stem)
            import_indices.append(len(kept))
        kept.append(line)

    # --- ADD: insert imports for real modules not yet present (completeness). ---
    # A schema file created AFTER data-init was generated would otherwise never be
    # registered. ADD mirrors `runtime_injector`'s own glob, which excludes
    # `_`-prefixed framework tables (`_forge_*`) — so we never *introduce* an
    # internal-table import the generator wouldn't emit. (PRUNE above still KEEPS an
    # existing `_forge_*` import when its file is real, so we don't strip one an app
    # legitimately has — we just don't add new ones.)
    added = 0
    if import_indices:
        # Determine the file's existing import indentation from the first import line.
        first_import_line = kept[import_indices[0]]
        indent = _IMPORT_LINE_RE.match(first_import_line).group("indent")

        missing = sorted(
            s for s in real_stems if s not in present_stems and not s.startswith("_")
        )
        if missing:
            # The array block spans from the first to the last surviving import line.
            # Build the full desired, sorted import set and rewrite the block region.
            block_start = import_indices[0]
            block_end = import_indices[-1]
            all_stems = sorted(present_stems | set(missing))
            new_block = [f'{indent}import("@/db/schema/{s}"),' for s in all_stems]
            kept = kept[:block_start] + new_block + kept[block_end + 1:]
            added = len(missing)
    # If we found NO import lines at all, we cannot confidently locate the array
    # block; PRUNE-only already handled above (removed stays as computed, add=0).

    new_text = "\n".join(kept)
    if new_text == original:
        return (False, removed, added)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new_text)
    except OSError as e:  # pragma: no cover - defensive
        logger.warning("schema_import_guard: could not write %s: %s", path, e)
        return (False, 0, 0)
    return (True, removed, added)


def reconcile_schema_imports(output_dir: str) -> dict:
    """Reconcile data-init / data-api schema imports to surviving schema files.

    Returns {"files_changed", "removed", "added"}. Never raises.
    """
    result = {"files_changed": 0, "removed": 0, "added": 0}
    try:
        schema_dir = os.path.join(output_dir, "src", "db", "schema")
        if not os.path.isdir(schema_dir):
            return result
        real_stems = _real_stems(schema_dir)

        for rel in _TARGETS:
            path = os.path.join(output_dir, rel)
            if not os.path.isfile(path):
                continue
            changed, removed, added = _reconcile_file(path, real_stems)
            result["removed"] += removed
            result["added"] += added
            if changed:
                result["files_changed"] += 1
    except Exception as e:  # noqa: BLE001 — never block generation on the guard
        logger.warning("schema_import_guard failed: %s", e)
    return result
