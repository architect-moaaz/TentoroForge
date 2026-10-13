"""The native engineer: one page of the application as a React Native screen.

The web's UI engineer (`ui_engineer`) writes a page as Next.js; this writes the
SAME page — the same Blueprint page, so the same entities, workflows and rules
— as a screen in the Expo project beside it (`native_projection`). One screen
per page, written against the native SDK and kit that ship in
`templates/native`, which mirror the web's names (`useList`, `useWorkflow`,
`WorkflowForm`, `href`…) so a model that knows the one writes the other.

What it is held to is what the web page is held to, with the compiler first: a
screen is type-checked against the application's own generated types (a
workflow input left out, a route that is not there, a column the entity lacks
is an error, not a heuristic) and against the page rules (every workflow the
page launches has a control, every move the flows name leads somewhere, no
change is faked in state). What goes back to the writer is the errors; what
comes out is code that compiles.

Not here, by design: the web's look review (a screenshot of the page) — there
is no native render target in the build yet, so a screen is accepted as
compiled and the narration says so; and parts (a screen is one file).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from services.blueprint.native_projection import TEMPLATE_DIR

logger = logging.getLogger(__name__)

#: The reply: the screen, whole, and anything it needs that no workflow does.
NATIVE_SCREEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rationale", "screen", "needs"],
    "properties": {
        "rationale": {"type": "string",
                      "description": "Two or three sentences: how the screen is arranged for a phone and why."},
        "screen": {"type": "string", "description": "The full contents of the screen file (Screen.tsx)."},
        "needs": {"type": "array", "items": {"type": "string"},
                  "description": "A change to records the screen needs and no workflow of the application "
                                 "makes — named in a sentence each. Empty when every change has a workflow."},
    },
}

#: The rounds a screen gets to compile (the web's).
def _rounds() -> int:
    from services.blueprint.ui_engineer import COMPILE_ROUNDS
    return COMPILE_ROUNDS


# ---------------------------------------------------------------------------
# What the writer is told
# ---------------------------------------------------------------------------

def sdk_guide() -> str:
    """The native SDK and kit as the template documents them: from "What a
    screen imports" to the tests — the one place that says what exists."""
    text = (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")
    start = text.index("### What a screen imports")
    end = text.index("## Tests")
    return text[start:end].strip()


NATIVE_RULES = """\
- ONE FILE. The whole screen is `Screen.tsx`: `export default function Screen() { … }`. Imports only from
  "react", "react-native", "@/ui" and "@/sdk" — and a type from "@/sdk" is how you name an entity's row.
  Nothing from next/*, react-dom, lucide-react, a CSS file or a package that is not listed; no `className`,
  no <div>/<span>/<button>/<img>/<a>: this is React Native, and the kit has the part you want.
- DATA IS A HOOK. There is no `load` and no server: read with `useList`, `useRecord`, `useCount`, `useQuery`,
  `useWidget`… and handle every state the hook has — loading, error with a retry, empty, and a record that is
  gone (`notFound`). `Screen` takes `loading`, `error`, `onRetry`, `empty` and `onRefresh` for exactly this.
  A route's id comes from `useParams<{ id: string }>()`; read nothing until it is there (pass `null`).
- EVERY CHANGE IS A WORKFLOW. `WorkflowForm`, `WorkflowButton`, or `useWorkflow(workflows.x)` and `run({…})`.
  Never write records any other way, and never fake one (a handler that filters a row out of state, or waits on
  a timer). When the screen needs a change no workflow makes, leave the control out and name the change in `needs`.
- EVERY WORKFLOW THE PAGE LAUNCHES HAS A CONTROL, and every move the flows name leads where it says
  (`useNav().push(href(pages.x, { id }))`, or `redirectTo`). A screen that compiles and cannot do the page's job
  is a failure.
- A PHONE, NOT A SHRUNK PAGE. One column. The primary action is in reach of the thumb (`footer` on `Screen`, or a
  full-width Button at the end of a form). Touch targets are 44 pt. A long list is a `ListView`, not a map
  inside a ScrollView. A secondary flow is a `Sheet`, not a second screen. Tables become cards or rows with the
  two facts that matter, the rest one tap away. Text never truncates what the person needs to read.
- COLOUR AND SIZE COME FROM THE THEME. `useTheme().colors.<token>`, `space.<size>`: never a hex colour and never
  a magic number for a margin. The kit's parts are already styled — use `Card`, `Badge`, `StatTile`, `Button`
  variants rather than styling a View.
- MONEY is in major units (12.50): `<Money value={…} />` or `formatMoney`. Dates through `formatDate`. Every
  visible string through `useT()` when the application has more than one language.
- WRITE IT AS YOU WOULD SHIP IT: no TODOs, no placeholder copy, no console.log, no unused imports. Real labels
  from the page's contract, real empty states in the application's own voice."""

NATIVE_DESIGN = """\
Design for the thumb and for glancing. Lead with what the person came to do or know: the primary number or the
primary action in the first screenful. Group by task with generous spacing from `space`, not by borders.
Use the application's own voice and the entity's own names. Make an empty list an invitation to add the first
one, and an error a sentence with a retry. Motion is the platform's; add none of your own. A screen that would
look at home in any other application is not finished."""


def _look(doc: dict) -> str:
    """The design system, as the tokens a native screen asks the theme for."""
    design = doc.get("designSystem") or {}
    colors = design.get("colors") or {}
    roles = {"background": "background", "surface": "card", "textPrimary": "foreground",
             "textSecondary": "mutedForeground", "primary": "primary", "accent": "accent",
             "accentSubtle": "accentSubtle", "inverse": "inverse"}
    lines = [str(design.get("visualPersonality") or "")[:600]]
    for role, token in roles.items():
        value = colors.get(role)
        if value:
            lines.append(f"- theme.colors.{token} ({value})")
    typo = design.get("typography") or {}
    head = typo.get("fontFamilyHeading") or typo.get("fontFamilyDisplay") or typo.get("headingFontFamily")
    body = typo.get("fontFamilyBase") or typo.get("fontFamily") or typo.get("fontFamilyBody")
    if head or body:
        lines.append(f"- type faces: heading {head or body}; body {body or head} (the system font unless the app loads them)")
    return "\n".join(x for x in lines if x)


def system_prompt(doc: dict) -> str:
    """Identical for every screen of one application — the cached prefix."""
    from services.blueprint.app_sdk import sdk_reference
    from services.blueprint.ui_engineer import _about, _language, _rhythm, bar

    comp = doc.get("composition") or {}
    conventions = "\n".join(f"- {c.get('topic')}: {c.get('rule')}" for c in comp.get("conventions") or []) or "- (none stated)"
    app = doc.get("application") or {}
    return f"""You are the native engineer of {app.get('name') or 'this application'}: you write one screen of its \
React Native (Expo, TypeScript strict) app, held to the standard of {bar(doc)}. The same page already exists on \
the web; you write it for the phone — the same data, the same workflows, the same rules, reached over the \
application's own API — and it must look and feel like THIS product, not like every other generated app.

WRITE IT, THEN IMPROVE IT. Your reply is compiled the moment it arrives — TypeScript strict against this \
application's own types, plus checks that every workflow the page launches has a control — and anything wrong \
comes straight back to you with the errors, up to {_rounds()} times. Begin writing early.

# The application
{app.get('name')}
{_about(doc)}

{_language(doc)}# Its direction — follow it on every screen
{comp.get('vision') or '(no vision stated — choose a calm, professional, information-dense style)'}
{conventions}

# Its rhythm — decided once for this application
{_rhythm(doc)}

# Its look — the tokens the theme carries
{_look(doc)}

# Rules
{NATIVE_RULES}

# The native SDK and kit
```
{sdk_guide()}
```

# This application's entities, workflows and pages (generated from its Blueprint — the web uses the same)
```ts
{sdk_reference(doc)}
```

# Design
{NATIVE_DESIGN}
Reply with the rationale, the full contents of Screen.tsx, and `needs` (empty when every change has a workflow)."""


def user_prompt(doc: dict, page: dict, *, feedback: str = "", brief: str = "", current: dict | None = None) -> str:
    from services.blueprint.ui_engineer import _page_brief

    out = ["Write this page as a native screen. The brief below is the web page's; its `load.ts`, `searchParams`, "
           "`useSearchParams` and `view.tsx` are the web's words — on the phone a hook reads the data, `useParams` "
           "gives the route's id and query, and the screen is one component.\n\n```json\n"
           + json.dumps(_page_brief(doc, page), indent=2) + "\n```"]
    if brief:
        out.append(f"\nWhat is wanted of it now:\n{brief}")
    if current:
        out.append("\nIts current screen — change it as asked, keep what works:\n```tsx\n"
                   + str(current.get("screen") or "") + "\n```")
    if feedback:
        out.append(f"\nYour previous version was refused. Fix every one of these and keep what worked:\n{feedback}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The page rules (text checks; the compiler does the rest)
# ---------------------------------------------------------------------------

_WEB_IMPORT = re.compile(r"""from\s+["'](next/[^"']*|next|react-dom[^"']*|lucide-react|@/components/[^"']*|@/lib/[^"']*|"""
                         r"""@tentoroforge/[^"']*|tailwind[^"']*|[^"']+\.css)["']""")
_HTML_TAG = re.compile(r"<(div|span|button|img|a|p|ul|li|table|tr|td|th|input|form|section|main|header|footer|h[1-6])[\s>/]")
_CLASSNAME = re.compile(r"\bclassName\s*=")
_HEX = re.compile(r"""["']#[0-9a-fA-F]{3,8}["']""")
_FETCH = re.compile(r"\bfetch\s*\(")
_CONSOLE = re.compile(r"\bconsole\.(log|debug)\s*\(")


def _native_findings(screen: str) -> list[str]:
    out = []
    if not re.search(r"export\s+default\s+(?:async\s+)?function\b|export\s+default\s+\w+", screen):
        out.append("Screen.tsx: it has no default export — `export default function Screen() { … }`.")
    for m in sorted({m.group(1) for m in _WEB_IMPORT.finditer(screen)}):
        out.append(f"Screen.tsx: imports `{m}` — a web module. Only react, react-native, @/ui and @/sdk exist here.")
    tags = sorted({m.group(1) for m in _HTML_TAG.finditer(screen)})
    if tags:
        out.append("Screen.tsx: HTML elements (" + ", ".join(f"<{t}>" for t in tags[:6])
                   + ") do not exist in React Native — use View/Text or the kit's parts.")
    if _CLASSNAME.search(screen):
        out.append("Screen.tsx: `className` does nothing in React Native — style from the kit and `useTheme()`.")
    if _HEX.search(screen):
        out.append("Screen.tsx: a hard-coded hex colour — take it from `useTheme().colors`.")
    if _FETCH.search(screen):
        out.append("Screen.tsx: `fetch` — read with the SDK's hooks and change with a workflow.")
    if _CONSOLE.search(screen):
        out.append("Screen.tsx: a console.log is left in.")
    return out


def _page_findings(doc: dict, page: dict, screen: str) -> list[str]:
    """The web's page rules, said for a screen: a launched workflow with no
    control, a flow move that leads nowhere, a change faked in state."""
    from services.blueprint.ui_engineer import _simulated_writes, _unfollowed_flows, _unwired_actions

    found = _unwired_actions(doc, page, screen) + _unfollowed_flows(doc, page, screen) + _simulated_writes(screen)
    return [e.replace("view.tsx", "Screen.tsx") for e in found]


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

#: The packages the template's `package.json` names, installed once and shared.
_TOOLCHAIN_LOCK = threading.Lock()


def toolchain_dir() -> Path:
    """Where the compiler and the packages the screens type-check against live:
    `FORGE_NATIVE_TOOLCHAIN`, else `backend/.forge/native-toolchain`."""
    given = os.environ.get("FORGE_NATIVE_TOOLCHAIN", "").strip()
    return Path(given) if given else Path(__file__).resolve().parents[2] / ".forge" / "native-toolchain"


def _package_json() -> dict:
    pkg = json.loads((TEMPLATE_DIR / "package.json").read_text(encoding="utf-8"))
    return {"name": "forge-native-toolchain", "version": "1.0.0", "private": True,
            "dependencies": pkg.get("dependencies") or {}, "devDependencies": pkg.get("devDependencies") or {}}


def _fingerprint() -> str:
    return hashlib.sha256(json.dumps(_package_json(), sort_keys=True).encode()).hexdigest()[:16]


def ensure_toolchain(run: Any = None, timeout: float = 1500.0) -> Path | None:
    """The toolchain directory with its packages installed, or None when it
    cannot be (no npm, no network): the screen is then checked by its page
    rules alone and the run says it was not compiled. Installed once, keyed by
    the template's dependencies, and shared by every screen of every app."""
    run = run or subprocess.run
    root = toolchain_dir()
    stamp = root / "node_modules" / ".forge-installed"
    tsc = root / "node_modules" / "typescript" / "bin" / "tsc"
    explicit = bool(os.environ.get("FORGE_NATIVE_TOOLCHAIN", "").strip())
    with _TOOLCHAIN_LOCK:
        if tsc.is_file() and (explicit or (stamp.is_file() and stamp.read_text().strip() == _fingerprint())):
            return root
        npm = shutil.which("npm")
        if not npm:
            logger.warning("[native_engineer] no npm: screens are not compiled")
            return None
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(json.dumps(_package_json(), indent=2), encoding="utf-8")
        logger.info("[native_engineer] installing the native toolchain in %s (once)", root)
        try:
            proc = run([npm, "install", "--no-audit", "--no-fund", "--loglevel", "error"], cwd=str(root),
                       capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("[native_engineer] the toolchain did not install: %s", exc)
            return None
        if getattr(proc, "returncode", 1) != 0 or not tsc.is_file():
            logger.warning("[native_engineer] the toolchain did not install: %s",
                           (getattr(proc, "stderr", "") or "")[-400:])
            return None
        stamp.write_text(_fingerprint(), encoding="utf-8")
        return root


def _posix(path: Path) -> str:
    return path.resolve().as_posix()


def typecheck(doc: dict, native_root: Path, page_id: str, screen: str, *, timeout: float = 240.0,
              toolchain: Path | None = None, run: Any = None) -> list[str] | None:
    """Compile one screen against the application's own generated types and
    the kit. Only errors in the screen count: the kit is checked by its own
    tests. Returns the errors (empty when it compiles), or None when there is
    no compiler to ask — which the caller says out loud."""
    from services.blueprint.native_projection import ensure_native_project

    tool = toolchain or ensure_toolchain()
    node = shutil.which("node")
    if tool is None or node is None:
        return None
    run = run or subprocess.run
    project = ensure_native_project(doc, native_root.parent)
    check = tool / ".checks" / f"{page_id}-{os.getpid()}-{threading.get_ident()}"
    if check.exists():
        shutil.rmtree(check, ignore_errors=True)
    check.mkdir(parents=True)
    try:
        (check / "screen.tsx").write_text(screen, encoding="utf-8")
        modules = tool / "node_modules"
        (check / "tsconfig.json").write_text(json.dumps({
            "extends": "expo/tsconfig.base",
            "compilerOptions": {
                "strict": True, "jsx": "react-native", "noEmit": True, "incremental": False,
                "skipLibCheck": True, "baseUrl": _posix(check),
                "paths": {
                    f"@/screens/{page_id}": [_posix(check / "screen.tsx")],
                    "@/*": [_posix(project / "src") + "/*"],
                    "*": [_posix(modules) + "/*", _posix(modules / "@types") + "/*"],
                },
                "typeRoots": [_posix(modules / "@types")],
            },
            "include": [_posix(check / "screen.tsx"), _posix(project / "src") + "/**/*.d.ts"],
        }, indent=2), encoding="utf-8")
        proc = run([node, _posix(modules / "typescript" / "bin" / "tsc"), "-p", _posix(check / "tsconfig.json"),
                    "--pretty", "false"], cwd=str(check), capture_output=True, text=True, encoding="utf-8",
                   timeout=timeout)
        marker = check.name + "/"
        errors: list[str] = []
        ours = False
        for line in (proc.stdout + proc.stderr).splitlines():
            where = line.split("(", 1)[0].replace("\\", "/")
            # tsc names a file relative to its cwd — the check folder, so the screen is
            # plain `screen.tsx` — or by a longer path through it from elsewhere. Anything
            # else is the kit's own file, and the kit is checked by its tests.
            if where == "screen.tsx" or where.endswith("/" + marker + "screen.tsx"):
                errors.append("Screen.tsx" + line[len(where):])
                ours = True
            elif ours and line.startswith(" "):
                errors[-1] += " " + line.strip()
            else:
                ours = False
        return errors
    finally:
        shutil.rmtree(check, ignore_errors=True)


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------

def compose_screen(doc: dict, page: dict, native_root: Path, client: Any, *, feedback: str = "", brief: str = "",
                   current: dict | None = None, node: str = "native_code",
                   check: Any = None) -> tuple[dict, list[Any]]:
    """Author one screen and compile it, returning the accepted `nativeCode`
    body and the usage of every call. Raises `CompileError` when the last round
    still does not compile; `NeedsWorkflow` when a change asks for records to
    change in a way no workflow does.

    `check(screen) -> list[str] | None` is the compiler, replaceable; None
    from it means there is none to ask (the screen is accepted on the page
    rules alone and the log says so)."""
    from services.blueprint.ui_engineer import CompileError, NeedsWorkflow, WRITE_EFFORT, WRITE_MAX_TOKENS, _with

    check = check or (lambda screen: typecheck(doc, native_root, str(page.get("id")), screen))
    system = system_prompt(doc)
    writer = _with(client, effort=WRITE_EFFORT, max_tokens=WRITE_MAX_TOKENS)
    spent: list[Any] = []
    note = feedback
    last_errors: list[str] = []
    rounds = _rounds()
    for round_ in range(1, rounds + 1):
        t0 = time.monotonic()
        reply = writer(system=system, user=user_prompt(doc, page, feedback=note, brief=brief, current=current),
                       schema=NATIVE_SCREEN_SCHEMA)
        text = getattr(reply, "text", reply)
        if getattr(reply, "usage", None) is not None:
            spent.append((reply.usage, time.monotonic() - t0))
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            note = f"Your reply was not valid JSON ({exc}). Return the object only."
            continue
        screen = str(body.get("screen") or "")
        needs = [str(n).strip() for n in body.get("needs") or [] if str(n).strip()]
        if needs and current is not None:
            # NOTHING IS WRITTEN AROUND A MISSING WORKFLOW — the web's rule.
            raise NeedsWorkflow(needs)
        errors = _native_findings(screen) + _page_findings(doc, page, screen)
        compiled = check(screen)
        if compiled is None:
            logger.info("[native_engineer] %s not compiled (no compiler); accepted on its page rules", page.get("id"))
        else:
            errors += compiled
        if not errors:
            logger.info("[native_engineer] %s composed in %d round(s), %d chars", page.get("id"), round_, len(screen))
            return ({"page": str(page.get("id")), "rationale": str(body.get("rationale") or ""),
                     "screen": screen, "parts": {}, "requirements": list(page.get("requirements") or [])}, spent)
        last_errors = errors
        current = {"screen": screen}
        note = ("The TypeScript compiler (strict) and the screen rules refused it:\n"
                + "\n".join(f"- {e}" for e in errors[:40]))
        logger.warning("[native_engineer] %s round %d: %d error(s): %s", page.get("id"), round_, len(errors),
                       "; ".join(errors[:3])[:400])
    raise CompileError(f"{page.get('id')}: the native screen still does not compile after {rounds} rounds — "
                       + "; ".join(last_errors[:12]))
