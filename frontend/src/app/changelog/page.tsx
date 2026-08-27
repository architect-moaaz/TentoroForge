/**
 * /changelog — public-ish page showing what's shipped on the platform.
 *
 * Server Component. Content is embedded as a constant below and rendered
 * with ReactMarkdown. When updating: also update /CHANGELOG.md at the
 * repo root to keep both in sync (the repo file is the canonical source
 * for git history + GitHub display).
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Changelog · Tentoro Forge",
  description: "What's shipped on the Tentoro Forge platform.",
};

// -----------------------------------------------------------------------
// Content — keep in sync with /CHANGELOG.md at repo root.
// -----------------------------------------------------------------------
const CHANGELOG = `
# Changelog

User-visible changes to the Tentoro Forge platform. Newest first.

**Icons:** 🐛 bug fix · ✨ new capability · 🎨 UX polish · ⚡ reliability / speed

---

## 2026-07-29

### UAT bug sweep — B-021 series (Planters / Nursery Management)
- ✨ **Cart runtime primitive** — every generated app now has a \`forge_cart\` table, \`/api/cart/*\` endpoints, and 4 registered components (\`AddToCart\` / \`CartBadge\` / \`CartPanel\` / \`CartPage\`). A commerce-worded brief marks the saleable entity \`commerce: true\` and the components auto-place on list rows, detail CTA, and shell nav. \`/cart\` page is auto-generated. Payment is a form field (real gateway integration is a separate build). (B-021.4)
- 🐛 **"batchs" typo class killed permanently** — deterministic English pluralizer (\`-ch/-sh/-x/-y/-fe\` + irregulars + zero-plurals), plus a post-gen backstop that overwrites LLM-authored \`emptyStateText\` and standard button labels with computed values. LLM prompt tells the model NOT to author mechanical strings. (B-021.2)
- 🐛 **Edit forms actually pre-fill** — control-type hydration table in the form renderer: FK-Select coerces from UUID, DatePicker from ISO, Checkbox from postgres string-boolean, KeyValueInput from jsonb object, FileUpload from URL. Deferred hydration when defaults arrive after mount. (B-021.6)
- 🐛 **Product-shaped entities get a photo field** — planner heuristic: entities matching product/media patterns (Plant, Product, Recipe, Vehicle, Property, Room, Menu, Post, Event, …) or \`commerce=true\` or briefs mentioning photos/gallery get \`photoUrl\` field auto-added. (B-021.7)
- 🐛 **Empty FK dropdowns unblock the form** — every FK column now maps to a declared entity; missing targets get a minimal stub so seed synth populates them. Select components with 0 options and an \`inlineAdd\` route render "+ Add new X →" instead of dead-ending. (B-021.8)
- 🐛 **List/detail data doesn't flash-reflow** — mandatory \`isLoading\` skeleton contract on Table + DescriptionList: matching-dimension placeholder inside the same chrome so layout is stable when data lands. (B-021.5)
- 🎨 **Sidebar title wraps + tooltips instead of cropping** — SideNav \`.tf-brand\` gets HTML \`title=\` on hover and a 2-line wrap policy. Long brand names like "Planters Nursery Management" stay readable. (B-021.1)
- 🎨 **Card children can never collide** — Card body enforces \`flex flex-col gap-3\` so any two direct children get 12px separation even when the schema author omits a Stack wrapper. (B-021.3)

### Smith turn crash — shadow-import trap
- 🐛 **Every Smith message crashed with "cannot access local variable 'time'"** — \`_handle_smith_turn\` read \`time.monotonic()\` on entry, but a later \`import time\` inside the same function made Python treat \`time\` as function-local for the entire call, so the read at the top of the function raised \`UnboundLocalError\`. Same Python-scope-rule trap as B-022.2 (\`_progress\`), different name. Removed the local re-import (module already imports \`time\`). Also fixed three other latent instances in the pipeline (\`_run_relay_pipeline\` re-importing \`traceback\`, \`run_parallel_agents\` re-importing \`json\`, \`_emit_per_page\` re-importing \`Path\`). New AST regression test \`test_no_shadow_imports.py\` fails any function that re-binds a module-top import with an earlier read — zero-tolerance across the whole backend.

### UAT bug sweep — B-022 series (Recipe Collection)
- 🐛 **"cannot access local variable '_progress'" crash on plan-recreate** — \`_ProgressTracker\` was assigned midway through the pipeline but the discovery-else branch above tried to call it, tripping Python's local-scope rule. Hoisted the init to the top of both pipeline functions; AST regression test prevents recurrence. Also closes the "adjust strategy" and "add more instructions" flows that landed on the same crash. (B-022.1, B-022.2, B-022.3)
- 🐛 **Signup no longer crashes with React #31** — Heading / Alert / Banner now funnel raw children through \`formatValue\`, so a schema binding that resolves to an object gets stringified safely instead of throwing "Objects are not valid as a React child" and blanking the page. Universal fix — applies wherever a text-position renders a bound value. (B-022.4)
- 🐛 **\`/profile\` / \`/settings\` open the current user's record** — new route-intent classifier recognises singleton routes (profile, settings, account, preferences) and collapses the page to a \`{{currentUser}}\`-bound form. No more "Add User" leak. (B-022.6)
- 🐛 **\`/home-cooks\` / \`/reviewers\` show only the relevant role** — route-intent role-scope catalog (30+ tokens: cooks, chefs, reviewers, recruiters, customers, hosts, drivers, …) injects \`filter: {role: "<role>"}\` onto the list dataSource. (B-022.7)
- 🐛 **\`/my-recipes\` / \`/my-orders\` show your rows** — \`my-X\` routes classified as \`current_user_scope_list\` get \`filter: {ownerId: "{{currentUser.id}}"}\` on the list dataSource + any Table props.filter. New entries actually appear because the list scope matches. (B-022.9)
- 🐛 **Dead "View details" buttons repaired or flagged** — post-gen \`navigate_target_guard\` walks every button/link, verifies the target against real plan routes (including dynamic segments like \`/plants/[id]\`). Repairs to nearest known prefix, or marks \`data-nav-warn="broken"\` so the button is visible but the mismatch is observable. External URLs + dynamic bindings pass through untouched. (B-022.8)
- 🎨 **Dashboards stop feeling empty** — post-gen top-up: if a dashboard page has fewer than 3 content sections, appends a KPI row (MetricTile per primary entity), quick-actions row (Create buttons), and a recent-items card. Skips User / Role / Notification / audit entities so KPIs reflect the actual domain. Idempotent. (B-022.10)
- 🎨 **Bare Cards and heading-only Sections get their space filled** — post-gen \`bare_container_guard\` prunes truly-empty containers and appends a subtle EmptyState ("Nothing here yet.") to surfaces that carry a title but no body. Blank-space class killed at the structural level. (B-022.5 partial — spelling + blank spaces closed; text-alignment consistency stays as a design-agent quality concern.)

### Discovery
- 🐛 **Confidence floor** — when the LLM emits \`0%\` but the dossier is actually populated (real domain, patterns, entity suggestions), the value is auto-bumped to \`50%\` so downstream agents don't throttle their creativity on a false-low signal. Fallback dossiers keep their explicit low confidence. (B-003)
- 🎨 **Fast vs Complete picker collapses after choice** — the historical Discovery card no longer shows clickable Build Fast / Build Complete buttons after you've picked one. It shows a compact "Chosen: Build Fast" chip instead. (B-007)

### Smith build assistant
- 🐛 **Deploy asks don't punt** — "deploy the app" now calls \`publish\` automatically and relays the returned message. No more fabricated "transient server-side loop error" excuses redirecting you to the button.
- 🐛 **Answers are bound to the diff** — a "Done! I fixed 1, 2, 3, 4, 5" reply is now compared against the actual on-disk change list. If only 2 of 5 landed, the answer is refused and Smith is forced to rewrite honestly. (B-015 class)
- ✨ **\`plan_and_apply\` for feature asks** — "add candidate messaging" now produces one 3–5 step plan (add entity → add pages → add workflow → wire form) and executes all steps in one Smith turn. No more jerky one-tool-at-a-time flows.

### Generation progress (main pipeline)
- ⚡ **Authoritative per-phase progress** — backend emits real progress events at every phase transition. The ring moves at ~30–60s cadence, not by interpolation. (B-020.4)
- ⚡ **Real ETA** — the estimate now scales elapsed vs baseline, bounded so a slow phase stretches honestly but never blows up. No more 7 → 13 → 15 min swings. (B-020.3, B-020.7, B-017)
- 🎨 **Office panel percentage** now increments in sync with the chat ring. (B-004)

---

## 2026-07-28

### Deployed apps — Server Components render error
- 🐛 **Two-layer defense** on the platform: a React error boundary catches render/hydration errors and shows a small in-place error card (instead of blanking the page), plus a token-completeness backfill prevents the specific token-shape NPE that caused the crash on Leave Tracker.
- ⚠️ Existing broken deploys need **one more Publish click** to pick up the fix. New generations get both automatically. (B-005, B-019, B-020.8)

### Discovery / UX
- ✨ **Fast vs Complete comparison** — Discovery card now shows a side-by-side "what you get / what you miss" card so you know what a Fast build skips before you pick. (B-020.5)
- 🐛 **Publish button disabled until ready** — no more premature clicks during theme selection that error out. (B-020.6)
- 🐛 **Org logo upload** — added the missing \`POST /api/orgs/{id}/logo\` endpoint (previously silent 404). (B-020.1)

### Smith
- 🐛 **Chat history threading** — Smith now sees prior turns as real chat messages, so "did you fix it?" resolves to the earlier target instead of Smith asking for a route. (B-002, B-009)
- 🐛 **Mutation-intent guard** — when you ask for a change ("remove Department") but Smith didn't call a mutating tool, the "Done!" reply is refused.
- 🐛 **Menu/nav-fix path** — "recruiters menu shows users page" triggers a deterministic scope-check + nav context injection instead of a 12-option punt. Smith answers effectively.

---

## 2026-07-27

### Preview
- 🐛 **App preview iframe fixed** — proxies through the backend with \`basePath\` / \`assetPrefix\` env-gating so forms and assets load. Node.js installed in the backend Docker image. (B-013)

### Generation pipeline
- 🐛 **Seed sequencer FK ordering** — child rows no longer insert before parents; newly-added employees appear immediately in the app. Same fix clears several downstream symptoms. (B-012 cluster: B-005/011/012/014/015/019 originally)
- 🐛 **Shell sidebar menu sync** — sidebar is now derived from \`nav-flow.json\` in a post-generate pass. Every generated page shows up with an appropriate icon. (B-014)
- 🐛 **Publish counter increments** — was stuck at 0 because the increment wasn't wired to the deploy success event. (B-016)
- 🐛 **Smith fix-errors preserves shell** — Smith's fix path no longer writes a blank dashboard on top of your existing menu / nav / theme. (B-008, B-010)
- 🐛 **Row-detail 404 fix** — \`services\` → \`test_services\` alias added to the data router. (B-001)

### Deployment
- ⚡ **Vercel + Neon publish pipeline** — real-time deployment events, per-stage progress in the Publish dialog.

---

## Older milestones (curated)

- ✨ **Deterministic frontend authoring** — 12-phase pipeline (discovery → design → contracts → schema → business logic → API → auth → per-page schema → components → pages → workflows → seed → QA) with a plan-completeness validator + REVISE loop.
- ✨ **Component library** — 100+ components including data-viz (Gauge, Heatmap, Chart types), scheduling (Kanban, Calendar, ResourceTimeline), input (FileUpload, ColorPicker, MaskedInput), overlay (Popover, Drawer, ContextMenu).
- ✨ **AI-node runtime** — workflows can call \`ai_generate\`, \`ai_classify\`, \`ai_extract\` (with native PDF support) backed by real Claude via a per-project integration key.
- ✨ **File upload + storage** — pluggable disk/S3, \`forge_files\` table, signed URL support.
- ✨ **Platform integrations** — org-level secrets (Resend, S3, AI providers) encrypted at rest, injected into generated apps at deploy time.
- ✨ **Smith conversational build assistant** — ReAct loop with per-project app-map context, deterministic seams for add_entity / add_page / add_workflow / wire_form_to_workflow / edit_page / plan_and_apply, and structured overclaim / mutation-intent / deploy-intent guards.

---

## Still open

- **Multi-role planner** — Admin + Employee-style role splits sometimes emit only one actor's UI. (B-011)
- **"Connection lost" mid-generation** — needs specific repro to isolate SSE keep-alive vs backend idle timeout. (B-018)
- **Per-page sub-events during frontend authoring** — the ring moves at phase-level cadence today; per-page sub-events during the fat \`frontend_schema\` phase are a follow-up.
- **Legacy broken deploys** — apps published before 2026-07-28 still show the Server Components error; a fresh Publish click picks up the fix.
`;

export default function ChangelogPage() {
  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-12">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Changelog</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            What's shipped on the Tentoro Forge platform. Newest first.
          </p>
        </div>
        <a
          href="/"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          ← Home
        </a>
      </div>

      <article
        className="
          prose prose-sm max-w-none
          dark:prose-invert
          prose-headings:font-semibold
          prose-h1:hidden
          prose-h2:mt-8 prose-h2:text-lg prose-h2:border-b prose-h2:pb-1
          prose-h3:mt-4 prose-h3:text-sm prose-h3:uppercase prose-h3:tracking-wider prose-h3:text-muted-foreground
          prose-ul:my-2 prose-li:my-0.5
          prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-[0.85em] prose-code:before:content-none prose-code:after:content-none
          prose-hr:my-6 prose-hr:border-border
          prose-strong:text-foreground
        "
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{CHANGELOG}</ReactMarkdown>
      </article>

      <p className="mt-10 text-center text-xs text-muted-foreground">
        Report a bug or ask a question in your project chat — Smith will route
        it to the right place.
      </p>
    </main>
  );
}
