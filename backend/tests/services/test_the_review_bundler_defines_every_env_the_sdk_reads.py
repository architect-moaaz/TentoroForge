"""The page review renders each page with esbuild in a headless browser, where `process` does not exist.

Next inlines `process.env.NEXT_PUBLIC_*` when it builds an app; the review bundler (static/react-jit.mjs) does not, so every name
the client SDK reads at load time must be defined there. One that is not turns every page importing that module into a blank
screen ("process is not defined"), scored 1/10 by the reviewer and rewritten again and again for nothing — found building a fleet
app end to end (2026-11-18), where the pages with a map were rejected over and over and the writer's calls were the biggest cost."""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SDK = BACKEND / "templates" / "app-foundation" / "src" / "sdk"
JIT = (BACKEND / "static" / "react-jit.mjs").read_text(encoding="utf-8")
SERVER_ONLY = {"server.ts"}   # runs in the server, where `process` exists


def _reads(path: Path) -> set[str]:
    return set(re.findall(r"process\.env\.([A-Z][A-Z0-9_]*)", path.read_text(encoding="utf-8")))


def test_every_env_name_the_client_sdk_reads_is_defined_for_the_review_bundler():
    missing: dict[str, set[str]] = {}
    for f in sorted(list(SDK.glob("*.ts")) + list(SDK.glob("*.tsx"))):
        if f.name in SERVER_ONLY:
            continue
        gone = {n for n in _reads(f) if f'"process.env.{n}"' not in JIT}
        if gone:
            missing[f.name] = gone
    assert not missing, f"the review bundler does not define these, so a page importing them renders blank: {missing}"


def test_the_map_names_are_the_ones_that_failed():
    for n in ("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "NEXT_PUBLIC_MAP_PROVIDER", "NEXT_PUBLIC_MAP_STYLE"):
        assert f'"process.env.{n}"' in JIT, n


def test_an_unset_provider_and_style_stay_undefined_as_in_a_real_app():
    """`?? "google"` and `|| DEFAULT_STYLE` must see undefined, not an empty string, or the defaults would never apply."""
    assert '"process.env.NEXT_PUBLIC_MAP_PROVIDER": "undefined"' in JIT
    assert '"process.env.NEXT_PUBLIC_MAP_STYLE": "undefined"' in JIT
