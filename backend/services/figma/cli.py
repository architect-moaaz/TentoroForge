"""Extract a design reference from a real Figma file, from a terminal.

Not the product surface — §41 and §108 describe that, and it is a Connect
Figma flow in a web workspace. This exists so the extraction can be driven
against a live file before any of that is built, which is the only way to find
out whether the tool payloads are the shape this package assumes.

    export FIGMA_PAT=figd_...
    python3 -m services.figma.cli 'https://figma.com/design/<key>/<name>?node-id=1-2'

The token is read from the environment by :class:`EnvSecretResolver` and never
printed, never written to the summary, and never stored (§42). ``--json``
writes the full reference to a file so the next stage can be developed against
a recorded extraction instead of re-billing the MCP on every run.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:  # `python3 -m` from the repo root
    sys.path.insert(0, str(BACKEND))

from services.figma.credentials import (  # noqa: E402
    EnvSecretResolver, FigmaCredential, FigmaCredentialError,
)
from services.figma.gateway import (  # noqa: E402
    DEFAULT_ENDPOINT, FigmaGateway, FigmaGatewayError,
)
from services.figma.reference import DesignReference, extract  # noqa: E402
from services.figma.url import parse  # noqa: E402


def render(ref: DesignReference) -> str:
    """§50's opener: what was found, before what is still unknown."""
    counts = ref.summary()
    lines = [
        f"Figma file {ref.target.describe()}",
        "",
        f"  {counts['screens']} screens ({counts['frames']} frames total)",
        f"  {counts['components']} components",
        f"  {counts['interactions']} prototype interactions",
        f"  {counts['colorTokens']} colour tokens, "
        f"{counts['typographyTokens']} typography tokens",
        "",
        "Screens",
    ]
    for screen in ref.screens:
        mark = " " if screen.looks_like_screen else "~"
        size = f"{int(screen.width)}x{int(screen.height)}" if screen.width else "-"
        labels = len((screen.structure or {}).get("labels") or [])
        img = "img" if screen.image else "   "
        lines.append(
            f"  {mark} {screen.node_id:<10} {screen.name[:38]:<38} "
            f"{size:>10}  {img}  {labels:>3} labels"
        )

    if ref.gaps:
        # §102 — a thin reference must look thin. These are what the design
        # could not tell us, and each one is a clarification Smith owes the
        # user before the DAG builds against it (§48, §50).
        lines += ["", "Gaps — what the design does not answer"]
        lines += [f"  - {g}" for g in ref.gaps]
    return "\n".join(lines)


def _as_dict(ref: DesignReference) -> dict:
    out = dataclasses.asdict(ref)
    # The rendered frames are megabytes of base64 and unreadable in a diff.
    for screen in out.get("screens", []):
        if screen.get("image"):
            screen["image"] = f"<{len(screen['image'])} bytes>"
    return out


async def _run(args) -> int:
    target = parse(args.url)
    if target is None:
        print(f"not a Figma URL: {args.url}", file=sys.stderr)
        return 2

    gateway = FigmaGateway(
        credential=FigmaCredential(ref=args.token_env),
        resolver=EnvSecretResolver(),
        endpoint=args.endpoint,
        timeout_s=args.timeout,
    )

    try:
        ref = await extract(
            gateway, target,
            max_screens=args.max_screens,
            with_images=not args.no_images,
        )
    except FigmaCredentialError as exc:
        print(f"credential: {exc}", file=sys.stderr)
        return 3
    except FigmaGatewayError as exc:
        print(f"figma {exc.kind}: {exc.detail}", file=sys.stderr)
        return 4

    print(render(ref))

    if args.json:
        args.json.write_text(json.dumps(_as_dict(ref), indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    calls = gateway.calls
    failed = [c for c in calls if not c.ok]
    print(f"\n{len(calls)} Figma calls, {len(failed)} failed, "
          f"{sum(c.duration_ms for c in calls)}ms total")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m services.figma.cli",
        description="Extract a design reference from a Figma file (PRD §41-55).",
    )
    parser.add_argument("url", help="Figma design URL")
    parser.add_argument("--token-env", default="FIGMA_PAT",
                        help="environment variable holding the PAT (default: FIGMA_PAT)")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                        help=f"Figma MCP endpoint (default: {DEFAULT_ENDPOINT})")
    parser.add_argument("--max-screens", type=int, default=40)
    parser.add_argument("--no-images", action="store_true",
                        help="skip frame renders; faster, but drops the §53 visual reference")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--json", type=Path, help="write the full reference here")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
