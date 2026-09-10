import fs from "fs";
import path from "path";

// TWO ROOTS, ONE SOURCE OF TRUTH. The canonical, user-authored token file is
// `output/<id>/src/theme/tokens.custom.json` — that is what the Forge theme
// editor (`routers/output_projects.py` GET/POST `/{id}/theme`), the design
// compiler, the Figma style extractor and the render preview
// (`apps/render-scaffold/src/lib/loadTokens.ts`, handed the PROJECT root) all
// use. This app's cwd is `output/<id>/app`, one level below, so resolving
// `src/theme/tokens.custom.json` against cwd looked for a file the platform
// had no writer for: every read was ENOENT, the bare catch swallowed it,
// `tokens.server.ts` merged defaultTokens with null, and a user's edited
// palette (`{"color":{"primary":{"50":"#c0c8d3"}}, "radius":{"scale":"soft"}}`
// in output/gh0mlpbp) rendered in the preview and vanished in the built app —
// with neither side reporting a disagreement.
//
// The build now mirrors the canonical file into the app root
// (`runtime_injector._mirror_theme_tokens`), because a deployed bundle ships
// `app/` alone and cannot reach the parent. The parent is still probed second
// so that (a) every project built before that mirror existed keeps working
// without a rebuild, and (b) a theme edit made after the last build is live
// immediately under `next dev`.
const CANDIDATES = [
  path.resolve(process.cwd(), "src/theme/tokens.custom.json"),
  path.resolve(process.cwd(), "..", "src/theme/tokens.custom.json"),
];

export function loadCustomTokens(): Record<string, Record<string, string>> | null {
  for (const p of CANDIDATES) {
    try {
      return JSON.parse(fs.readFileSync(p, "utf8"));
    } catch {
      // try the next root
    }
  }
  return null;
}
