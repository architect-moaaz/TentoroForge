"""Smith writes code — through the build's own seam (§0 of `2026-09-24-smith-as-a-loop`).

`write_page_code` is the first write primitive: the loop, having READ a page
(`read_page_code`, `grep`), says precisely what its code should do differently,
and the UI engineer that wrote the page in the first place rewrites it. It is
not a verb. Verbs are the vocabulary of the first interpretation call — the
classifier's — and this is the loop's: it exists so that a change no verb
describes ("accepted rentals should count as needing attention", "put the
filters above the list") is still a change Smith makes, rather than one of
`limits.py`'s honest refusals.

THE SAME SEAM AS THE BUILD, WHICH IS WHAT MAKES IT ALLOWED. §5 of the spec
refuses "a free-form file-edit tool", and this is not one: nothing here opens
`view.tsx`. `compose.recode_page` briefs `ui_engineer`, whose code goes to
`tsc` against the typed SDK for `COMPILE_ROUNDS`, and what compiles becomes a
`pageCode` row through `apply_agent_result` and one commit — exactly the path
a page takes during a build. The Blueprint stays the record; `view.tsx` is
projected from it afterwards, as always.

WHAT THE COMPILER SAYS IS A FINDING. A page that does not compile after three
rounds used to end the turn as `needs_user` with the error in a chat bubble.
It is a proof — the one oracle the build trusts most — and so it is handed
back as `finding`, and the loop, which can now read the error and the code,
gets to try again with a better brief. The same for a contract refusal and
for a widget the new code does not draw.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: (name, description, {argument: type}). Written for the model choosing it.
WRITES: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("write_page_code",
     "Rewrite the React of a page that EXISTS, by route, to do what `brief` "
     "says. Use it after reading the page: the brief names the concrete "
     "change — the constant, the component, the query, the layout order — in "
     "terms of the code you read, not the user's sentence. The page is "
     "rewritten by the engineer that wrote it, type-checked against the SDK, "
     "and committed as one version. The compiler's verdict comes back to you. "
     "For a page that does not exist yet, `compose_route`.",
     {"route": "string", "brief": "string"}),
)

WRITE_NAMES: frozenset[str] = frozenset(name for name, _d, _a in WRITES)


def write_page_code(output_dir: str, route: str, brief: str, *,
                    reasoning: Any = None) -> dict:
    """Rewrite one page's code to `brief`. Returns
    `{applied, said, finding, touched, version}` — `finding` set when an
    oracle refused, in its words; `said` for the person either way."""
    from services.blueprint.service import BlueprintService
    from services.smith.compose import ComposeError, _page_for_route, code_row, coded_app, recode_page

    route = (route or "").strip()
    brief = (brief or "").strip()
    if not route or not brief:
        return _finding(f"`write_page_code` needs both `route` and `brief`; got route={route!r}.")
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return _finding("This project has no Blueprint, so there is no page to rewrite.")
    page = _page_for_route(svc.doc, route)
    if page is None:
        routes = ", ".join(str(p.get("route")) for p in svc.doc.get("pages") or []
                           if isinstance(p, dict))[:500]
        return _finding(f"There is no page at `{route}`. Routes: {routes}. "
                        "A page that does not exist is created with `compose_route`.")
    if code_row(svc.doc, str(page.get("id"))) is None and not coded_app(svc.doc):
        return _finding(f"`{route}` is not written as code — it renders from its layout "
                        "tree, which `compose_route` and `add_widgets` change.")
    app_root = str(Path(output_dir) / "app")
    try:
        out = recode_page(svc, route, app_root=app_root, request=brief, reasoning=reasoning)
    except ComposeError as exc:
        # The compiler's (or the contract's) own words, unparaphrased.
        return _finding(f"{route} was not changed: {exc}")
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] write_page_code %s failed", route)
        return _finding(f"{route} was not changed — {type(exc).__name__}: {exc}")
    if not out.get("applied"):
        return _finding(f"{route} was not changed: {out.get('reason') or 'the change was refused'}")
    missing = [str(m) for m in out.get("missing") or []]
    version = int(out.get("version") or 0)
    said = f"Rewrote **{route}** (version {version})."
    if missing:
        return {"applied": True, "said": said, "touched": list(out.get("committed") or []),
                "version": version,
                "finding": (f"{route} was rewritten (version {version}), but the new code does "
                            f"not draw: {', '.join(missing)}. The brief asked for it; the code "
                            "does not show it.")}
    return {"applied": True, "said": said, "finding": "",
            "touched": list(out.get("committed") or []), "version": version}


def _finding(text: str) -> dict:
    return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}


def run(name: str, args: dict, *, output_dir: str, reasoning: Any = None) -> dict:
    """Carry out one write. The result's `finding` is the observation when an
    oracle refused; `said` is what the person is told."""
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    if name == "write_page_code":
        return write_page_code(output_dir, str(args.get("route") or ""),
                               str(args.get("brief") or ""), reasoning=reasoning)
    raise KeyError(name)


__all__ = ["WRITES", "WRITE_NAMES", "run", "write_page_code"]
