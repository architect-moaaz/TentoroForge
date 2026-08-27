#!/usr/bin/env python3
"""One-off migration script: backfill Blueprint for every project.

Usage:
    python -m scripts.migrate_project_to_blueprint [--force] [--dry-run] [<output_root>]

Defaults:
    output_root = <backend>/../output  (the standard forge output tree)

Iterates every top-level directory in `output_root`, treats each as a
project (project_id = directory name), and calls
`backfill_project_blueprint` on it. Idempotent — projects that
already have a blueprint are skipped unless `--force` is passed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _default_output_root() -> Path:
    """`<backend>/../output`. Callers can override on the CLI."""
    here = Path(__file__).resolve()
    return here.parent.parent.parent / "output"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output_root", nargs="?", default=None,
                   help="root directory containing per-project subdirs")
    p.add_argument("--force", action="store_true",
                   help="overwrite existing blueprints (destructive)")
    p.add_argument("--dry-run", action="store_true",
                   help="list what would change, do nothing")
    args = p.parse_args()

    root = Path(args.output_root) if args.output_root else _default_output_root()
    if not root.exists() or not root.is_dir():
        print(f"[migrate] output root does not exist: {root}", file=sys.stderr)
        return 2

    # Import lazily so `python -m scripts.…` works from repo root.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from services.blueprint_backfill import backfill_project_blueprint

    total = 0
    created = 0
    skipped = 0
    errors = 0

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        project_id = entry.name
        total += 1

        if args.dry_run:
            has_bp = (entry / ".forge" / "blueprint.json").exists()
            status = "skip (has blueprint)" if has_bp and not args.force \
                else "would backfill"
            print(f"  {project_id}: {status}")
            continue

        try:
            r = backfill_project_blueprint(
                project_id=project_id, output_dir=str(entry),
                force=args.force,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  {project_id}: ERROR — {exc!r}", file=sys.stderr)
            errors += 1
            continue

        if r.created:
            created += 1
            print(f"  {project_id}: created "
                  f"({r.entities} entities, {r.workflows} workflows, "
                  f"{r.pages} pages)")
        else:
            skipped += 1
            print(f"  {project_id}: skipped ({r.reason})")

    print()
    print(f"[migrate] {total} project(s) considered — "
          f"created {created}, skipped {skipped}, errors {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
