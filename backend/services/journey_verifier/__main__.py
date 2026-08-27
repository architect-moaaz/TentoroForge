"""CLI: `python -m services.journey_verifier <output_dir> [--base-url URL] [--emit-only]`

Convenience wrapper for running the verifier from a shell. Prints a compact
summary and exits non-zero on any failing journey — plays nicely as a
warn-mode gate in the pipeline or a strict CI step.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (
    collect_needed_slugs,
    emit,
    extract,
    resolve_fixtures,
    run_journey_suite,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="journey_verifier")
    p.add_argument("output_dir", type=Path)
    p.add_argument("--base-url", default="http://localhost:3000")
    p.add_argument("--repo-root", type=Path,
                   default=Path(__file__).resolve().parents[3])
    p.add_argument("--emit-only", action="store_true",
                   help="Extract + emit files; skip running Playwright.")
    p.add_argument("--boot-timeout", type=int, default=30)
    p.add_argument("--json", action="store_true",
                   help="Emit JSON result to stdout instead of the text summary.")
    args = p.parse_args(argv)

    output_dir = args.output_dir.resolve()
    if not output_dir.exists():
        print(f"error: {output_dir} does not exist", file=sys.stderr)
        return 2

    spec = extract(output_dir, base_url=args.base_url)
    slugs = collect_needed_slugs(spec)
    spec.fixtures = resolve_fixtures(slugs, output_dir, args.repo_root)
    journeys_dir = emit(spec, output_dir)

    print(f"→ archetype: {spec.archetype}")
    print(f"→ journeys : {len(spec.journeys)}")
    for j in spec.journeys:
        print(f"    · {j.slug}: {j.name} ({len(j.steps)} steps)")
    print(f"→ fixtures : {list(spec.fixtures.keys()) or '(none needed)'}")
    print(f"→ emitted  : {journeys_dir}")

    if args.emit_only:
        return 0

    print(f"→ running against {args.base_url}...")
    result = run_journey_suite(
        output_dir,
        base_url=args.base_url,
        boot_timeout_s=args.boot_timeout,
        playwright_cwd=args.repo_root,
    )

    if args.json:
        print(json.dumps({
            "ok": result.ok,
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "duration_ms": result.duration_ms,
            "error": result.error,
            "journeys": [
                {
                    "slug": j.slug, "name": j.name, "status": j.status,
                    "duration_ms": j.duration_ms, "failure": j.failure,
                    "failing_step": j.failing_step,
                } for j in result.journeys
            ],
        }, indent=2))
    else:
        print()
        print("─" * 60)
        for j in result.journeys:
            mark = "✓" if j.status == "passed" else "✗"
            print(f" {mark}  [{j.status:8}] {j.slug} · {j.name} ({j.duration_ms} ms)")
            if j.failing_step:
                print(f"      ↳ failed at: {j.failing_step}")
            if j.failure:
                first_line = j.failure.split("\n")[0][:140]
                print(f"      ↳ error   : {first_line}")
        print("─" * 60)
        print(f"passed {result.passed}/{result.total}  in {result.duration_ms} ms")
        if result.error:
            print(f"harness error: {result.error}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
