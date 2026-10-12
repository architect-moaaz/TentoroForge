"""`python -m services.engineer <output_dir> [--minutes N] [--name X]`

Build an approved definition feature by feature, saying each step as it
goes, and print what was proven at the end. The way step 2 of the plan is
run on copies of real apps, beside today's pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
import time


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="services.engineer")
    ap.add_argument("output_dir")
    ap.add_argument("--minutes", type=float, default=0, help="time budget; 0 means none")
    ap.add_argument("--name", default="", help="the application's name, for what is said")
    ap.add_argument("--request", default="", help="the person's words, for the authors")
    args = ap.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv()
    from services.engineer.build import build

    t0 = time.time()

    def emit(kind: str, data: dict) -> None:
        if kind in ("message", "state"):
            print(f"[{round(time.time() - t0)}s] {kind}: {json.dumps(data, default=str)[:600]}", flush=True)

    out = build(args.output_dir, args.output_dir.rstrip("/") + "/app", emit=emit, description=args.request,
                budget_minutes=args.minutes, app_name=args.name)
    print(json.dumps({k: v for k, v in out.items() if k != "features"}, default=str))
    for f in out.get("features") or []:
        print(f"  {f['feature']} {f['name']}: {f.get('passed')} of {f.get('statements')} held; "
              f"failing {f.get('failing') or '-'}; untried {f.get('untried') or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
