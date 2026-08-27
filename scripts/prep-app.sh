#!/usr/bin/env bash
# prep-app.sh <output-dir>
# Make a freshly-generated app CRUD-ready and VERIFY it:
#   schema-barrel reconcile · owner-FK types · theme floor · drizzle config ·
#   migrate · seed admin · auth check.  Prints ✅/❌ per step.
set -uo pipefail

APP_IN="${1:?usage: scripts/prep-app.sh <output-dir>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
PY="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
APP="$(cd "$APP_IN" && pwd)"
cd "$APP"

DBURL="$(grep -E '^DATABASE_URL' .env.local 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"'')"
echo "▶ app: $APP"
echo "▶ db:  $(echo "$DBURL" | sed 's#//[^@]*@#//...@#')"

echo "▶ [1/6] reconcile schema barrel / FK types / theme + write drizzle config"
"$PY" - "$APP" <<PYEOF
import sys
sys.path.insert(0, "$BACKEND")
app = sys.argv[1]
from pathlib import Path
from services.schema_barrel import reconcile_db_schema_barrel
from services.user_fk_types import reconcile_user_fk_types
from services.theme_tokens import complete_light_theme
print("   barrel:", reconcile_db_schema_barrel(app).get("removed_shadow"))
print("   fk:", reconcile_user_fk_types(app).get("columns"))
print("   theme:", complete_light_theme(app).get("added"))
Path(app, "drizzle.config.ts").write_text(
  'import { defineConfig } from "drizzle-kit";\n\n'
  'export default defineConfig({\n  schema: "./src/db/schema",\n  out: "./drizzle",\n'
  '  dialect: "postgresql",\n  dbCredentials: { url: process.env.DATABASE_URL! },\n});\n')
print("   drizzle.config: ok")

# Root redirect: avoid "/"->"/" loops (ERR_TOO_MANY_REDIRECTS).
import json
navp = Path(app, "src", "contracts", "nav-flow.json")
initial = "/home"
if navp.exists():
    nav = json.loads(navp.read_text())
    pages = nav.get("pages") or []
    by_id = {p.get("id"): p for p in pages}
    ip = by_id.get(nav.get("initialPage")) or (pages[0] if pages else {})
    route = ip.get("route")
    if route and route != "/":
        initial = route
    else:
        sf = ip.get("schemaFile") or ""
        stem = sf.rsplit("/",1)[-1].removesuffix(".json") if sf else (ip.get("id") or "")
        if stem and stem not in ("index",""):
            initial = "/" + stem
        else:
            initial = next((p["route"] for p in pages if p.get("route") and p["route"]!="/"), "/home")
Path(app, "src", "app", "page.tsx").write_text(
  'import { redirect } from "next/navigation";\n'
  f'export default function RootPage() {{ redirect("{initial}"); }}\n')
print("   root redirect:", initial)

# Single next.config.js (dual config drops transpilePackages -> "self is not defined").
Path(app, "next.config.js").write_text(
  "/** @type {import('next').NextConfig} */\nmodule.exports = {\n  reactStrictMode: true,\n"
  '  transpilePackages: ["@tentoroforge/engine", "@tentoroforge/library", "@tentoroforge/renderer", "@tentoroforge/schema"],\n'
  '  serverExternalPackages: ["isomorphic-dompurify", "jsdom"],\n  typescript: { ignoreBuildErrors: true },\n'
  '  images: { domains: ["localhost"] },\n};\n')
for alt in ("next.config.ts","next.config.mjs"):
    ap = Path(app, alt)
    if ap.exists(): ap.unlink()
print("   next.config: single .js")

# Completeness: synthesize any missing create page for entities with a Create workflow.
from services.component_alias import normalize_component_aliases
print("   component aliases:", normalize_component_aliases(app).get("changed") or "none")
from services.crud_page_coverage import ensure_crud_pages
_cpc = ensure_crud_pages(app)
print("   create pages added:", _cpc.get("created") or "none")
from services.auth_secret import ensure_unique_auth_secret
print("   unique auth secret:", ensure_unique_auth_secret(app).get("set"))
from services.auth_email_ci import make_email_login_case_insensitive
print("   email login CI:", make_email_login_case_insensitive(app).get("patched"))
from services.schema_page_live import make_form_pages_live
print("   form pages live:", make_form_pages_live(app).get("patched"))
from services.api_route_prune import prune_entity_crud_routes
_pr = prune_entity_crud_routes(app)
print("   pruned per-entity CRUD routes:", len(_pr.get("deleted") or []), "(Data Engine catch-all is sole CRUD path)")
from services.schema_pipeline import _regenerate_route_registry
_regenerate_route_registry(app); print("   route registry: regenerated")
from services.schema_version_fix import fix_schema_versions
print("   schemaVersion fix:", fix_schema_versions(app).get("fixed") or "none")
PYEOF

echo "▶ [2/6] npm install (if needed)"
[ -d node_modules ] || npm install --silent 2>&1 | tail -1

echo "▶ [3/6] migrate"
DATABASE_URL="$DBURL" npx drizzle-kit push --force 2>&1 | tail -1

echo "▶ [4/6] seed admin"
"$PY" - "$APP" <<PYEOF
import sys; sys.path.insert(0, "$BACKEND")
from pathlib import Path
from services.seed_backstop import ensure_seed_file
ensure_seed_file(Path(sys.argv[1]))
PYEOF
DATABASE_URL="$DBURL" npx tsx src/db/seed.ts 2>&1 | tail -1

echo "▶ [5/6] verify auth (admin@example.com / admin123)"
cat > .prep_auth.ts <<'TSEOF'
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { eq } from "drizzle-orm";
import bcrypt from "bcryptjs";
async function main(){
  const [u] = await db.select().from(users).where(eq(users.email,"admin@example.com")).limit(1);
  if(!u){console.log("   AUTH: ❌ no admin user");return;}
  const ok = await bcrypt.compare("admin123",(u as any).password);
  console.log("   AUTH:", ok ? "✅ login works" : "❌ password mismatch");
}
main().then(()=>process.exit(0)).catch(e=>{console.log("   AUTH: ❌",String(e).slice(0,90));process.exit(0);});
TSEOF
DATABASE_URL="$DBURL" npx tsx .prep_auth.ts 2>&1 | grep "AUTH:" | head -1
rm -f .prep_auth.ts

echo "▶ [6/6] ✅ prepped. Run it:"
echo "     cd \"$APP\" && rm -rf .next && DATABASE_URL='$DBURL' npm run dev"
