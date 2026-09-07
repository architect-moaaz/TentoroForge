"""Make the scaffold's session gate honour the app's auth-gating decision.

The app-foundation ships with two independent auth choke-points:

1. `(dashboard)/layout.tsx` — `if (!session) redirect("/login")`
2. `src/middleware.ts` — `withAuth` from next-auth that intercepts EVERY route
   BEFORE any page handler runs

For a gated app both are correct. For a public app (authGated=false) BOTH
must be neutralised — the layout gate alone is not enough because the
middleware bounces to /login before the page ever renders. This guard reads
`authGated` from nav-flow.json and, when the app is NOT gated, neutralises
both. Gated apps are left exactly as shipped. Deterministic + idempotent.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_GATE = 'if (!session) redirect("/login");'
_REPLACEMENT = "// public app (authGated=false): no session gate"

# Public-app middleware: same file signature Next.js expects (default export +
# `config`) but a no-op middleware that lets every request through. Keeps the
# withAuth import present but unused so IDE/tooling doesn't complain about a
# missing dep during the LLM regen — a subsequent full regen replaces the
# whole file anyway.
_PUBLIC_MIDDLEWARE = '''\
// public app (authGated=false): auth middleware neutralised by auth_gate_guard
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export default function middleware(_req: NextRequest) {
  return NextResponse.next();
}

export const config = {
  // Match nothing — keep the file valid but skip every request.
  matcher: [],
};
'''


def guard_auth_gate(output_dir: str) -> dict:
    root = Path(output_dir)
    nav = root / "src" / "contracts" / "nav-flow.json"
    if not nav.exists():
        return {"patched": 0}
    try:
        gated = bool(json.loads(nav.read_text(encoding="utf-8")).get("authGated"))
    except (json.JSONDecodeError, OSError):
        return {"patched": 0}
    if gated:
        return {"patched": 0}  # gate is correct as shipped

    patched = 0

    # 1. Layout-level gate (LLM-authored page-level check)
    layout = root / "src" / "app" / "(dashboard)" / "layout.tsx"
    if layout.exists():
        text = layout.read_text(encoding="utf-8")
        if _GATE in text:
            layout.write_text(text.replace(_GATE, _REPLACEMENT), encoding="utf-8")
            patched += 1

    # 2. Middleware-level gate (framework-level intercept, template file)
    #    Idempotent: only rewrite if the current contents actually use
    #    withAuth — otherwise assume it's already public or hand-edited.
    middleware = root / "src" / "middleware.ts"
    if middleware.exists():
        mw_text = middleware.read_text(encoding="utf-8")
        if "withAuth" in mw_text or "next-auth/middleware" in mw_text:
            middleware.write_text(_PUBLIC_MIDDLEWARE, encoding="utf-8")
            patched += 1

    if patched:
        logger.info(
            "auth_gate_guard: neutralised %d gate(s) for public app in %s",
            patched, output_dir,
        )
    return {"patched": patched}
