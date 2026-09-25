"""Every page looked at as it is written — by a reviewer, on a screenshot.

A page that compiles can still be a poor page, and the compiler will never
say so. Until now the only look came after the whole application was
assembled (`page_review`: boot, database, dev server), as an opt-in verb;
the pages a build shipped were the pages nobody had seen. This looks at
each page the moment it compiles, inside the writer's own loop:

1. the candidate is bundled with the editor's JIT — sample data in place of
   the database, the app's own Tailwind, no dev server (`install` precedes
   `page_code`, so esbuild is there);
2. headless Chromium renders it at a desk and a phone width and
   screenshots both, keeping every error the page threw;
3. the reviewer sees the screenshots with the page's contract and the app's
   direction (and the reference images the user attached, as the bar) and
   returns a score, what works and what to change;
4. a `revise` goes back to the writer as one more round, with the review as
   its brief; the better-scoring version is what the page keeps.

A look can only ever improve a page: what the toolchain cannot do (no
Chromium, no esbuild, a bundle that fails) is logged and the page is
accepted as the compiler accepted it. Bounded: `LOOKS` looks per page.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Looks per page: one at the compiled page, one at its rewrite.
LOOKS = 2
#: Viewports the reviewer is shown — a desk and a phone.
VIEWPORTS: dict[str, tuple[int, int]] = {"desktop": (1280, 900), "mobile": (390, 844)}
#: Renders at once per process: Chromium is ~150 MB each, and twelve pages
#: compose in parallel.
_RENDERS = threading.BoundedSemaphore(4)


class LookUnavailable(RuntimeError):
    """The page could not be looked at here — the reason is the message."""


def frame_html(css: str, vendor_js: str, page_js: str) -> str:
    """One document of the page: the editor canvas's frame, self-contained."""
    return ('<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<style id="forge-page-css">{css}</style></head><body><div id="root"></div>'
            '<script>window.__forgeLookErrors=[];window.addEventListener("message",function(e){'
            'var d=e.data;if(d&&d.type==="forge-editor:error"&&d.payload)window.__forgeLookErrors.push('
            'String(d.payload.file||"")+": "+String(d.payload.message||""));});</script>'
            f'<script>{vendor_js}</script><script>{page_js}</script></body></html>')


def render(doc: dict, page: dict, app_root: Path, load: str, view: str, out_dir: Path) -> dict[str, Any]:
    """Bundle the candidate and screenshot it at every viewport.

    ``{"shots": {name: path}, "errors": [...]}`` — the errors are what the
    page itself threw (a render error, a failed load), proved in the browser."""
    from services.react_editor.jit import LOOK_DIR, bundle_source
    from services.react_editor.service import EditorError, Project

    project = Project(root=app_root.parent, app_root=app_root)
    try:
        bundle = bundle_source(project, doc, page, view, load)
    except EditorError as exc:
        raise LookUnavailable(f"bundle: {exc}") from exc
    finally:
        shutil.rmtree(app_root / LOOK_DIR / str(page.get("id")), ignore_errors=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover — depends on the machine
        raise LookUnavailable("playwright is not installed") from exc
    html = frame_html(bundle["css"], bundle["vendor"], bundle["js"])
    out_dir.mkdir(parents=True, exist_ok=True)
    shots: dict[str, str] = {}
    errors: list[str] = []
    with _RENDERS:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    for name, (w, h) in VIEWPORTS.items():
                        tab = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
                        tab.on("pageerror", lambda e: errors.append(f"view.tsx: {e}"))
                        tab.on("console", lambda m: errors.append(f"console: {m.text}")
                               if m.type == "error" and "favicon" not in m.text else None)
                        tab.set_content(html, wait_until="load")
                        try:
                            tab.wait_for_selector("#root > *", timeout=15000)
                        except Exception:  # noqa: BLE001 — an empty root is itself a finding
                            errors.append("view.tsx: nothing rendered within 15s")
                        tab.wait_for_timeout(700)
                        file = out_dir / f"{name}.png"
                        tab.screenshot(path=str(file), full_page=True)
                        shots[name] = str(file)
                        errors.extend(str(e) for e in (tab.evaluate("window.__forgeLookErrors") or []))
                        tab.close()
                finally:
                    browser.close()
        except LookUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — a browser that will not run is a machine fact
            raise LookUnavailable(f"browser: {type(exc).__name__}: {str(exc)[:200]}") from exc
    seen: list[str] = []
    for e in errors:
        if e not in seen:
            seen.append(e)
    return {"shots": shots, "errors": seen[:12]}


def judge(doc: dict, page: dict, look: dict, client: Any, *, references: list[Path] = ()) -> tuple[dict, Any]:
    """The reviewer's verdict on the screenshots. Returns the verdict and
    what the call cost, as `(usage, elapsed)`."""
    from services.blueprint.page_review import PASS_SCORE, REVIEW_SCHEMA, reviewer_system
    from services.blueprint.references import READ_FOR
    from services.blueprint.ui_engineer import _page_brief

    proved = "\n".join(f"- {e}" for e in look.get("errors") or []) or "(none)"
    names = list(look.get("shots") or {})
    user = ("The page's contract:\n```json\n" + json.dumps(_page_brief(doc, page), indent=1)
            + "\n```\nIt is rendered with sample data in place of the database — judge the design, "
            "the hierarchy and the behaviour it implies, not the rows.\n\n"
            f"What the browser proved broken:\n{proved}\n\n"
            + "The screenshots, in order: " + ", ".join(f"{n} ({VIEWPORTS[n][0]}px wide)" for n in names)
            + ". Judge both: a page that is right at a desk and broken on a phone does not pass.")
    images = [look["shots"][n] for n in names]
    if references:
        user += (f"\n\nThe last {len(references)} image(s) are what the user showed as the standard "
                 f"they want: {READ_FOR['page_look']}")
        images += [str(p) for p in references]
    t0 = time.monotonic()
    reply = client(system=reviewer_system(doc), user=user, schema=REVIEW_SCHEMA, images=images)
    body = json.loads(getattr(reply, "text", reply))
    body["broken"] = list(look.get("errors") or [])
    if body["broken"] or any(i.get("severity") == "high" for i in body.get("issues") or []) \
            or int(body.get("score") or 0) < PASS_SCORE:
        body["verdict"] = "revise"
    return body, (getattr(reply, "usage", None), time.monotonic() - t0)


def look_brief(verdict: dict) -> str:
    """The review as the writer's brief for its next round."""
    lines = [f"A reviewer looked at your page as it renders (desk and phone) and scored it "
             f"{verdict.get('score')}/10. Keep what works and fix every issue:"]
    for s in verdict.get("strengths") or []:
        lines.append(f"  + {s}")
    if verdict.get("broken"):
        lines.append("BROKEN — proved in the browser, fix every one first:")
        lines += [f"  ! {b}" for b in verdict["broken"]]
    for i in verdict.get("issues") or []:
        lines.append(f"  - [{i.get('severity')}] {i.get('where')}: {i.get('problem')} → {i.get('fix')}")
    return "\n".join(lines)


def rank(verdict: dict) -> tuple[int, int]:
    """Nothing proven broken first, then the score — the order `page_review`
    keeps the best version by."""
    return (0 if verdict.get("broken") else 1, int(verdict.get("score") or 0))


def look_at(doc: dict, page: dict, app_root: Path, load: str, view: str, client: Any, *,
            attempt: int = 1) -> tuple[dict, Any]:
    """Render, then judge. Raises LookUnavailable when this machine cannot."""
    from services.blueprint import references

    out_dir = Path(app_root).parent / ".forge" / "look" / str(page.get("id")) / f"look-{attempt}"
    look = render(doc, page, Path(app_root), load, view, out_dir)
    shown = references.paths(app_root.parent) if getattr(client, "accepts_images", True) else []
    verdict, spent = judge(doc, page, look, client, references=shown)
    verdict["shots"] = look["shots"]
    verdict["attempt"] = attempt
    # WHAT WAS LOOKED AT AND WHAT WAS SAID, KEPT BESIDE THE SCREENSHOTS. The
    # accepted version is the only code the Blueprint keeps; without these a
    # reader cannot tell what the reviewer asked for or whether the rewrite
    # did it (the first trial's rewrite of a list page changed one border).
    try:
        (out_dir / "view.tsx").write_text(view, encoding="utf-8")
        (out_dir / "load.ts").write_text(load, encoding="utf-8")
        (out_dir / "verdict.json").write_text(json.dumps(verdict, indent=1), encoding="utf-8")
    except OSError:  # a record, never a gate
        pass
    logger.info("[page_look] %s look %d: %s %s/10, %d issue(s), %d broken", page.get("id"), attempt,
                verdict.get("verdict"), verdict.get("score"), len(verdict.get("issues") or []),
                len(verdict.get("broken") or []))
    return verdict, spent
