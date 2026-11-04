"""This application's own component kit — written once, composed by every page.

Every page used to be designed alone, by a writer optimising for correctness,
so two pages of one product agreed only by luck and each re-decided what a
panel, a row or a status chip looks like. The one move that turned a real
application from plain to designed (Criterion CARES, measured 2026-11-04) was a
person inventing a shared kit: 34 exports in one file, imported by 14 of its 22
pages. The pipeline had no stage that did that, and no generated application had
a single shared component of its own — `src/components/` held the platform's
files and three scaffold parts nothing imported.

So a node between the direction and the pages writes the app's parts: its page
head, its panel, its list row, its status pill, its empty state — and the words
and numbers it formats, which matter as much. In that same measurement the
formatters were reached for as often as the components (`money` 8 pages,
`statusWord` 6, `dueWords` 5), because what makes a product feel made is every
screen saying "3 days overdue" in the same words and the same colour.

THE KIT MAY NAME COLOURS AND A PAGE MAY NOT. A page is held to the semantic
token classes, which is why a palette actually applies and contrast holds; held
to them alone, though, a writer can only produce a correctly recoloured version
of the same app. The kit is the exception, bounded the way a drawn page's is
(`ui_engineer._drawn_findings`): its colours are enumerated in advance, in
`componentKit.palette`, projected to `--kit-*` beside the design tokens. A part
writes `bg-[var(--kit-wash)]`, never a hex of its own, so the whole kit can be
read, contrast-checked and rethemed in one place.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Where the app's own parts live, beside the platform's components.
KIT_DIR = Path("src/components/app")
#: The import prefix a page uses for them.
KIT_IMPORT = "@/components/app"
#: Written from `componentKit.palette`; the parts import it for inline styles.
PALETTE_FILE = "palette.ts"
#: Found by their marker, so a hand-written part is never swept away — the same
#: bargain `app_sdk.CODE_PAGE_MARKER` makes for a generated route.
KIT_MARKER = "// forge:app-kit"

#: How many times the kit is handed back its own compiler errors.
COMPILE_ROUNDS = 3

#: Placeholder shapes `assembly.scaffold_tokens` hunts for across the whole app
#: `src/`. One of these in a kit file fails `refuse_unfilled_scaffold` and with
#: it the entire build, so the kit is refused them at the door instead.
_SCAFFOLD_TOKEN = re.compile(r"__[A-Z][A-Z_]+__|\{\{[a-z_]+\}\}")
_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_KIT_VAR = re.compile(r"--kit-([a-z0-9-]+)")
#: The kit is held to the page writer's rule for this too
#: (`ui_engineer.escaped_in_jsx_text`): JSX text is not a JavaScript string, so
#: `\u00b7` reaches the screen as six characters. Stay's lead card shipped
#: "Nov 1 – Nov 1 \u00b7 0 nights" (2026-11-04) because the rule held pages and
#: the kit was outside it.


def _kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", str(name)).replace("_", "-").replace(" ", "-").lower()


def palette_of(doc: dict) -> dict[str, str]:
    """`{name: #rrggbb}` — only entries that are actually a colour."""
    raw = ((doc.get("componentKit") or {}).get("palette") or {})
    return {str(k): str(v).strip() for k, v in raw.items()
            if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v.strip())}


def palette_vars(doc: dict) -> list[str]:
    """`--kit-*` custom properties, for `tokens.css` beside the design tokens."""
    return [f"  --kit-{_kebab(k)}: {v};" for k, v in sorted(palette_of(doc).items())]


def parts_of(doc: dict) -> list[dict]:
    kit = doc.get("componentKit") or {}
    return [p for p in (kit.get("parts") or [])
            if isinstance(p, dict) and str(p.get("file") or "").strip() and p.get("code")]


def _filename(part: dict) -> str:
    """The part's file, as a bare name under the kit directory."""
    return Path(str(part.get("file"))).name


def exports_of(doc: dict) -> dict[str, list[str]]:
    """`{file stem: [exported names]}` — what the kit declares it exports,
    falling back to reading the code when it declares nothing."""
    out: dict[str, list[str]] = {}
    for part in parts_of(doc):
        names = [str(n).strip() for n in (part.get("exports") or []) if str(n).strip()]
        if not names:
            names = re.findall(r"export\s+(?:async\s+)?(?:function|const|type)\s+(\w+)",
                               str(part.get("code")))
        if names:
            out[Path(_filename(part)).stem] = names
    return out


# --------------------------------------------------------------------------- #
# What the page writer is handed
# --------------------------------------------------------------------------- #

def kit_vocabulary(doc: dict) -> str:
    """The kit as import lines, in the shape `_kit_exports()` already uses for
    the shadcn parts — so the page writer reads one list, not two dialects."""
    by_file = exports_of(doc)
    if not by_file:
        return ""
    purpose = {Path(_filename(p)).stem: str(p.get("purpose") or "") for p in parts_of(doc)}
    lines = []
    for stem in sorted(by_file):
        note = purpose.get(stem) or ""
        lines.append(f'  import {{ {", ".join(by_file[stem])} }} from "{KIT_IMPORT}/{stem}";'
                     + (f"   // {note}" if note else ""))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# On disk
# --------------------------------------------------------------------------- #

def _palette_module(doc: dict) -> str:
    colours = palette_of(doc)
    body = "".join(f'  {k}: "{v}",\n' for k, v in sorted(colours.items()))
    return (f"{KIT_MARKER}\n"
            "// This application's own colours, written from the Blueprint's\n"
            "// `componentKit.palette`. Also projected as `--kit-*` in tokens.css, which is\n"
            "// how a class names one (`bg-[var(--kit-wash)]`); this constant is for the\n"
            "// places a class cannot reach, like an SVG fill or a gradient stop.\n"
            "// Edit the Blueprint, not this file.\n"
            f"export const C = {{\n{body}}} as const;\n\n"
            "export type KitColour = keyof typeof C;\n")


def project_component_kit(doc: dict, app_root: str | Path) -> list[str]:
    """Write the kit under `src/components/app/`. Idempotent.

    Called twice by design: by the node that writes the kit, because
    `ui_engineer.typecheck` resolves `@/components/app/*` against the real tree
    and a page importing a file that is not yet on disk cannot compile; and
    again from the frontend projection, so a rebuild and an undo put it back.
    """
    root = Path(app_root)
    parts = parts_of(doc)
    if not parts and not palette_of(doc):
        return []
    out = root / KIT_DIR
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def put(name: str, content: str) -> None:
        path = out / name
        if not (path.exists() and path.read_text(encoding="utf-8") == content):
            path.write_text(content, encoding="utf-8")
        written.append(name)

    put(PALETTE_FILE, _palette_module(doc))
    for part in parts:
        code = str(part["code"])
        head = code if code.lstrip().startswith(KIT_MARKER) else f"{KIT_MARKER}\n{code}"
        put(_filename(part), head)

    # A part the kit no longer declares goes, so a renamed one does not linger
    # and a page cannot import yesterday's. Only ours — by the marker.
    for stale in out.glob("*.ts*"):
        if stale.name in written:
            continue
        try:
            if stale.read_text(encoding="utf-8").lstrip().startswith(KIT_MARKER):
                stale.unlink()
        except OSError:  # noqa: PERF203 — a file we cannot read is not ours to delete
            continue
    return [str(KIT_DIR / n) for n in written]


# --------------------------------------------------------------------------- #
# What the kit is held to
# --------------------------------------------------------------------------- #

def findings(doc: dict, parts: list[dict]) -> list[str]:
    """What the compiler cannot see and the kit's own bargain forbids."""
    from services.blueprint.ui_engineer import escaped_in_jsx_text
    out: list[str] = []
    named = {_kebab(k) for k in palette_of(doc)}
    for part in parts:
        name, code = _filename(part), str(part.get("code") or "")
        for token in sorted(set(_SCAFFOLD_TOKEN.findall(code))):
            out.append(f"{name}: carries `{token}`, which the build reads as an unfilled "
                       "scaffold placeholder and refuses — write the real text.")
        for hexed in sorted(set(_HEX.findall(code))):
            out.append(f"{name}: names the colour `{hexed}`. The kit's colours live in "
                       "`palette`, and reach the code as `var(--kit-<name>)` in a class or "
                       "`C.<name>` from ./palette — so the whole kit can be rethemed at once.")
        for used in sorted(set(_KIT_VAR.findall(code))):
            if used not in named:
                out.append(f"{name}: uses `--kit-{used}`, which `palette` does not declare.")
        if escaped_in_jsx_text(code):
            out.append(f"{name}: a `\\uXXXX` escape in JSX text or an attribute string is shown "
                       "literally — write the character itself (— · ₹), or {\"\\u2014\"} in braces.")
        if "@/sdk/server" in code or re.search(r"\bfetch\(", code):
            out.append(f"{name}: reads data. A kit part is given what to draw; the page loads it.")
        if re.search(r'^\s*"use client"|^\s*\'use client\'', code) is None \
                and re.search(r"\buse(State|Effect|Router|Memo|Callback)\b", code):
            out.append(f'{name}: uses a hook, so its first line must be "use client".')
    return out


def typecheck(app_root: str | Path, timeout: float = 180.0) -> list[str]:
    """Compile the kit where it lives, against the app's own tsconfig.

    The page check filters out every error outside the page's own three files —
    rightly, since the scaffold carries some — which means a type error inside a
    kit part would be dropped there and surface only at `next build`, after the
    pages that import it had already been written against it.
    """
    root = Path(app_root)
    if not (root / KIT_DIR).is_dir():
        return []
    tsc_path = shutil.which("tsc", path=str(root / "node_modules" / ".bin"))
    if not tsc_path:
        raise RuntimeError(f"no TypeScript compiler under {root} — install has not run")
    check = root / ".forge-check" / f"kit-{os.getpid()}-{threading.get_ident()}"
    check.parent.mkdir(parents=True, exist_ok=True)
    if check.exists():
        shutil.rmtree(check, ignore_errors=True)
    check.mkdir(parents=True)
    try:
        (check / "tsconfig.json").write_text(json.dumps({
            "extends": "../../tsconfig.json",
            "compilerOptions": {"incremental": False, "noEmit": True},
            "include": [f"../../{KIT_DIR.as_posix()}/**/*.ts",
                        f"../../{KIT_DIR.as_posix()}/**/*.tsx",
                        "../../next-env.d.ts", "../../src/types/**/*.d.ts"],
        }), encoding="utf-8")
        proc = subprocess.run([tsc_path, "-p", str(check / "tsconfig.json"), "--pretty", "false"],
                              cwd=str(root), capture_output=True, text=True,
                              encoding="utf-8", timeout=timeout)
    finally:
        shutil.rmtree(check, ignore_errors=True)
    # Only the kit's own files; the scaffold's modules are built with type
    # errors ignored and carry some, and the kit is not where they are fixed.
    marker = KIT_DIR.as_posix() + "/"
    errors: list[str] = []
    ours = False
    for line in (proc.stdout + proc.stderr).splitlines():
        where = line.split("(", 1)[0]
        if marker in where:
            errors.append(line[line.index(marker) + len(marker):])
            ours = True
        elif ours and line.startswith(" "):
            errors[-1] += " " + line.strip()
        else:
            ours = False
    return errors


# --------------------------------------------------------------------------- #
# Writing it
# --------------------------------------------------------------------------- #

#: THE PALETTE IS A LIST HERE AND A MAP IN THE BLUEPRINT. A structured reply
#: may not carry a free-form object: `{"additionalProperties": {"type":
#: "string"}}` is refused outright — "For 'object' type, 'additionalProperties:
#: object' is not supported" — and the node 400'd twice and wrote nothing
#: (Claimsdesk, 2026-11-04). Named entries instead, folded back into the map the
#: contract holds.
KIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["palette", "parts"],
    "properties": {
        "rationale": {"type": "string"},
        "palette": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["name", "value"],
                "properties": {"name": {"type": "string"},
                               "value": {"type": "string"}},
            },
        },
        "parts": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["file", "purpose", "exports", "code"],
                "properties": {
                    "file": {"type": "string"},
                    "purpose": {"type": "string"},
                    "exports": {"type": "array", "items": {"type": "string"}},
                    "code": {"type": "string"},
                },
            },
        },
    },
}

#: The parts a real designed application actually reached for, with how many of
#: its 14 kit-using pages imported each (Criterion CARES, measured 2026-11-04).
#: Named so the kit covers what pages need rather than what is easy to write —
#: the gaps are where that application's pages gave up and inlined their own
#: markup. Not a list to copy: this product's own set, in its own language.
_PARTS_SEEN = (
    ("the page frame — the ground, the gutter, the rhythm of space down a page", 12),
    ("the page head — eyebrow, title, subtitle and the one action", 11),
    ("the primary action, and the quiet one beside it", 11),
    ("a section panel — the container most of a page is made of", 10),
    ("the empty state, in this product's voice", 9),
    ("the status chip, with one tone per state of the thing", 9),
    ("a list row — the shape a record takes in a list", 4),
    ("the figure tile — one number and what it means", 5),
    ("a section heading smaller than a page title", 5),
    ("the search and filter bar", 5),
)


def kit_prompts(doc: dict) -> tuple[str, str]:
    """What the kit engineer is told. Deliberately not a template to fill: it is
    given the product, its register and its rhythm, and asked to design."""
    from services.blueprint.ui_engineer import RHYTHM_OPTIONS, _kit_exports, bar, derive_rhythm

    app = doc.get("application") or {}
    ds = doc.get("designSystem") or {}
    comp = doc.get("composition") or {}
    rhythm = derive_rhythm(doc)

    system = (
        "You are the design engineer of a software product. Before any page is written you "
        "build the product's OWN set of parts — the page head, the panel, the row, the chip, "
        "the empty state — and the small functions that put its words and numbers on screen. "
        "Every page is then composed from them.\n\n"
        "This is the difference between a product and a template. Thirty pages each inventing "
        "their own panel agree with each other by accident; thirty pages built from one panel "
        "are one product. Make something as considered as "
        f"{bar(doc)} — and specific to THIS product: the parts a claims desk needs are not the "
        "parts a hotel's guest app needs, and they should not look alike.\n\n"
        "YOU MAY NAME THIS PRODUCT'S COLOURS AND A PAGE MAY NOT. A page is held to the "
        "semantic token classes so the palette always applies; held to them alone it can only "
        "produce a tasteful default. You get the tints, washes and inks in between — but they "
        "are declared once, in `palette`, and reached as `var(--kit-<name>)` inside a class or "
        "`C.<name>` from `./palette`. A `#hex` written anywhere in a part is refused.\n\n"
        "Sizes, radii, spacing, gradients, letter-spacing and hand-built shadows ARE yours "
        "here — that is most of what makes a surface look drawn rather than defaulted. Use the "
        "design's own scale where it fits (`text-display/h1/h2/h3/body/caption`, `shadow-sm` to "
        "`shadow-xl`, `rounded-lg`), and your own exact values where the design wants them."
    )

    look = {k: ds.get(k) for k in ("register", "visualPersonality", "informationDensity",
                                   "colors", "typography", "radius", "elevation", "motion",
                                   "shell", "references") if ds.get(k)}
    entities = [e.get("name") for e in ((doc.get("data") or {}).get("entities") or [])][:14]
    patterns = sorted({str(p.get("pattern")) for p in doc.get("pages") or []
                       if p.get("pattern") and p.get("status") != "DEPRECATED"})

    user = (
        f"The product: {app.get('name')}\n{str(app.get('description') or '')[:1500]}\n\n"
        f"Its design:\n{json.dumps(look, indent=1)[:3500]}\n\n"
        f"Its direction:\n{str(comp.get('vision') or '')[:1500]}\n\n"
        "THE RHYTHM YOUR PARTS MUST IMPLEMENT — decided for the whole app; the pages are "
        "told to build to it, and from now on your parts are how they do:\n"
        + "\n".join(f"- {k}: `{rhythm[k]}` — {RHYTHM_OPTIONS[k][rhythm[k]]}" for k in RHYTHM_OPTIONS)
        + f"\n\nIts records: {', '.join(str(e) for e in entities if e) or 'none yet'}\n"
        f"Its kinds of page: {', '.join(patterns) or 'unknown'}\n\n"
        "WRITE THE PARTS THIS PRODUCT NEEDS. A real designed application's pages reached for "
        "these, and the count is how many of its fourteen kit-using pages imported each:\n"
        + "\n".join(f"- {what} ({n} pages)" for what, n in _PARTS_SEEN)
        + "\nThat is what pages ask for, not a list to copy — name and shape yours for this "
        "product, add what it needs and leave out what it does not.\n\n"
        "AND THE WORDS AND NUMBERS, which matter as much. In that same application the "
        "formatters were imported as often as the components, because what makes a product "
        "feel made is every screen saying the same thing the same way: its money, its dates "
        "and relative times, its reference numbers, the plain-English word for each status "
        "and the tone that status is drawn in, how long is left and whether that is urgent. "
        "Write the ones THIS product's records need, from the records above.\n\n"
        "HOW TO WRITE THEM\n"
        "- One file per part, named for it: `Panel.tsx`, `PageHead.tsx`, `format.ts`.\n"
        "- Plain React and Tailwind. A part is given what to draw as props; it never loads "
        "data, imports `@/sdk/server` or calls `fetch`.\n"
        "- You may import: react, next/link, lucide-react, clsx, tailwind-merge, motion/react, "
        f"`{KIT_IMPORT}/palette`, another of your own parts, and the shadcn kit:\n{_kit_exports()}\n"
        "- A part that uses a hook starts with \"use client\".\n"
        "- Real <button>/<a>, labels, `aria-label` on an icon-only control, visible focus.\n"
        "- Mobile first: nothing overflows at 375px.\n"
        "- Every exported name listed in `exports`, so the page writer can be handed them.\n\n"
        "Return `palette` — the handful of colours this product needs beyond its roles, each "
        "`{name, value}` with value a `#rrggbb` — then "
        "`parts`, and a one-paragraph `rationale` saying what language these parts are in."
    )
    return system, user


def _palette_map(palette: Any) -> dict[str, str]:
    """The reply's named entries as the `{name: hex}` the contract holds. A map
    is accepted too, so a hand-written body or a future schema still lands."""
    if isinstance(palette, dict):
        return {str(k): str(v) for k, v in palette.items()}
    return {str(e["name"]): str(e.get("value") or "")
            for e in (palette or []) if isinstance(e, dict) and e.get("name")}


def compose_kit(doc: dict, client: Any, app_root: str | Path,
                usage: Any = None, rounds: int = COMPILE_ROUNDS) -> tuple[dict, Any]:
    """Write the kit, then hold it to the compiler and its own rules.

    Returns the `componentKit` body. The files are left on disk: the pages
    written next import them, and `typecheck` can only check code where it
    lives.
    """
    system, user = kit_prompts(doc)
    note, body, last = "", {}, None
    for round_ in range(1, max(1, rounds) + 1):
        reply = client(system=system, user=user + note, schema=KIT_SCHEMA)
        last = getattr(reply, "usage", None) or last
        raw = json.loads(getattr(reply, "text", reply))
        body = {
            "rationale": str(raw.get("rationale") or ""),
            "palette": _palette_map(raw.get("palette")),
            "parts": [{"file": Path(str(p.get("file"))).name,
                       "purpose": str(p.get("purpose") or ""),
                       "exports": [str(n) for n in (p.get("exports") or [])],
                       "code": str(p.get("code") or "")}
                      for p in (raw.get("parts") or []) if p.get("file") and p.get("code")],
        }
        if not body["parts"]:
            return body, last

        probe = {**doc, "componentKit": body}
        style = findings(probe, body["parts"])
        project_component_kit(probe, app_root)
        broke: list[str] = []
        try:
            broke = typecheck(app_root)
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:  # noqa: BLE001
            logger.warning("[component_kit] not compiled: %s", exc)
        errors = style + broke
        if not errors:
            return body, last
        if round_ >= rounds:
            if broke:
                body = _without_the_broken(doc, body, broke, app_root)
            if style and body["parts"]:
                # A style finding never costs a part: an unthemed chip is worth
                # more than no chip, and the page it is on still compiles.
                logger.warning("[component_kit] kept with %d style finding(s): %s",
                               len(style), "; ".join(style[:4]))
            return body, last
        note = ("\n\nThe TypeScript compiler (strict) and the kit's rules refused it:\n"
                + "\n".join(f"- {e}" for e in errors[:40])
                + "\nReturn the whole kit again, fixed.")
    return body, last


def _without_the_broken(doc: dict, body: dict, errors: list[str],
                        app_root: str | Path) -> dict:
    """Drop the parts the compiler named, and the whole kit if that is not enough.

    A KIT THAT DOES NOT COMPILE TAKES THE PAGES WITH IT. Every page imports it,
    and `ui_engineer.settle_code_pages` deletes a page's code after it fails to
    compile twice — so one bad part, shipped, would empty the application. Six
    good parts are worth more than seven with a casualty, and no kit at all is
    survivable: the pages are then written in the token classes, exactly as they
    were before this node existed.
    """
    named = {_filename(p) for p in body["parts"]}
    blamed = {e.split("(", 1)[0] for e in errors if e.split("(", 1)[0] in named}
    if not blamed:
        # The compiler is unhappy with something we cannot attribute to a part;
        # we cannot cut precisely, so we do not ship a kit at all.
        blamed = named
    kept = {**body, "parts": [p for p in body["parts"] if _filename(p) not in blamed]}
    logger.warning("[component_kit] dropped %d part(s) that did not compile: %s",
                   len(blamed), ", ".join(sorted(blamed)))
    project_component_kit({**doc, "componentKit": kept}, app_root)
    if kept["parts"]:
        try:
            if still := typecheck(app_root):
                # Cutting one part can break another that imported it.
                logger.warning("[component_kit] the rest still does not compile (%s); "
                               "shipping no kit", still[0][:160])
                kept = {**kept, "parts": []}
                project_component_kit({**doc, "componentKit": kept}, app_root)
        except (RuntimeError, subprocess.SubprocessError, OSError):  # noqa: BLE001
            pass
    return kept
