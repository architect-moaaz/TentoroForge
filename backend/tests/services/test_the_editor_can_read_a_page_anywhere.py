"""The editor's own scripts carry their dependencies.

`static/*.mjs` parse and rewrite a page's React source with @babel/parser.
On a developer's machine those imports resolve from the repo root's
node_modules — Node walks up until it finds one. A container has no repo root
above `/app/static`, so on UAT (both stacks) every attempt to open a page in
the editor answered

    The page could not be read: Cannot find package '@babel/parser'
    imported from /app/static/react-model.mjs

with HTTP 422, for every page of every project. Nothing declared the
dependency, so nothing could install it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
STATIC = BACKEND / "static"

#: `import … from "x"`, bare specifiers only — a relative import is a sibling
#: file and needs nothing installed.
_IMPORT = re.compile(r"""^import\s+(?:[^'"]*?\sfrom\s+)?["'](?P<name>[^.'"][^'"]*)["']""")

#: Node's own. Nothing installs these.
_BUILTIN = {"fs", "path", "crypto", "module", "url", "os", "util", "events", "stream",
            "child_process", "process", "http", "https", "zlib", "readline", "worker_threads"}


def _bare_imports() -> set[str]:
    """What Node resolves when it loads these scripts.

    Only the import header counts: `react-jit.mjs` writes a React file as a
    template string, and those `import React from "react"` lines are OUTPUT,
    not something this process loads. So reading stops at the first line that
    is neither blank, a comment, nor an import."""
    found: set[str] = set()
    for script in STATIC.glob("*.mjs"):
        for line in script.read_text("utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "/*", "*", "*/")):
                continue
            m = _IMPORT.match(line)
            if not m:
                break                          # past the header — the rest is code
            name = m.group("name")
            if name.startswith("node:") or name in _BUILTIN:
                continue
            parts = name.split("/")
            found.add("/".join(parts[:2]) if name.startswith("@") else parts[0])
    return found


def test_every_package_the_scripts_import_is_declared():
    declared = set(json.loads((STATIC / "package.json").read_text("utf-8")).get("dependencies") or {})
    missing = sorted(_bare_imports() - declared)
    assert not missing, f"imported by static/*.mjs but declared nowhere: {missing}"


def test_the_image_installs_them_beside_the_scripts():
    """Declaring is not installing: Node resolves from the directory the
    script is in, so the install has to land in `/app/static/node_modules`."""
    dockerfile = (BACKEND / "Dockerfile").read_text("utf-8")
    assert "cd /app/static && npm install" in dockerfile
    assert dockerfile.index("COPY . .") < dockerfile.index("cd /app/static && npm install")


def test_the_versions_are_pinned():
    """A parser that floats is a page that reads differently next Tuesday."""
    deps = json.loads((STATIC / "package.json").read_text("utf-8"))["dependencies"]
    assert deps, "the scripts import something; it belongs here"
    for name, spec in deps.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", spec), f"{name} is {spec!r}, not an exact version"
