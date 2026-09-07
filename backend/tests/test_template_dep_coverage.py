"""Regression: the standalone-app package.json template must be a superset of
every third-party package imported by the app-foundation floor.

The non-figma flow copies the app-foundation floor (src/**) into a generated
app, then app_emitter.emit_standalone_app OVERWRITES package.json from
standalone-app/package.json.tmpl. If the template omits a package the floor
imports (radix, @tanstack/react-query, recharts, ...), `next build` fails with
Module-not-found. This test locks the two templates together.
"""

import json
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
TMPL = TEMPLATES / "standalone-app" / "package.json.tmpl"
FLOOR_SRC = TEMPLATES / "app-foundation" / "src"

# Packages that need not appear in the template deps:
#   - node builtins (fs, path, node:*)
#   - packages provided by the vendored @tentoroforge/* set (file: deps)
#   - packages provided transitively by next (server-only) / dev tooling
ALLOWLIST = {
    # node builtins
    "fs", "path", "os", "crypto", "http", "https", "url", "stream", "util",
    "events", "buffer", "child_process", "assert", "process",
    # vendored workspace packages (may or may not be pinned in the template)
    "@tentoroforge/editor",
    # provided by next / build tooling, never a direct dep of the floor
    "server-only",
}


def _package_name(spec: str) -> str:
    """Reduce a module specifier to its installable package name.

    @radix-ui/react-dialog -> @radix-ui/react-dialog
    next/link              -> next
    react-dom/client       -> react-dom
    """
    if spec.startswith("@"):
        parts = spec.split("/")
        return "/".join(parts[:2])
    return spec.split("/")[0]


def _template_deps() -> set[str]:
    text = TMPL.read_text(encoding="utf-8")
    # Stub {{...}} / <<...>> placeholders so json.loads succeeds.
    text = re.sub(r"\{\{[^}]*\}\}", "__PLACEHOLDER__", text)
    text = re.sub(r"<<[^>]*>>", "__PLACEHOLDER__", text)
    data = json.loads(text)
    deps = set(data.get("dependencies", {}))
    deps |= set(data.get("devDependencies", {}))
    return deps


def _floor_imported_packages() -> set[str]:
    import_re = re.compile(
        r"""(?:from|import)\s+['"]([^'"]+)['"]"""
    )
    pkgs: set[str] = set()
    for path in FLOOR_SRC.rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
            continue
        for spec in import_re.findall(path.read_text(encoding="utf-8")):
            # Skip relative and alias imports.
            if spec.startswith(".") or spec.startswith("@/") or spec.startswith("~"):
                continue
            # Skip node: builtins explicitly.
            if spec.startswith("node:"):
                continue
            if spec.endswith(".css"):
                continue
            pkgs.add(_package_name(spec))
    return pkgs


def test_standalone_template_covers_app_foundation_imports():
    deps = _template_deps()
    imported = _floor_imported_packages()
    missing = sorted(p for p in imported if p not in deps and p not in ALLOWLIST)
    assert not missing, (
        "standalone-app/package.json.tmpl is missing deps imported by the "
        f"app-foundation floor: {missing}. Add them (with the app-foundation "
        "pinned version) so `next build` does not fail Module-not-found."
    )
