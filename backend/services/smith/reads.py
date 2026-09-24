"""Smith reads the real application (S2 of `2026-09-24-smith-as-a-loop`, §0).

Until now Smith knew what one string said: `context.resolve` ranked the
Blueprint's artifacts against the request and handed over a capped slice, and
that slice was the whole of what a turn could see. A model told "the page does
not draw what you asked" could not open the page. "Knows the whole code in and
out" starts here — with the loop able to look, the way Claude Code's `Read`
and `Grep` look: exact, dumb, and never guessing.

THESE TOOLS NEVER GUESS. `read_file` reads the path it is given or says the
path is not there; it does not find the nearest file. `grep` returns matches
or none. A read that "helpfully" widened its search would be the repair chain
in a new place — a tool whose answer is not what was asked for is a tool whose
answers cannot be reasoned from.

THE ONE POLICY. An observation is written to the conversation, and §42 says a
credential must not come to rest there. So a file whose NAME says it holds
secrets (`.env`, `.env.local`, keys) is refused outright — the refusal names
the file and says why, which is the honest answer — and every other file's
content goes through `secrets_scrub.scrub` on the way out. This is the one
"cannot" that stays, and it is policy rather than capability, which is the
distinction §0 draws.

BOUNDED IN SIZE, SAID WHEN CUT. A page of React is a few hundred lines; a
lock file is fifty thousand. Reads are capped, and a capped read says so and
says how to ask for the rest, rather than returning a file that looks whole
and is not.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path
from typing import Any

from services.smith.secrets_scrub import scrub

#: Files refused by name, whatever they contain. Anchored on what people
#: actually name credential files; the content scrub catches the rest.
SECRET_NAMES: tuple[str, ...] = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
    "*.keystore", "credentials*.json", "service-account*.json",
)

#: Directories not worth a step. Reading into them is allowed by path — a
#: person may genuinely need one file of a dependency — but they are left out
#: of listings and searches, which otherwise return thousands of lines of
#: nobody's code.
SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", ".next", ".next-verify", ".git", "dist", "build", "__pycache__",
    ".turbo", ".cache", "coverage",
})

#: How much of a file one read returns, in lines. Enough for any page module
#: the build writes; a longer file is read in pieces by `start`.
MAX_LINES = 400
#: How many matches a search returns. A pattern matching more than this is a
#: pattern that needs narrowing, and the observation says so.
MAX_MATCHES = 60
#: Longest line shown before it is cut — minified code and data URIs would
#: otherwise put a megabyte into one observation.
MAX_LINE = 240
#: How many entries a listing returns.
MAX_ENTRIES = 200


class ReadRefused(ValueError):
    """The read cannot be done as asked. The message says why and what would
    work — it is the observation, not an exception the loop hides."""


def _root(output_dir: str) -> Path:
    return Path(output_dir).resolve()


def _jail(output_dir: str, rel: str) -> Path:
    """The absolute path for `rel`, which must stay inside the project.

    `..` and absolute paths are refused as given rather than normalised into
    something inside — a path that was meant to escape should be answered as
    such, and a path that was a typo should not silently become a different
    file.
    """
    rel = (rel or "").strip()
    if not rel:
        raise ReadRefused("No path was given. Paths are relative to the project, e.g. `app/src/pages/tools/view.tsx`.")
    if rel.startswith(("/", "~")) or ".." in Path(rel).parts:
        raise ReadRefused(f"`{rel}` is not a path inside the project. Paths are relative to the project root.")
    root = _root(output_dir)
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise ReadRefused(f"`{rel}` resolves outside the project and is refused.")
    return path


def _secret_name(path: Path) -> bool:
    name = path.name
    return any(fnmatch.fnmatch(name, pattern) for pattern in SECRET_NAMES)


def _cut(line: str) -> str:
    return line if len(line) <= MAX_LINE else line[:MAX_LINE] + " …[cut]"


# --------------------------------------------------------------------------- #
# The tools
# --------------------------------------------------------------------------- #

def read_file(output_dir: str, path: str, start: int = 1) -> str:
    """The file at `path`, numbered, from line `start`, at most MAX_LINES."""
    target = _jail(output_dir, path)
    if _secret_name(target):
        raise ReadRefused(
            f"`{path}` holds credentials and is not read — its contents would be "
            "written into the conversation. If you need a variable's NAME, it is "
            "in the projected settings; the value itself is never needed here.")
    if not target.exists():
        raise ReadRefused(f"There is no file at `{path}`. `list_files` shows what is there.")
    if target.is_dir():
        raise ReadRefused(f"`{path}` is a directory. `list_files` lists it; `read_file` wants a file.")
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ReadRefused(f"`{path}` is not a text file.")
    lines = text.splitlines()
    total = len(lines)
    first = max(1, int(start or 1))
    shown = lines[first - 1:first - 1 + MAX_LINES]
    body = "\n".join(f"{first + i:>5}| {_cut(l)}" for i, l in enumerate(shown))
    body = scrub(body)
    head = f"{path} — {total} lines"
    if first > 1 or first - 1 + len(shown) < total:
        last = first - 1 + len(shown)
        head += f", showing {first}–{last}"
        if last < total:
            head += f"; read_file(path, start={last + 1}) for the rest"
    return f"{head}\n{body}" if body else f"{head} (empty)"


def list_files(output_dir: str, path: str = "") -> str:
    """What is under `path` (the project root when empty), one level deep,
    directories first, dependency and build directories left out."""
    target = _jail(output_dir, path) if path.strip() else _root(output_dir)
    if not target.exists():
        raise ReadRefused(f"There is no `{path}` in the project.")
    if not target.is_dir():
        raise ReadRefused(f"`{path}` is a file, not a directory. `read_file` reads it.")
    entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    lines: list[str] = []
    skipped: list[str] = []
    for entry in entries:
        if entry.is_dir() and entry.name in SKIP_DIRS:
            skipped.append(entry.name + "/")
            continue
        if entry.is_dir():
            count = sum(1 for _ in entry.iterdir())
            lines.append(f"{entry.name}/  ({count} entries)")
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            mark = "  [credentials — not readable]" if _secret_name(entry) else ""
            lines.append(f"{entry.name}  ({size} bytes){mark}")
    shown = lines[:MAX_ENTRIES]
    head = f"{path or '.'} — {len(lines)} entries"
    if len(lines) > MAX_ENTRIES:
        head += f", showing {MAX_ENTRIES}"
    if skipped:
        head += f"; left out: {', '.join(skipped)}"
    return head + ("\n" + "\n".join(shown) if shown else " (empty)")


def grep(output_dir: str, pattern: str, path: str = "", glob: str = "") -> str:
    """Lines matching `pattern` (a regular expression, case-insensitive) under
    `path`, in files matching `glob` when given. Dependency and build
    directories are not searched."""
    pattern = (pattern or "").strip()
    if not pattern:
        raise ReadRefused("No pattern was given.")
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ReadRefused(f"`{pattern}` is not a valid regular expression: {exc}.")
    base = _jail(output_dir, path) if path.strip() else _root(output_dir)
    if not base.exists():
        raise ReadRefused(f"There is no `{path}` in the project.")
    root = _root(output_dir)
    hits: list[str] = []
    files_searched = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if glob and not fnmatch.fnmatch(name, glob):
                continue
            file = Path(dirpath) / name
            if _secret_name(file):
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            files_searched += 1
            rel = file.relative_to(root).as_posix()
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{n}: {_cut(line.strip())}")
                    if len(hits) > MAX_MATCHES:
                        break
            if len(hits) > MAX_MATCHES:
                break
    where = f" under `{path}`" if path.strip() else ""
    if not hits:
        return f"No line matches /{pattern}/{where} ({files_searched} files searched)."
    head = f"{min(len(hits), MAX_MATCHES)} match(es) for /{pattern}/{where}"
    if len(hits) > MAX_MATCHES:
        head += f" — more than {MAX_MATCHES}; narrow the pattern or the path"
    return head + "\n" + "\n".join(scrub(h) for h in hits[:MAX_MATCHES])


def read_section(doc: dict, name: str) -> str:
    """One section of the Blueprint, as JSON. Dotted names reach inside:
    `data.entities`, `navigation`, `pages`, `workflows`, `rules`,
    `designSystem`, `requirements`, `product`, `pageCode`."""
    name = (name or "").strip()
    if not name:
        raise ReadRefused("No section was named. Top-level sections: " + ", ".join(sorted(doc)) + ".")
    node: Any = doc
    for part in name.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            have = ", ".join(sorted(node)) if isinstance(node, dict) else "(not a section)"
            raise ReadRefused(f"The Blueprint has no `{name}`. At that level there is: {have}.")
    text = json.dumps(node, indent=1, ensure_ascii=False)
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        text = "\n".join(lines[:MAX_LINES]) + f"\n… [{len(lines) - MAX_LINES} more lines; ask for a narrower name, e.g. `{name}.<key>`]"
    return f"{name}:\n{scrub(text)}"


def _by_id(doc: dict) -> dict[str, tuple[str, dict]]:
    from services.blueprint.orchestrator import graph_pool
    out: dict[str, tuple[str, dict]] = {}
    for section, art in graph_pool(doc):
        if isinstance(art, dict) and art.get("id"):
            out[str(art["id"])] = (section, art)
    return out


def _label(art: dict) -> str:
    for key in ("name", "label", "title", "route", "table", "action"):
        if art.get(key):
            return str(art[key])
    return ""


def find(doc: dict, query: str) -> str:
    """Artifacts whose identity fields match `query` — ranked the way the
    context resolver ranks them, so `find` and the opening slice agree."""
    from services.smith.context import score_artifacts

    query = (query or "").strip()
    if not query:
        raise ReadRefused("Nothing to look for was given.")
    scored = score_artifacts(doc, query)[:20]
    if not scored:
        return f"Nothing in the Blueprint matches “{query}”."
    index = _by_id(doc)
    lines = []
    for s in scored:
        section, art = index.get(s.artifact_id, (s.section, {}))
        lines.append(f"{s.artifact_id}  {section}  {_label(art)}  ({s.why})".rstrip())
    return f"{len(lines)} match(es) for “{query}”:\n" + "\n".join(lines)


def read_page_code(doc: dict, route: str) -> str:
    """The React a page is written as — `load.ts` and `view.tsx` — by route."""
    from services.blueprint.app_sdk import code_page_files
    from services.smith.compose import _page_for_route, code_row

    route = (route or "").strip()
    page = _page_for_route(doc, route)
    if page is None:
        routes = ", ".join(str(p.get("route")) for p in doc.get("pages") or [] if isinstance(p, dict))[:600]
        raise ReadRefused(f"There is no page at `{route}`. Routes: {routes}.")
    row = code_row(doc, str(page.get("id")))
    if row is None:
        raise ReadRefused(
            f"`{route}` ({page.get('id')}) is not written as code — it renders from its "
            "layout tree. `read_section pageLayouts` shows the tree.")
    files = code_page_files(doc, row)
    out = [f"{route} ({page.get('id')}) — {len(files)} module(s)"]
    for rel, content in files.items():
        lines = content.splitlines()
        shown = lines[:MAX_LINES]
        out.append(f"\n--- {rel} ({len(lines)} lines{', cut' if len(lines) > MAX_LINES else ''}) ---")
        out.append("\n".join(f"{i:>5}| {_cut(l)}" for i, l in enumerate(shown, 1)))
    return scrub("\n".join(out))


def dependents(doc: dict, artifact_id: str) -> str:
    """What `artifact_id` refers to, and what refers to it — §19's graph, one
    hop each way. The reverse direction is computed by asking every artifact
    what it references; there is no reverse index and the pool is small."""
    from services.smith.code_intel import refs_of

    artifact_id = (artifact_id or "").strip()
    if not artifact_id:
        raise ReadRefused("No artifact id was given (e.g. `PAGE-003`, `ENTITY-002`).")
    index = _by_id(doc)
    if artifact_id not in index:
        raise ReadRefused(f"There is no artifact `{artifact_id}`. `find` looks one up by name.")
    section, art = index[artifact_id]
    # AN EDGE IS A REFERENCE TO SOMETHING THAT EXISTS. `refs_of` reads every
    # id-shaped value off an artifact; membership in the index is what makes
    # it an edge. `code_intel.dependencies(depth=1)` returned only the seed on
    # a real engine document whose page plainly refers to its entity, module
    # and role — why was not chased; this asks the artifact directly, which
    # is the question anyway. Sections that are not artifacts (the navigation
    # tree names pages but has no id) do not appear as referrers.
    def _edges(a: dict) -> set[str]:
        return {r for r in refs_of(a) if r in index}

    outgoing = sorted(_edges(art) - {artifact_id})
    incoming = sorted(other for other, (_s, a) in index.items()
                      if other != artifact_id and artifact_id in _edges(a))

    def _row(i: str) -> str:
        sec, a = index.get(i, ("?", {}))
        return f"  {i}  {sec}  {_label(a)}".rstrip()

    out = [f"{artifact_id}  {section}  {_label(art)}"]
    out.append(f"refers to ({len(outgoing)}):")
    out += [_row(i) for i in outgoing] or ["  (nothing)"]
    out.append(f"referred to by ({len(incoming)}):")
    out += [_row(i) for i in incoming] or ["  (nothing)"]
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# The catalogue entry and the dispatcher
# --------------------------------------------------------------------------- #

#: (name, description, {argument: type}). Descriptions are written for the
#: thing that reads the catalogue — the model deciding what to look at.
READS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("read_file",
     "A file of the application, numbered, from `start` (default 1), up to "
     f"{MAX_LINES} lines. Paths are relative to the project root — `app/src/...`. "
     "Reads exactly the path given; a wrong path is reported, never corrected.",
     {"path": "string", "start": "integer"}),
    ("list_files",
     "What is in a directory of the application, one level. Empty `path` is "
     "the project root. Dependency and build directories are left out.",
     {"path": "string"}),
    ("grep",
     "Lines matching a regular expression, across the application's own "
     "files, with file and line number. `path` narrows where; `glob` (e.g. "
     "`*.tsx`) narrows which files.",
     {"pattern": "string", "path": "string", "glob": "string"}),
    ("read_section",
     "One section of the Blueprint as JSON — `pages`, `data.entities`, "
     "`workflows`, `rules`, `navigation`, `designSystem`, `requirements`, "
     "`product`, `pageCode`, `pageLayouts`. Dotted names reach inside.",
     {"name": "string"}),
    ("find",
     "Artifacts whose name, label, route, table or action matches the words "
     "given, with their ids — the way to turn 'the dashboard' into `PAGE-014`.",
     {"query": "string"}),
    ("read_page_code",
     "The React a page is written as — its `load.ts` and `view.tsx` — by route. "
     "This is what the screen actually runs.",
     {"route": "string"}),
    ("dependents",
     "What refers to an artifact and what it refers to: the pages a workflow "
     "is launched from, the entity a field belongs to, the rules on a page.",
     {"artifact_id": "string"}),
)

READ_NAMES: frozenset[str] = frozenset(name for name, _d, _a in READS)


def run(name: str, args: dict, *, output_dir: str, doc: dict) -> str:
    """Carry out one read. Returns the observation text; a refusal IS the
    observation, in the tool's own words."""
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    try:
        if name == "read_file":
            return read_file(output_dir, str(args.get("path") or ""),
                             int(args.get("start") or 1))
        if name == "list_files":
            return list_files(output_dir, str(args.get("path") or ""))
        if name == "grep":
            return grep(output_dir, str(args.get("pattern") or ""),
                        str(args.get("path") or ""), str(args.get("glob") or ""))
        if name == "read_section":
            return read_section(doc, str(args.get("name") or ""))
        if name == "find":
            return find(doc, str(args.get("query") or ""))
        if name == "read_page_code":
            return read_page_code(doc, str(args.get("route") or ""))
        if name == "dependents":
            return dependents(doc, str(args.get("artifact_id") or ""))
    except ReadRefused as refused:
        return str(refused)
    except (ValueError, TypeError) as exc:
        return f"`{name}` could not run with those arguments: {exc}"
    raise KeyError(name)


__all__ = ["READS", "READ_NAMES", "ReadRefused", "run", "read_file", "list_files",
           "grep", "read_section", "find", "read_page_code", "dependents",
           "MAX_LINES", "MAX_MATCHES", "SECRET_NAMES", "SKIP_DIRS"]
