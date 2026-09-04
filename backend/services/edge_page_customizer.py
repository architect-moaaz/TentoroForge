"""Spec C5 — Edge-page customizer.

Substitutes ``{{app_name}}``, ``{{app_initial}}``, ``{{home_route}}``
templates in the copied edge pages (``not-found.tsx``, ``error.tsx``,
``forbidden.tsx``, ``loading.tsx``, ``maintenance.tsx`` +
``components/EdgePageFrame.tsx``) with per-app values pulled from
project settings + nav-flow.

Pure text substitution — the edge pages already ship in a good visual
state; this pass makes their COPY app-specific.

Idempotent: re-running with the same values is a no-op. Values it
can't resolve (e.g. missing nav-flow) fall back to sensible defaults
so the page still renders text like "Return to your app".
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# Every file that contains {{app_name}} / {{app_initial}} / {{home_route}}.
_EDGE_FILES: tuple[str, ...] = (
    "src/app/not-found.tsx",
    "src/app/error.tsx",
    "src/app/forbidden.tsx",
    "src/app/loading.tsx",
    "src/app/maintenance.tsx",
    "src/components/EdgePageFrame.tsx",
)

_TOKEN_RE = re.compile(r"\{\{([a-z_][a-z0-9_]*)\}\}", re.IGNORECASE)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _derive_app_name(output_dir: Path) -> str:
    """Read the app's human name in preference order.

    1. ``src/contracts/design-spec.json`` → ``identity.name`` (rare)
    2. ``src/contracts/plan.json`` → ``app_name`` / ``name``
    3. package.json ``name`` (kebab-case → Title Case)
    4. output-dir basename → Title Case
    """
    for rel, key in (
        ("src/contracts/design-spec.json", "name"),
        ("src/contracts/plan.json", "app_name"),
        ("src/contracts/plan.json", "name"),
    ):
        data = _read_json(output_dir / rel)
        if isinstance(data, dict):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    pkg = _read_json(output_dir / "package.json")
    if isinstance(pkg, dict) and isinstance(pkg.get("name"), str):
        return _title_case(pkg["name"])
    return _title_case(output_dir.name)


def _title_case(slug: str) -> str:
    parts = re.split(r"[\s_\-]+", slug.strip())
    return " ".join(p[:1].upper() + p[1:] for p in parts if p) or "App"


def _initial(app_name: str) -> str:
    for c in app_name:
        if c.isalnum():
            return c.upper()
    return "•"


def _is_linkable(route: object) -> bool:
    """Whether `route` is a URL, not a route pattern.

    `/survey/[slug]` is a template — Next's app router refuses it as a `Link`
    href and throws at runtime ("Dynamic href found in <Link> while using the
    /app router"). It reached an error page because it was simply the first
    route in nav-flow, and this function took the first route it found.

    An app whose only pages are detail routes has no home to point at, so the
    caller falls back to `/` rather than linking to a pattern.
    """
    return (isinstance(route, str) and route.startswith("/")
            and "[" not in route and "]" not in route)


def _derive_home_route(output_dir: Path) -> str:
    """First LINKABLE route from nav-flow, or the shell's home entry, or ``/``."""
    nav = _read_json(output_dir / "src/contracts/nav-flow.json")
    if isinstance(nav, dict):
        for candidate in (
            nav.get("home"),
            nav.get("entry"),
            nav.get("root"),
        ):
            if _is_linkable(candidate):
                return str(candidate)
        entries = nav.get("entries") or nav.get("pages")
        if isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict):
                    for k in ("route", "path", "href"):
                        if _is_linkable(e.get(k)):
                            return str(e[k])
    shell = _read_json(output_dir / "src/schemas/shell.json")
    if isinstance(shell, dict):
        menu = shell.get("menu") or []
        if isinstance(menu, list):
            for item in menu:
                if isinstance(item, dict):
                    v = item.get("navigate") or item.get("route")
                    if _is_linkable(v):
                        return str(v)
    return "/"


def _substitute(text: str, subs: dict[str, str]) -> str:
    def _sub(m: re.Match) -> str:
        key = m.group(1).lower()
        v = subs.get(key)
        return v if isinstance(v, str) else m.group(0)
    return _TOKEN_RE.sub(_sub, text)


def customize_edge_pages(
    output_dir: str,
    *,
    app_name: str | None = None,
    home_route: str | None = None,
) -> dict:
    """Rewrite every edge-page file in place. Returns ``{files, tokens_replaced}``.

    Args:
        output_dir: generated app root.
        app_name: override for the app's human name. Otherwise derived
            from design-spec / plan / package.json / dir name.
        home_route: override for the "Return to X" link. Otherwise
            derived from nav-flow / shell / defaults to ``/``.

    Flag-gated on ``FORGE_POLISH_EDGE_PAGES`` when the caller wants an
    explicit opt-in; ``customize_edge_pages`` itself always runs when
    called — the pipeline is the flag site.
    """
    root = Path(output_dir)
    if not root.is_dir():
        return {"files": 0, "tokens_replaced": 0}

    name = app_name or _derive_app_name(root)
    home = home_route or _derive_home_route(root)
    subs = {
        "app_name": name,
        "app_initial": _initial(name),
        "home_route": home,
    }

    files_changed = 0
    total_replaced = 0
    for rel in _EDGE_FILES:
        p = root / rel
        if not p.is_file():
            continue
        try:
            original = p.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[edge-pages] read failed for %s: %s", p, exc)
            continue
        # Count only tokens we actually know how to substitute.
        matches = [m for m in _TOKEN_RE.finditer(original) if m.group(1).lower() in subs]
        if not matches:
            continue
        rewritten = _substitute(original, subs)
        if rewritten != original:
            try:
                p.write_text(rewritten, encoding="utf-8")
                files_changed += 1
                total_replaced += len(matches)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[edge-pages] write failed for %s: %s", p, exc)

    return {"files": files_changed, "tokens_replaced": total_replaced,
            "app_name": name, "home_route": home}


def is_enabled() -> bool:
    """Read the rollout flag. Default ON: the standalone-app template
    ships edge pages with literal ``{{app_name}}`` placeholders, which
    are INVALID JSX until substituted — `next build` fails prerendering
    /_not-found with "ReferenceError: app_name is not defined" (broke
    every Vercel publish while this defaulted off). Substitution is a
    correctness requirement, not polish; the flag remains only as an
    emergency off-switch."""
    return os.getenv("FORGE_POLISH_EDGE_PAGES", "1").strip().lower() in ("1", "true", "yes", "on")


__all__ = ["customize_edge_pages", "is_enabled"]
