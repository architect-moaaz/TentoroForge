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

# The single authoritative config — THE one source. app_emitter imports
# `AUTHORITATIVE_NEXT_CONFIG` from here rather than keeping its own copy: two
# copies is exactly how `basePath` came to be added to the (orphaned) template
# next.config.ts for the preview proxy and NOT to the .js that actually ships,
# so the preview never ran under its prefix.
#
# basePath / assetPrefix: the platform iframes the generated app behind a
# reverse proxy at /api/projects/<id>/preview/serve/… (preview.py sets
# NEXT_BASE_PATH / NEXT_ASSET_PREFIX). Without these, Next emits page + asset
# URLs at the root — /_next/…, /login — so from inside the iframe every asset
# 404s and the auth middleware's /login redirect loops. Env-gated: unset (the
# Vercel deploy case) → the spreads collapse to {} and the app runs at root,
# exactly as before.
#
# outputFileTracingIncludes: Server Components read src/schemas/**/*.json and
# src/contracts/*.json, and rules/engine.ts reads rules/** — all via fs at
# render time, none a static import Next's file-tracer can see, so each has to
# be forced into every serverless function's trace or Vercel hits ENOENT on
# `/var/task/src/schemas/home.json` (SSR 500s) or silently disables every
# business rule.
_AUTHORITATIVE = (
    "/** @type {import('next').NextConfig} */\n"
    "// Preview-behind-prefix mode — see services/next_config_guard.py.\n"
    "const PREVIEW_BASE_PATH = process.env.NEXT_BASE_PATH || undefined;\n"
    "const PREVIEW_ASSET_PREFIX = process.env.NEXT_ASSET_PREFIX || PREVIEW_BASE_PATH;\n"
    "module.exports = {\n"
    "  reactStrictMode: true,\n"
    "  ...(PREVIEW_BASE_PATH ? { basePath: PREVIEW_BASE_PATH } : {}),\n"
    "  ...(PREVIEW_ASSET_PREFIX ? { assetPrefix: PREVIEW_ASSET_PREFIX } : {}),\n"
    '  transpilePackages: ["@tentoroforge/engine", "@tentoroforge/library", '
    '"@tentoroforge/renderer", "@tentoroforge/schema"],\n'
    '  serverExternalPackages: ["isomorphic-dompurify", "jsdom"],\n'
    '  distDir: process.env.NEXT_DIST_DIR || ".next",\n'
    "  outputFileTracingIncludes: {\n"
    '    "/**": ['
    '"./src/schemas/**/*.json", "./src/contracts/**/*.json", "./registry.json", '
    '"./rules/**/*", "./src/rules/**/*"'
    "],\n"
    "  },\n"
    "  typescript: { ignoreBuildErrors: true },\n"
    '  images: { domains: ["localhost"] },\n'
    "};\n"
)

#: Public name for the one authoritative config, imported by app_emitter so the
#: emitted file and this backstop can never drift apart again.
AUTHORITATIVE_NEXT_CONFIG = _AUTHORITATIVE

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
    # Missing the preview basePath wiring → the app cannot run under the
    # editor's reverse proxy (blank preview + /login redirect loop). A config
    # written before this existed has no NEXT_BASE_PATH reference; heal it.
    if "NEXT_BASE_PATH" not in text:
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
