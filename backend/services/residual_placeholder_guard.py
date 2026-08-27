"""Catch template placeholders that survived into emitted JSX.

A `{{token}}` left in a `.tsx` file is not a placeholder to the compiler —
it is an expression container holding an object literal. `{{app_name}}` is
shorthand for `{app_name: app_name}`, so it typechecks as a reference to an
identifier that does not exist, and dies only when the page renders:

    ReferenceError: app_name is not defined
        at stringify (<anonymous>)      ← React serialising the object

That is a Vercel `next build` failure on `/_not-found`, observed in
production. Nothing else catches it: it compiles, it passes the delivery
gate, it passes the journey gate, and the first signal is a red deploy.

WHY A SEPARATE GUARD, NOT A FIX IN THE SUBSTITUTER
--------------------------------------------------
`edge_page_customizer` does the substitution and does it correctly — every
app in `output/` is clean. The failure mode is a substitution pass that
did not RUN (an older app, a skipped post-gen, a template added without a
matching substituter). A guard downstream of every writer is the only
thing that notices absence.

THE DISCRIMINATOR
-----------------
`{{...}}` is legitimate in JSX in attribute position — `style={{ height }}`
is an object with a shorthand property, and a colon-based test does NOT
catch it. Position is what separates the two:

    style={{ height }}        attribute value  — preceded by `=`   → legal
    Return to {{app_name}}    JSX text         — not preceded by `=` → broken

So the rule is: strip line comments, strip quoted strings (the workflow
runtime legitimately carries `"{{binding}}"` inside string literals),
neutralise attribute position, and flag whatever `{{identifier}}` remains.

Validated against 8,612 emitted `.tsx` files across the whole output
corpus: zero false positives.

Scope is `.tsx` only. `.ts` files (engine.ts, ai.ts, node-io.ts…) carry
hundreds of `{{binding}}` occurrences inside strings and regexes by
design; they have no JSX and cannot fail this way.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# `{{ident}}` — a single bare identifier. A colon (`{{color:'red'}}`) means
# an object literal with explicit keys, which is ordinary JSX.
_TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

# Attribute position: `prop={{ ... }}`. Legal — neutralised before scanning.
_ATTR_RE = re.compile(r"=\s*\{\{")

# Quoted strings, including template literals. The workflow runtime and the
# renderer both carry binding syntax inside strings on purpose.
_QUOTED_RE = re.compile(r"""(['"`])(?:\\.|(?!\1).)*\1""")


def scan_text(text: str) -> list[dict]:
    """Residual placeholders in one file's source, as ``[{line, token, snippet}]``.

    Pure — no I/O. Empty list means the file is safe.
    """
    out: list[dict] = []
    for i, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.split("//", 1)[0]        # drop line comments
        line = _QUOTED_RE.sub("", line)     # drop string contents
        line = _ATTR_RE.sub("=<<attr", line)  # neutralise attribute position
        for m in _TOKEN_RE.finditer(line):
            out.append({
                "line": i,
                "token": m.group(1),
                "snippet": raw.strip()[:120],
            })
    return out


def scan_app(output_dir: str | Path) -> dict:
    """Scan every emitted ``.tsx`` under ``src/``.

    Returns ``{"findings": [...], "files": N, "scanned": N}``. Never raises —
    a guard that crashes the pipeline is worse than the bug it looks for.
    """
    root = Path(output_dir)
    src = root / "src"
    findings: list[dict] = []
    scanned = 0
    if not src.is_dir():
        return {"findings": [], "files": 0, "scanned": 0}

    for p in sorted(src.rglob("*.tsx")):
        if "node_modules" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001 — unreadable file is not this guard's problem
            continue
        scanned += 1
        for hit in scan_text(text):
            hit["file"] = str(p.relative_to(root))
            findings.append(hit)

    return {
        "findings": findings,
        "files": len({f["file"] for f in findings}),
        "scanned": scanned,
    }


def apply_residual_placeholder_guard(output_dir: str | Path) -> dict:
    """Scan, write ``contracts/placeholder-report.json``, log at the right level.

    The report is written even when clean, so a missing report means the
    guard did not run rather than found nothing — those two must never be
    indistinguishable.
    """
    root = Path(output_dir)
    res = scan_app(root)
    try:
        (root / "contracts").mkdir(parents=True, exist_ok=True)
        (root / "contracts" / "placeholder-report.json").write_text(
            json.dumps(res, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("residual_placeholder_guard: report write failed: %s", exc)

    if res["findings"]:
        by_token: dict[str, int] = {}
        for f in res["findings"]:
            by_token[f["token"]] = by_token.get(f["token"], 0) + 1
        logger.error(
            "residual_placeholder_guard: %d unsubstituted placeholder(s) in %d "
            "file(s) — THESE BREAK `next build` AT PRERENDER (%s). First: %s:%d",
            len(res["findings"]), res["files"],
            ", ".join(f"{k}x{v}" for k, v in sorted(by_token.items())),
            res["findings"][0]["file"], res["findings"][0]["line"],
        )
    else:
        logger.info("residual_placeholder_guard: clean (%d .tsx scanned)",
                    res["scanned"])
    return res
