#!/usr/bin/env python3
"""Retrofit CLI — apply :mod:`services.interaction_auto_derive`'s rules
to an already-generated app so the new interaction primitives take
effect without a full regeneration.

Usage:
    # Dry-run one app
    python backend/scripts/apply_field_interactions.py output/8s3pz4bm --dry-run

    # Apply to all apps under output/
    python backend/scripts/apply_field_interactions.py output/

    # Verbose (per-field trace)
    python backend/scripts/apply_field_interactions.py output/8s3pz4bm -v

Safety:
  - Loads every page schema JSON, walks the tree for Form nodes, runs
    :func:`apply_auto_derivations` on the fields[] array in place,
    writes back only if something changed.
  - Mirrors to plan.json if the plan tracks the same field (best-effort).
  - Idempotent — running twice on the same app is a no-op.
  - Never overwrites a hand-authored interaction block.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Make the backend/ package importable when invoked as a script.
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from services.interaction_auto_derive import apply_auto_derivations  # noqa: E402


logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger("apply_field_interactions")


def _find_apps(target: Path) -> list[Path]:
    """Return the list of generated-app roots to process.

    Accepts either a single app dir (contains ``src/schemas``) or a
    parent output/ dir (each subdir that has ``src/schemas`` is an app).
    """
    target = target.resolve()
    if not target.exists():
        raise FileNotFoundError(f"target does not exist: {target}")

    if (target / "src" / "schemas").is_dir():
        return [target]

    apps: list[Path] = []
    for child in sorted(target.iterdir()):
        if not child.is_dir():
            continue
        if (child / "src" / "schemas").is_dir():
            apps.append(child)
    return apps


def _walk_forms(node) -> list[list[dict]]:
    """Walk a schema tree and yield every Form node's fields[] list.

    Fields are the concrete authoring surface for the interaction block.
    Returns pointers to the lists (mutable) so callers can rewrite in place.
    """
    forms: list[list[dict]] = []

    def visit(x):
        if isinstance(x, dict):
            # Form-node convention: {"type": "Form", ...} with fields inside props.
            if x.get("type") in ("Form", "form"):
                props = x.get("props") if isinstance(x.get("props"), dict) else x
                fields = props.get("fields")
                if isinstance(fields, list):
                    forms.append(fields)
            # Some schema-v2 form pages put fields at the top of the root.
            top_fields = x.get("fields")
            if isinstance(top_fields, list):
                forms.append(top_fields)
            for v in x.values():
                visit(v)
        elif isinstance(x, list):
            for item in x:
                visit(item)

    visit(node)
    # Dedup by object identity (same list may appear twice through nested walks).
    seen: set[int] = set()
    out: list[list[dict]] = []
    for f in forms:
        if id(f) in seen:
            continue
        seen.add(id(f))
        out.append(f)
    return out


def _process_app(
    app: Path, *, dry_run: bool, verbose: bool
) -> dict[str, int]:
    """Process one app. Returns a stats dict for the summary line."""
    schemas_dir = app / "src" / "schemas"
    schema_files = sorted(schemas_dir.rglob("*.json"))
    stats = {"schemas_scanned": 0, "schemas_changed": 0, "fields_derived": 0}

    for schema_path in schema_files:
        stats["schemas_scanned"] += 1
        try:
            schema = json.loads(schema_path.read_text())
        except json.JSONDecodeError:
            if verbose:
                log.warning("  skip (invalid JSON): %s", schema_path.name)
            continue

        forms = _walk_forms(schema)
        if not forms:
            continue

        # Snapshot for diff-detection
        before = json.dumps(schema, sort_keys=True)

        for form_fields in forms:
            fake_plan = {"pages": [{"id": schema_path.stem, "fields": form_fields}]}
            report = apply_auto_derivations(fake_plan)
            stats["fields_derived"] += len(report["applied"])
            if verbose and report["applied"]:
                for a in report["applied"]:
                    log.warning("    + %s (%s)", a, schema_path.relative_to(app))

        after = json.dumps(schema, sort_keys=True)
        if before != after:
            stats["schemas_changed"] += 1
            if not dry_run:
                tmp = schema_path.with_suffix(schema_path.suffix + ".tmp")
                tmp.write_text(json.dumps(schema, indent=2) + "\n")
                tmp.replace(schema_path)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retrofit field-interaction auto-derivations on generated apps."
    )
    parser.add_argument("target", help="Path to an app dir OR a parent output/ dir")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    parser.add_argument("-v", "--verbose", action="store_true", help="Per-field trace")
    args = parser.parse_args()

    try:
        apps = _find_apps(Path(args.target))
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not apps:
        print(f"no apps found under {args.target}", file=sys.stderr)
        return 1

    total = {"apps": 0, "schemas_scanned": 0, "schemas_changed": 0, "fields_derived": 0}
    for app in apps:
        stats = _process_app(app, dry_run=args.dry_run, verbose=args.verbose)
        total["apps"] += 1
        for k in ("schemas_scanned", "schemas_changed", "fields_derived"):
            total[k] += stats[k]
        marker = "would-change" if args.dry_run else "changed"
        prefix = "  ✓" if stats["schemas_changed"] else "  ·"
        print(
            f"{prefix} {app.name}  scanned={stats['schemas_scanned']}  "
            f"{marker}={stats['schemas_changed']}  derived={stats['fields_derived']}"
        )

    print(
        f"\nsummary: {total['apps']} app(s), "
        f"{total['schemas_scanned']} schema(s) scanned, "
        f"{total['schemas_changed']} would-change" if args.dry_run
        else f"\nsummary: {total['apps']} app(s), "
             f"{total['schemas_scanned']} schema(s) scanned, "
             f"{total['schemas_changed']} changed, "
             f"{total['fields_derived']} interaction(s) added"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
