"""Normalize a generated app's next.config to the one authoritative form.

app_emitter writes a single correct next.config.js, but the schema/code agents also
emit their own next.config (they're prompted to), and the LLM tends to "helpfully"
pile the vendored packages' transitive deps — jsdom, parse5, cssstyle,
@asamuzakjp/css-color, @tentoroforge/editor — into `transpilePackages` to make things
build. That's wrong: jsdom reads its default UA stylesheet via a __dirname-relative
require, so BUNDLING it (transpilePackages) breaks at runtime with
`ENOENT .next/browser/default-stylesheet.css` on every page that sanitizes HTML.
jsdom must be a `serverExternalPackages` entry (loaded from node_modules at runtime)
instead.

Because the agent's config can land after app_emitter's write — and refines can
re-introduce it — this guard re-asserts the authoritative config as a deterministic
post-generate backstop (and on every validate→repair sweep). It also removes
conflicting next.config.ts/.mjs so Next doesn't pick an ambiguous one.
"""
from __future__ import annotations

import os

# The single authoritative config. Keep in sync with app_emitter.py's emit.
#
# outputFileTracingIncludes: Server Components read src/schemas/**/*.json and
# src/contracts/*.json via fs.readFile at render time — those aren't static
# imports, so Next's file-tracer would otherwise leave them out of the
# serverless bundle. Deployed to Vercel, /dashboard then hits ENOENT on
# `/var/task/src/schemas/home.json` and every SSR route 500s. Ship them
# alongside every route.
_AUTHORITATIVE = (
    "/** @type {import('next').NextConfig} */\n"
    "module.exports = {\n"
    "  reactStrictMode: true,\n"
    '  transpilePackages: ["@tentoroforge/engine", "@tentoroforge/library", '
    '"@tentoroforge/renderer", "@tentoroforge/schema"],\n'
    '  serverExternalPackages: ["isomorphic-dompurify", "jsdom"],\n'
    "  outputFileTracingIncludes: {\n"
    '    "/**/*": ['
    '"./src/schemas/**/*.json", "./src/contracts/**/*.json", "./registry.json"'
    "],\n"
    "  },\n"
    "  typescript: { ignoreBuildErrors: true },\n"
    '  images: { domains: ["localhost"] },\n'
    "};\n"
)

# The markers of a bad config: jsdom/its subtree bundled via transpilePackages,
# the authoritative markers missing, OR outputFileTracingIncludes missing
# (Vercel deploy would 500 on any SSR page that reads schemas).
_BAD_MARKERS = ("jsdom", "cssstyle", "@asamuzakjp", "parse5")


def _is_wrong(text: str) -> bool:
    if "serverExternalPackages" not in text:
        return True
    # Missing the file-tracing includes → Vercel deploy will 500 on any
    # SSR route that reads src/schemas/*.json (ENOENT /var/task/src/schemas/…).
    # Older-generation apps hit this before the tracing includes existed;
    # heal them on the next sweep.
    if "outputFileTracingIncludes" not in text:
        return True
    # jsdom (or its subtree) inside transpilePackages is the failure mode. Cheap
    # heuristic: the bad deps should only ever appear on the serverExternalPackages
    # line, never in transpilePackages.
    for line in text.splitlines():
        if "transpilePackages" in line and any(m in line for m in _BAD_MARKERS):
            return True
    # Multi-line transpilePackages array: if any bad marker sits before the
    # serverExternalPackages declaration, it's in the transpile block.
    t_idx = text.find("transpilePackages")
    s_idx = text.find("serverExternalPackages")
    if t_idx != -1 and s_idx != -1 and s_idx > t_idx:
        block = text[t_idx:s_idx]
        if any(m in block for m in _BAD_MARKERS):
            return True
    return False


def normalize_next_config(output_dir: str) -> dict:
    """Re-assert the authoritative next.config.js and drop conflicting variants.
    Returns {normalized, removed_variants}."""
    out = output_dir
    js = os.path.join(out, "next.config.js")
    normalized = 0
    try:
        current = ""
        if os.path.exists(js):
            with open(js, encoding="utf-8") as fh:
                current = fh.read()
        if current != _AUTHORITATIVE and (not current or _is_wrong(current)):
            with open(js, "w", encoding="utf-8") as fh:
                fh.write(_AUTHORITATIVE)
            normalized = 1
    except OSError:
        return {"normalized": 0, "removed_variants": 0}

    removed = 0
    for alt in ("next.config.ts", "next.config.mjs"):
        p = os.path.join(out, alt)
        if os.path.exists(p):
            try:
                os.unlink(p)
                removed += 1
            except OSError:
                pass
    return {"normalized": normalized, "removed_variants": removed}
