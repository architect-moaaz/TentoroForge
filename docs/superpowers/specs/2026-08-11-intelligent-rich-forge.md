# Intelligent + rich Forge — the substrate

**Status**: spec, not implemented.
**Owner**: pipeline + Smith + design-quality workstreams (joint).
**Companions**:
- `2026-08-07-brief-canonical.md` (A — canonical brief + visual fidelity)
- `2026-08-07-domain-form-intelligence.md` (B — form UX)
- `2026-08-07-design-polish.md` (C — dashboards / voice / motion)
- `2026-08-07-domain-intelligence-cleanup.md` (D — bypass cleanup)
- `2026-08-08-advanced-ux.md` (E — interactions / a11y / advanced patterns)
- `2026-07-14-canonical-resource-registry.md` (single naming authority)
- `2026-07-13-resource-binding-contract.md` (bind-only-to-real-resources)
- `2026-08-01-self-verify-pass-design.md` (SV, the verify half of the intelligence loop)
- `2026-08-06-vf-self-healing.md` (self-healing — the recover half)

This spec **replaces the substrate** that A–E all sit on. It doesn't
re-scope any of them; it makes their assumptions load-bearing:

- A/B/C/D/E all assume a **single stable notion of "what kind of app
  this is"**. Today we have two overlapping, partial notions
  (`domain` in `domain_context.py`, `archetype` in `archetype_*.py`)
  and no notion of **topology** (shell vs. no shell, gated vs. open,
  hero vs. list-first). This spec introduces the topology axis and
  reconciles the naming so every downstream spec reads a single set
  of values.
- A/B/C/D/E all assume the pipeline is capable of **plan → act →
  verify → recover** as a first-class loop. Today the loop exists in
  pieces (SV runs at the end, self-healing runs on failure, plan-and-
  apply runs in Smith) but is not uniform. This spec makes the loop
  uniform across every generation stage and every Smith turn.
- A/B/C/D/E all assume **rich-by-construction**: aesthetic profiles,
  signature moves per archetype, surface treatments applied
  deterministically. Today rich UI is emergent (the LLM sometimes
  authors it, the design critic sometimes catches its absence).
  This spec makes rich the guaranteed baseline.

The name of the substrate is deliberate: **intelligent + rich**.
"Intelligent" = plans, verifies, recovers, learns — like Claude Code
operates on our codebase. "Rich" = visually distinctive by
`(shape × archetype × industry)`, no generic-shadcn look — like AC10
copy proved is possible when we hand-tune every seam.

---

## Problem

Three concrete gaps, each with a canonical failure mode.

### Gap 1 — no topology axis

`plan.py` today captures **what the app does** (`archetype`) and
**what industry it lives in** (`domain`, soon `industry`). It does not
capture **what shape the app takes**:

- Does it have a dashboard shell with a sidebar, or is it a single
  full-bleed page?
- Is auth a modal on the same page, a separate `/login` route, or
  absent entirely?
- Is the primary interaction a hero-CTA moment, a data grid, a card
  feed, or a form?
- Does the app orchestrate work between multiple actors, or is it a
  single-user utility?

The canonical failure: **Snap2App-style consumer utility generated
as a dashboard-with-sidebar with `/login` route and empty menu.**
AC10 copy (`output/dxlc5m31`) required ~15 manual patches to undo the
shell, remove the login route, wire the hero pages via
`_figmaDerived: true`, and mount `<Toaster />` at root. Every one of
those patches would have been unnecessary if the pipeline knew "this
is a consumer utility, not an internal workspace."

Downstream, every stage guesses topology:

- `select_frame` assumes a shell exists.
- `derive_actor_onboarding` produces a `/login` route by default.
- `shell_menu_sync` synthesizes menu entries for pages that shouldn't
  be in a menu.
- `translate_workflow` produces awaiting-dispatch forms even when
  the shape calls for fire-and-forget.
- `post_generate_fixes` runs guards designed for internal apps on
  consumer apps.

### Gap 2 — inconsistent intelligence loop

Claude Code's baseline behavior on this codebase:

1. Read enough context to understand what's true right now.
2. Plan a change (Edit spec, list files to touch).
3. Apply the change.
4. Verify: types, tests, visual, logs — whichever the change would
   affect.
5. On failure: recover (retry with different approach, fall back to
   a template, escalate to the user).

Forge's pipeline and Smith do parts of this, unevenly:

| Loop stage | Pipeline today | Smith today |
|---|---|---|
| Read context | partial — planner reads brief; downstream stages re-derive | `smith_memory` + `build_app_map` — good |
| Plan | `plan.py` is authoritative for the initial gen; downstream stages don't plan | `plan_and_apply` — good |
| Act | every stage acts | tools act |
| Verify | `self_verify_pass` at the end only | none per turn |
| Recover | `vf-self-healing` on failure; per-agent retry | DUR-2 retry-break, uneven |

The canonical failure: **Smith turn does the wrong thing, user has
to catch it and correct manually.** Every "no, that's wrong" from
the user is a verify-loop that Smith should have run itself.

### Gap 3 — richness is emergent, not guaranteed

The design critic (Angle B) runs in shadow mode. Aesthetic profiles
exist as prompts, not as deterministic surface treatments. Signature
moves per archetype (the pulsing scan orb, the kanban lane-swap,
the metric-row sparkline) are LLM-authored when they appear at all,
and absent when they don't.

The canonical failure: **generated app renders with default
shadcn-clone look — grey cards, no gradient, no hero, no signature
moment — and the user's reaction is "this looks generic."** AC10
copy is proof that the same input, hand-tuned, can produce a
distinctive product. The pipeline needs to reach that bar by
construction.

---

## Solution

Three substrate pieces, each cures one gap. They install in order
(P1 → P2 → P3), because P2 assumes P1 and P3 assumes both.

### P1 — Four-axis topology

Introduce two new axes (`app_shape`, `runtime_context`), pluralize
one (`archetype` → `archetypes`), rename one (`domain` →
`industry`). All four axes are first-class fields on `plan.py`,
all four are LLM-authored, all four are read by every downstream
stage in a defined priority order.

### P2 — Uniform intelligence loop

Formalize plan → act → verify → recover as a repeated cycle across
every generation stage and every Smith turn, with a shared context
substrate (`app_map` + registry + `smith_memory`) that both pipeline
and Smith read.

### P3 — Rich by construction

Six aesthetic profiles catalogued (glass-dark, carbon, polaris,
material-3, fluent-2, clean-editorial). Selection is a derived
function over `ShapeProfile` primitives × `industry` — not a
shape-label lookup. Signature moves catalogued per archetype.
Deterministic surface treatment pass applied post-gen. Design
critic promoted from shadow to enforcement.

Rest of this document specs each in the depth needed to implement.

---

## P1 — Three-axis topology

### The axes

**`app_shape`** — *what kind of thing this app is*, topologically.
**Not** a label picked from a closed enum. A **profile composed from
primitives**, authored by the LLM per app.

The reason: naming a bucket (`consumer-utility`) collapses apps that
share nothing structurally. Snap2App is hero + camera + result;
Spotify is player-bar + browse; Instagram is feed + capture; Uber is
map + booking overlay; Duolingo is lesson-card + streak; a tip
calculator is one form. If we force them into `consumer-utility`,
every downstream stage reads "no shell, hero, gradient CTA" and
produces the same wrong app for five of the six.

Instead: the LLM composes a `shape_profile` from a small set of
independent primitives. Each primitive has a **small closed value
set** (validators enforce membership). The LLM picks each value
based on the brief. Two consumer apps with different structures
end up with different profiles automatically.

The vocabulary:

| Field | Values | Question it answers |
|---|---|---|
| `layout.shell` | `none`, `sidebar`, `header`, `three-pane`, `bottom-tabs`, `map-canvas` | Is there persistent chrome? What shape? |
| `layout.hero` | `none`, `full-bleed-gradient`, `media-hero`, `metric-row`, `player-bar`, `map-canvas`, `feed-header`, `now-playing` | What dominates the first view? |
| `layout.primaryInteraction` | `cta-button`, `capture`, `search`, `feed`, `player`, `map`, `chat`, `lesson`, `data-grid`, `card-grid`, `form` | What is the user mostly doing? |
| `layout.density` | `spacious`, `comfortable`, `dense` | How much per screen? |
| `auth.surface` | `none`, `modal`, `route`, `sso-only` | How does the user get in? |
| `auth.gating` | `none`, `on-action`, `on-load` | When do we require login? |
| `nav.menu` | `none`, `sidebar-links`, `header-links`, `bottom-tabs`, `drawer`, `command-palette` | How does the user get around? |
| `nav.back` | `history`, `crumb`, `close-modal`, `none` | How does the user retreat? |
| `workflows.executionMode` | `fire-and-forget`, `await-with-progress`, `streaming`, `background-with-notification` | What happens on submit? |
| `data.readShape` | `single-record`, `list`, `feed`, `grid`, `map-pins`, `board`, `timeline` | How is data presented? |
| `data.denormalization` | `none`, `moderate`, `aggressive` | Do FKs get flattened for display? |
| `identity.usageMode` | `single-session`, `returning-personal`, `multi-user-team`, `public-anonymous` | Who uses this and how often? |

**~12 primitives, ~4–6 values each. The combinatorial space covers
essentially every app.** Snap2App = `{shell: none, hero: full-bleed-
gradient, primaryInteraction: capture, auth: modal-on-action, nav:
none, workflows: fire-and-forget, data.readShape: list, identity:
single-session}`. Spotify = `{shell: sidebar, hero: player-bar,
primaryInteraction: player, auth: route-on-load, nav: sidebar-links,
data.readShape: grid, identity: returning-personal}`. Instagram =
`{shell: bottom-tabs, hero: feed-header, primaryInteraction: feed,
auth: route-on-load, nav: bottom-tabs, data.readShape: feed,
identity: returning-personal}`.

None share a label; each downstream stage reads exactly the
primitives it cares about.

**Optional descriptor** — the LLM MAY tag the profile with a
human-readable `label` (e.g. `"capture-analyze-utility"`, `"music-
player"`, `"social-feed"`). The label is for humans (design critic
rubric, analytics, telemetry). **Downstream stages never read the
label** — only the primitives. Adding a new kind of app never
requires editing the taxonomy or shipping code; the LLM composes
the profile from the same primitives.

**`archetypes`** — *what capabilities the app provides* — **now
plural, and LLM-composed the same way `app_shape` is**. Existing
`archetype: str` (singular) fits Snap2App but not Workday, and
picking from a closed enum doesn't fit any long tail. Two
authoring paths, both LLM-driven, per module:

1. **Pick a recipe** — when a known pattern fits, the LLM references
   a named recipe from `backend/archetypes/recipes.json`. A recipe
   is a concrete stack: entity template + workflow template +
   component set + signature moves. Examples: `visual_product_search`
   (camera + ai_extract + parallel MCP scrape + aggregate),
   `checkout` (cart + address + payment + review + confirm),
   `chat` (thread list + message pane + input + presence). Recipes
   grow by JSON edit; no code change to add a new one.

2. **Compose capabilities** — when no recipe fits, the LLM composes
   from a small closed vocabulary of **capability primitives**:

    | Field | Values |
    |---|---|
    | `read.pattern` | `single-record`, `list`, `grid`, `board`, `tree`, `timeline`, `feed`, `map-pins`, `chart` |
    | `read.grouping` | `none`, `status`, `date`, `category`, `assignee`, `hierarchy` |
    | `write.pattern` | `none`, `inline`, `create-form`, `edit-form`, `wizard`, `drag`, `bulk-action` |
    | `write.integrity` | `direct`, `approval-required`, `audit-logged` |
    | `interactions` | multi-select from `[drag-reorder, drag-between-groups, bulk-select, filter, sort, group-by, inline-edit, live-follow, infinite-scroll, pinch-zoom, keyboard-nav, right-click-context]` |
    | `presentation.itemShape` | `card`, `row`, `tile`, `dot`, `node`, `bar`, `pin` |
    | `state.realtime` | `none`, `poll`, `stream` |

   The LLM emits values per primitive. Signature moves attach to
   the primitives (any composition with `interactions:
   [drag-between-groups]` gets the lane-swap animation; any with
   `read.pattern: map-pins` gets the pin-cluster treatment), so
   the pipeline knows what to render even without a recipe name.

**Recipes are shortcuts, not the primary vocabulary.** A recipe
internally declares its capability primitives, so downstream stages
never branch on the recipe name — they read the resolved
primitives. `visual_product_search` internally resolves to
`{read.pattern: list, write.pattern: capture, interactions:
[live-follow], state.realtime: stream}` plus a pre-authored
workflow template. This means: a novel module composed
capability-by-capability still gets full pipeline support; a
recipe module gets the same support plus the recipe's canned
workflow and component set.

Not a taxonomy of apps, a taxonomy of *core interactions* —
composed, not enumerated.

**`industry`** — *what semantic world the app lives in* — the
renamed `domain`. Open string with a suggested set:
`healthcare`, `legal`, `consumer-retail`, `fintech-brokerage`,
`hr-payroll`, `recruitment`, `consumer-mobility`,
`consumer-food-delivery`, etc. LLM MAY invent a new industry
value when nothing fits; downstream stages that key on industry
(palette bias, aesthetic-profile picker) fall back to the closest
match via LLM classification, not a rules table.

**`runtime_context`** — *what platform capabilities the app needs
at runtime*, orthogonal to shape/archetype/industry. Multi-select
from a closed vocabulary — no app "shape" implies these; Swiggy
needs `geo` but Uber needs `geo` too, and a workspace CRM might
need `geo` for its "field visits" module. Not derivable from
shape.

| Value | What it enables |
|---|---|
| `geo` | GPS + geocoding + reverse-geocoding; location bootstrap; "near me" queries |
| `camera` | capture (photo + video); barcode/QR scan |
| `microphone` | audio input; voice notes; speech-to-text |
| `push_notifications` | background delivery; badge counts; deep-link on tap |
| `offline_sync` | local-first storage; conflict resolution; sync queue |
| `background_tasks` | long uploads; workers that survive app-close |
| `sensors` | accelerometer + gyro + health (HealthKit / Health Connect) |
| `contacts` | phonebook read; invite flows |
| `photo_library` | gallery picker; album access |
| `biometric_auth` | Face ID / Touch ID / Android biometrics |
| `wallet_pass` | Apple Wallet / Google Pay pass issuance |
| `deep_linking` | universal-link URL handlers; app-scheme; app-to-app share receive |
| `voice_assistant` | Siri Shortcuts / Google Assistant intents |
| `haptic_feedback` | rumble; success/warning taptic |
| `clipboard_share` | cross-app share sheet; paste-detect |

Each value corresponds to a runtime-integration bundle: permission
prompts, native module imports, provider/hook wiring, and the
platform-side plumbing that already exists via
`platform_integrations` and the mobile scaffolding pipeline.
`runtime_context: [geo, push_notifications]` on Swiggy's plan
triggers gen-time emission of the geo-bootstrap provider, the
Expo location permission block in `app.json`, and the FCM/APNs
push registration — same mechanism that ships integration
providers today, driven by the plan instead of a per-recipe
guess.

### Why four independent axes

Every real generation makes four independent decisions:

- *"Does this app have a sidebar?"* — an `app_shape` question. Two
  apps in the same industry (Snap2App and a retail-analytics
  dashboard) answer differently.
- *"Which core interactions does this app need?"* — an
  `archetypes` question. Workday and a single-purpose org chart
  both live in `hr-payroll` but Workday has 8 modules and the org
  chart has 1.
- *"What palette / typography / iconography feels native?"* — an
  `industry` question. Two apps with the same shape and archetypes
  (healthcare CRUD vs. fintech CRUD) answer differently.
- *"Which platform capabilities does this app need at runtime?"* —
  a `runtime_context` question. Not derivable from the other
  three: Uber, Swiggy, and a field-service CRM all need `geo`;
  Snap2App and Shazam both need `camera` and `microphone`
  respectively despite being visually opposite.

Folding these into one axis creates ambiguity — is
`visual_product_search` a shape, a capability, an industry hint,
or a camera-permission signal? Splitting them lets each stage
read the axis it cares about. And plurality on `archetypes` +
multi-select on `runtime_context` lets the same substrate cover
both Snap2App (one archetype, one context capability) and Swiggy
(ten archetypes, four context capabilities) without a separate
"big-app pipeline."

### LLM-primary authorship, on every axis

**All four axes are authored by the LLM.** The planner reads the
brief once and emits `app_shape`, `archetypes`, `industry`, and
`runtime_context` in one structured call. This is the whole
uniqueness story: apps land on different profiles because a
reasoning model wrote them in response to a specific brief, not
because a rules table matched keywords.

The deterministic fallback detectors mentioned throughout this
spec are **safety nets for API outage, not routine backstops**.
When they fire, the pipeline emits a `LLM_UNAVAILABLE` finding
into the plan report, logs a warning, and marks the generation
as "produced under degraded conditions" so we can measure how
often it happens (target: <1% of gens). We do not quietly ship
fallback-shaped apps and call them normal.

The one hard rule: **no axis has a silent default that the
pipeline picks on the LLM's behalf**. Every plan.json field has
either an LLM-authored value, a user override, or a loud fallback
finding. No third path.

### Coverage verdicts — honest scope

The four axes cover a huge space (~80% of what people ask for),
but they don't cover everything. Games, creative authoring tools
(Photoshop, Ableton, video editors, IDEs, DAWs), spatial / AR /
VR, voice-only conversational, embedded firmware, and browsers
are examples of what Forge is not for. Silently generating a
broken app for these helps nobody.

The planner emits a `coverage_verdict` on every generation as
part of its normal structured output — an honest assessment of
whether the brief fits the substrate. Three possible statuses,
each with a defined pipeline response:

**`in_scope`** — the brief composes cleanly from the four axes'
primitives + reference apps + recipes. The vast majority of
generations. Pipeline proceeds normally; no side effects.

**`extension_needed`** — the substrate is close but missing one
dimension (a new primitive value, a small new axis). The planner
generates the nearest-supported composition and populates
`missing_dimensions` + `suggested_extensions`. Pipeline proceeds
BUT appends a structured entry to `substrate_gap_log.jsonl`:

```jsonl
{ "ts": "2026-08-14T…", "gen_slug": "abc123",
  "brief_summary": "Chrome extension for markdown-to-slack…",
  "missing_dimensions": ["deployment_target=extension"],
  "suggested_extensions": [
    "add `deployment_target` axis alongside `runtime_context`",
    "values: web|mobile|extension|watch|desktop|kiosk|tv" ],
  "nearest_supported": "web app with a bookmarklet-style overlay" }
```

Team reviews the log weekly. Any gap that appears in ≥3 real
briefs across ≥2 weeks graduates to a first-class primitive via
JSON edit (never speculative). The substrate grows on evidence,
not opinion.

**`out_of_scope`** — the brief asks for something structurally
outside Forge (game engine, video editor, spatial UI, firmware,
etc.). **Pipeline stops** before generation. Frontend surfaces a
structured `OutOfScopeCard`:

> Forge builds data-driven web and mobile apps. Your brief asks
> for a **real-time multiplayer game with physics**, which needs
> a game engine, not an app framework.
>
> Nearest thing Forge can build: **a game-catalog +
> leaderboard + player-stats app** that would sit alongside the
> game itself.
>
> [ Generate the nearest supported instead ]  [ Refine my brief ]
> [ Cancel ]

User picks. No silent failure, no generation nobody wants, no
broken app spent tokens making.

Same principle as the LLM-fallback rule above: **the pipeline
never silently generates something outside its ability**. Either
it succeeds honestly, or it refuses honestly with a structured
redirect.

### Data model

`plan.py`:

```python
class ShapeProfile(BaseModel):
    # Every field is required; every value is validated against
    # the closed set defined in the vocabulary table above.
    layout: LayoutSlice          # shell, hero, primaryInteraction, density
    auth: AuthSlice              # surface, gating
    nav: NavSlice                # menu, back
    workflows: WorkflowSlice     # executionMode
    data: DataSlice              # readShape, denormalization
    identity: IdentitySlice      # usageMode
    label: str | None = None     # optional descriptor; humans only

class Capabilities(BaseModel):
    """Small closed vocabulary of interaction primitives. Values
    validated against the vocabulary table above."""
    read: ReadSlice           # pattern, grouping
    write: WriteSlice         # pattern, integrity
    interactions: list[str]   # closed set, multi-select
    presentation: PresSlice   # itemShape
    state: StateSlice         # realtime

class ArchetypeInstance(BaseModel):
    """One module within the app. Large apps have many; small apps
    have one. Every instance binds to entities and MAY override the
    outer app_shape locally (Uber's outer shell is map-canvas but
    its payment_methods module is a form).

    Authoring: EITHER `recipe` (name from recipes.json — pipeline
    resolves capabilities + workflow + components from the recipe)
    OR `capabilities` (LLM composed from primitives). If both are
    set, `capabilities` overrides the recipe's defaults field by
    field — a recipe with a local twist."""
    name: str                                # e.g. "checkout_flow"
    recipe: str | None = None                # optional recipe name
    capabilities: Capabilities | None = None # composed primitives
    entities: list[str]                      # entity slugs this module touches
    routes: list[str]                        # e.g. ["/checkout", "/checkout/pay"]
    local_shape: ShapeProfileOverride | None = None
    label: str | None = None                 # human descriptor

    @validator
    def one_of_recipe_or_capabilities(cls, values):
        if not values.get("recipe") and not values.get("capabilities"):
            raise ValueError("must set recipe or capabilities (or both)")
        return values

class CoverageVerdict(BaseModel):
    """Planner's honest assessment of whether the brief fits the
    substrate. Emitted alongside the four axes on every generation."""
    status: Literal["in_scope", "extension_needed", "out_of_scope"]
    reason: str                              # one-sentence explanation
    missing_dimensions: list[str] = []       # what the axes don't capture
    suggested_extensions: list[str] = []     # concrete axis / vocabulary
                                             # additions that would fit
    nearest_supported: str | None = None     # closest adjacent app Forge
                                             # CAN build, when status !=
                                             # in_scope

class Plan(BaseModel):
    archetypes: list[ArchetypeInstance]      # LLM-authored (plural)
    industry: str                            # LLM-authored (renamed from `domain`)
    app_shape: ShapeProfile                  # LLM-authored profile, not a label
    runtime_context: list[str]               # LLM-authored, multi-select
                                             # from runtime_context vocabulary
    coverage_verdict: CoverageVerdict        # LLM-authored honest assessment
    entities: list[Entity]
    ...
```

**Two levels of shape.** The outer `app_shape` frames the whole app:
shell chrome, auth surface, brand identity, global nav. Every
`ArchetypeInstance` MAY declare a `local_shape` override that
changes any subset of primitives for that module's routes only.

Resolution rule: for a given route, effective shape =
`app_shape` merged with the owning `ArchetypeInstance.local_shape`
(instance wins on overlap). Downstream stages that render a
specific page read the **effective** shape via
`resolve_shape(plan, route) -> ShapeProfile`, not `plan.app_shape`
directly.

Concrete: Uber's `payment_methods` module declares `local_shape:
{layout.shell: null, layout.primaryInteraction: form}`. The `/pay`
route resolves to `{...outer..., layout.shell: null,
layout.primaryInteraction: form}` — a modal form over the map,
not the map surface itself. Ecommerce's `checkout_wizard` declares
`local_shape: {layout.hero: none, layout.primaryInteraction: form,
nav.menu: none}` — the shell header shrinks or disappears during
checkout, matching every real checkout on the web.

**Why not per-page shapes?** Because most pages within a module
share the same shape (all 4 checkout steps are the same wizard,
all 6 payroll-run steps are the same wizard). Module is the
correct grain — small enough to capture real variation, large
enough to avoid an explosion of per-page overrides.

**All three axes are LLM-authored.** For `app_shape` specifically,
the LLM authors a **profile** (values for each primitive) rather than
picking a label. Same LLM call as today — one more structured output
field on the planner.

The planner's system prompt gains a section listing every primitive
and its value set, plus a handful of reference apps showing composed
profiles:

```
APP SHAPE — compose the profile below by picking a value for each
primitive. Base your choices on the brief's implied structure,
audience, and interaction. There is no fixed set of "kinds of app";
compose what fits.

Primitives (pick one value per field):
  layout.shell:               none | sidebar | header | three-pane | bottom-tabs | map-canvas
  layout.hero:                none | full-bleed-gradient | media-hero | metric-row | player-bar | map-canvas | feed-header | now-playing
  layout.primaryInteraction:  cta-button | capture | search | feed | player | map | chat | lesson | data-grid | card-grid | form
  layout.density:             spacious | comfortable | dense
  auth.surface:               none | modal | route | sso-only
  auth.gating:                none | on-action | on-load
  nav.menu:                   none | sidebar-links | header-links | bottom-tabs | drawer | command-palette
  nav.back:                   history | crumb | close-modal | none
  workflows.executionMode:    fire-and-forget | await-with-progress | streaming | background-with-notification
  data.readShape:             single-record | list | feed | grid | map-pins | board | timeline
  data.denormalization:       none | moderate | aggressive
  identity.usageMode:         single-session | returning-personal | multi-user-team | public-anonymous

Each archetype instance uses EITHER a `recipe` (a known pattern
from recipes.json — pipeline knows the full stack) OR
`capabilities` (LLM composed from primitives when no recipe fits).
Both are valid; prefer a recipe when one matches. You MAY set both
to use a recipe as a starting point and locally override.

Reference apps — small (one module):
  Snap2App → shell:none, hero:full-bleed-gradient, primaryInteraction:
    capture, auth:modal-on-action, workflows:fire-and-forget,
    data.readShape:list, identity:single-session.
    archetypes: [{name:"scan", recipe:"visual_product_search"}]
  Spotify → shell:sidebar, hero:player-bar, ...
    archetypes: [{name:"library", recipe:"catalog"},
                 {name:"now_playing", recipe:"player"}]
  A tip calculator → shell:none, hero:none, primaryInteraction:form,
    ...
    archetypes: [{name:"calc",
                  capabilities:{read:{pattern:"single-record"},
                                write:{pattern:"create-form"},
                                interactions:[],
                                presentation:{itemShape:"row"},
                                state:{realtime:"none"}}}]

Reference apps — large (many modules, mix of recipes + compositions
+ local shape overrides):
  Uber rider →
    archetypes: [
      {name:"ride_request", recipe:"wizard",
        local_shape:{primaryInteraction:"form", nav.menu:"none"}},
      {name:"active_ride",
        capabilities:{read:{pattern:"map-pins"}, write:{pattern:"none"},
                      interactions:["live-follow","pinch-zoom"],
                      presentation:{itemShape:"pin"},
                      state:{realtime:"stream"}}},
      {name:"ride_history",
        capabilities:{read:{pattern:"list", grouping:"date"},
                      write:{pattern:"none"},
                      interactions:["filter","sort"],
                      presentation:{itemShape:"row"},
                      state:{realtime:"none"}},
        local_shape:{shell:"header", primaryInteraction:"data-grid"}},
      {name:"payment_methods", recipe:"crud",
        local_shape:{shell:"header", primaryInteraction:"form"}},
      {name:"chat", recipe:"chat",
        local_shape:{shell:"three-pane"}}
    ]
  Workday / HCM →
    archetypes: [
      {name:"employee_directory", recipe:"directory"},
      {name:"org_chart",
        capabilities:{read:{pattern:"tree", grouping:"hierarchy"},
                      write:{pattern:"drag"},
                      interactions:["pinch-zoom","drag-reorder"],
                      presentation:{itemShape:"node"},
                      state:{realtime:"none"}},
        local_shape:{primaryInteraction:"map"}},
      {name:"time_off", recipe:"approval_queue",
        local_shape:{data.readShape:"board"}},
      {name:"payroll_run", recipe:"wizard",
        local_shape:{nav.menu:"none"}},
      {name:"performance_review", recipe:"wizard"},
      {name:"benefits_enrollment", recipe:"wizard"},
      {name:"recruiting_pipeline",
        capabilities:{read:{pattern:"board", grouping:"status"},
                      write:{pattern:"drag", integrity:"audit-logged"},
                      interactions:["drag-between-groups","bulk-select","filter"],
                      presentation:{itemShape:"card"},
                      state:{realtime:"poll"}}}
    ]
  Shopify storefront →
    archetypes: [
      {name:"catalog", recipe:"catalog"},
      {name:"product_detail", recipe:"crud"},
      {name:"cart", recipe:"cart"},
      {name:"checkout", recipe:"checkout",
        local_shape:{hero:"none", primaryInteraction:"form",
                     nav.menu:"none"}},
      {name:"orders", recipe:"crud"},
      {name:"account", recipe:"crud"}
    ]
  Robinhood →
    archetypes: [
      {name:"portfolio", recipe:"dashboard"},
      {name:"watchlist",
        capabilities:{read:{pattern:"feed"}, write:{pattern:"inline"},
                      interactions:["live-follow","sort"],
                      presentation:{itemShape:"row"},
                      state:{realtime:"stream"}}},
      {name:"chart", recipe:"chart_analysis"},
      {name:"order", recipe:"wizard",
        local_shape:{shell:"none", primaryInteraction:"form"}},
      {name:"news", recipe:"feed"}
    ]

You MAY add a short human-readable label — for humans only; the
pipeline reads only primitives (capabilities and shape) plus the
recipe name when set.

COVERAGE VERDICT — before authoring the four axes, honestly
assess whether the brief fits Forge's substrate.

  `in_scope`         — the brief composes from the four axes'
                       primitives (with or without a matching
                       reference app / recipe). Almost always.
  `extension_needed` — the brief is close but one dimension is
                       missing (e.g. deployment target, real-time
                       collaboration model, tenancy shape). Author
                       the nearest supported composition AND list
                       what would need to be added in
                       `suggested_extensions`.
  `out_of_scope`     — the brief asks for something structurally
                       outside Forge: games, creative authoring
                       (Photoshop / Ableton / video editors /
                       IDEs / DAWs), spatial / AR / VR / voice-
                       only, embedded firmware, browsers,
                       emulators. **Do not fabricate an app**.
                       Emit `status: out_of_scope` with a clear
                       `reason` and `nearest_supported` — the
                       pipeline will surface a refusal card to
                       the user.

Emit `coverage_verdict` as part of the same structured output as
the four axes. Never quietly settle for a poor fit; a truthful
`out_of_scope` verdict is more useful than a broken app.

RUNTIME CONTEXT — pick every platform capability this app needs
at runtime (multi-select from the vocabulary). None-of-these =
empty list. Do NOT pick capabilities the app doesn't actually
use; each one triggers permission prompts and native module
weight.

Reference: runtime_context for the apps above —
  Snap2App:  [camera]
  Spotify:   [background_tasks, offline_sync, push_notifications, wallet_pass]
  Instagram: [camera, photo_library, push_notifications, contacts, deep_linking]
  Uber:      [geo, push_notifications, background_tasks, biometric_auth, wallet_pass]
  Workday:   [push_notifications, biometric_auth, offline_sync]
  Shopify:   [push_notifications, wallet_pass, biometric_auth]
  Robinhood: [push_notifications, biometric_auth, wallet_pass, background_tasks]
  Gusto:     [push_notifications, biometric_auth]
  Swiggy:    [geo, push_notifications, contacts, deep_linking, wallet_pass]
  Tip calc:  []
```

Deterministic follow-ups run on the emitted profile (**not** to
author it, but to catch obvious problems):

- **Value validator** — every primitive's value must be in its
  closed set. If the LLM emits something outside, fall back to
  `shape_profile_detector.py` (a lightweight heuristic scorer, same
  pattern as `archetype_detector.py`) for that one field, keeping
  the LLM's other choices intact.
- **Coherence check** — some combos are suspicious:
  `layout.shell: none` + `nav.menu: sidebar-links` (no shell to hold
  the menu), `identity.usageMode: single-session` + `auth.gating:
  on-load` (asking anonymous users to log in before they see
  anything), `workflows.executionMode: fire-and-forget` +
  `data.readShape: single-record` (writing without reading back what
  we wrote). Not forbidden — surfaced as a `plan_completeness`
  finding, planner REVISE loop gets one chance to reconcile. If the
  LLM stands its ground with a stated reason, we trust it.

Fallback ladder (identical shape to `archetype_classifier`):

```
LLM emits profile → validate every field against value set → done
LLM emits invalid value for a field → shape_profile_detector fills
                                     that field only → done
API key missing / LLM raised → shape_profile_detector fills whole
                              profile (safe conservative defaults)
```

Safe conservative defaults, when the detector has no signal at all:
`shell: sidebar, hero: none, primaryInteraction: data-grid, auth:
route-on-load, nav: sidebar-links, workflows: await-with-progress,
data.readShape: list, identity: multi-user-team`. This matches
today's default output shape — so a missing-API-key fallback still
generates a working (if unadventurous) app.

All three axes are user-overridable at generation start (via the
planned override UI) and via a `plan.overrides` block in the brief.
User overrides win over LLM output; LLM output wins over
detector. Overrides can be partial (`overrides.app_shape.layout.
shell: none` overrides just that field, leaves the rest of the
LLM-authored profile).

### The profile IS the composition

There is **no per-shape JSON file**. The `ShapeProfile` the planner
emits IS the app's profile; it lives on `plan.json` alongside the
rest of the plan. Every consumer reads the primitives directly.

What we ship for shape + archetype is not a catalog of apps —
it's **vocabulary + recipe metadata**, all JSON, all growable
without a code change:

```
backend/shapes/
  vocabulary.json          # closed value set for each shape primitive
                           # (single source of truth; planner prompt
                           # renders from this, validator reads from
                           # this, code enums generated from this)
  reference_apps.json      # reference apps shown in the planner
                           # prompt (Spotify, Snap2App, Uber, Workday,
                           # tip calc, …). Grow to teach the planner
                           # new kinds of apps.

backend/archetypes/
  capability_vocabulary.json # closed value set for each capability
                             # primitive (read.pattern, write.pattern,
                             # interactions, presentation, state).
  recipes.json               # named recipes — each declares its
                             # capabilities + workflow template +
                             # component set + signature moves. Grow
                             # to add a new nameable pattern.
  signature_moves.json       # signature moves KEYED BY capability
                             # primitive value, not by recipe name.
                             # `interactions: [drag-between-groups]`
                             # → lane-swap animation. `read.pattern:
                             # map-pins` → pin-cluster treatment.
                             # `write.pattern: capture` → pulsing
                             # scan orb. Recipes MAY declare
                             # additional recipe-specific signatures.

backend/runtime/
  context_vocabulary.json    # closed value set for runtime_context
                             # (geo, camera, push_notifications, …).
  context_bundles/           # one folder per capability. Each holds
                             # the permission strings, native imports,
                             # provider template, and integration
                             # requirements the wire-pass emits when
                             # that capability is declared. Add a new
                             # runtime capability = new folder +
                             # append to context_vocabulary.json.

backend/telemetry/
  substrate_gap_log.jsonl    # append-only log of `extension_needed`
                             # verdicts. One JSON entry per gen where
                             # the planner marked the brief as
                             # "close but missing a dimension." Team
                             # reviews weekly; any gap appearing in
                             # ≥3 briefs across ≥2 weeks graduates to
                             # a vocabulary edit. Evidence, not
                             # speculation.
```

Six files/folders, all data. Adding a new app kind =
`reference_apps.json` edit. Adding a new named recipe =
`recipes.json` edit. Adding a new signature move =
`signature_moves.json` edit. Adding a new runtime capability =
new `context_bundles/<name>/` folder. Only the closed
vocabularies (`vocabulary.json`, `capability_vocabulary.json`,
`context_vocabulary.json`) map to code enums — because they're
what validators and derived functions branch on.

**Derived properties.** Some questions downstream stages ask
(e.g. "does this app get a `<Toaster />` at root?") depend on
multiple primitives. Those live as **pure functions** over the
profile, not fields on the profile:

```python
# services/shape_profile_derived.py

def needs_root_toaster(profile: ShapeProfile) -> bool:
    """Toaster mounted at app-root when any surface bypasses the shell."""
    return (
        profile.layout.shell == "none"
        or profile.auth.surface == "modal"
        or profile.workflows.executionMode == "fire-and-forget"
    )

def form_submit_pattern(profile: ShapeProfile) -> str:
    """How submit buttons behave visually + interaction-wise."""
    if profile.workflows.executionMode == "fire-and-forget":
        return "fire-and-forget-with-toast-nav"
    if profile.workflows.executionMode == "streaming":
        return "in-place-progress"
    return "await-with-spinner"

def should_generate_login_route(profile: ShapeProfile) -> bool:
    return profile.auth.surface == "route"
```

Derived functions are the ONLY place logic like "no shell + modal
auth → root Toaster" lives. No `if app_shape == "consumer-utility"`
anywhere. New primitive → new derivation → downstream stage reads
the derived value.

**Per-route resolution** (multi-module apps):

```python
# services/shape_profile_derived.py

def resolve_shape(plan: Plan, route: str) -> ShapeProfile:
    """Effective shape for a specific route = outer app_shape merged
    with the owning ArchetypeInstance's local_shape override."""
    owner = _find_owning_module(plan.archetypes, route)
    if owner is None or owner.local_shape is None:
        return plan.app_shape
    return _merge(plan.app_shape, owner.local_shape)
```

Every page-level derived function (`needs_root_toaster`,
`form_submit_pattern`, `should_generate_login_route`) accepts a
`ShapeProfile` — callers pass `resolve_shape(plan, route)` for the
current page, or `plan.app_shape` for app-global concerns like the
root layout's shell wrapper. Uber's `/pay` route resolves to a
form-mode profile → `form_submit_pattern` returns
`await-with-spinner`; Uber's `/` route resolves to the map-canvas
profile → different treatment. Same code path, different input.

### Downstream integration (the priority order)

Every consumer of the axes follows a **fixed priority**:
`app_shape` > `archetype` > `industry`. In practice: `app_shape`
decides topology (shell / auth / navigation), `archetype` decides
capability-specific layout (kanban lanes, dashboard rows), `industry`
decides semantic dressing (palette, terminology, iconography).

This ordering matters because it prevents the today-failure of
`archetype: crud` forcing a shell on a `app_shape:
consumer-utility` app. `app_shape` wins.

Full integration table (each row is a code change). Every
**app-global** stage reads `plan.app_shape`; every **per-page** or
**per-route** stage reads `resolve_shape(plan, route)`. Never a
shape label:

| Stage | Scope | Reads | Behavior |
|---|---|---|---|
| `coverage_verdict_gate` (NEW) | app | `plan.coverage_verdict` | **runs first, before any generation stage.** `in_scope` → proceed. `extension_needed` → proceed + append to `substrate_gap_log.jsonl`. `out_of_scope` → halt pipeline, emit `OutOfScopeCard` payload for frontend, no generation performed. |
| `root_layout_template` | app | `plan.app_shape` + `needs_root_toaster(app_shape)` | mounts `<Toaster />` when derivation says so; wraps in root shell |
| `select_frame` (SP4-2) | app | `plan.app_shape.layout.shell` | switches on `none` / `sidebar` / `header` / `three-pane` / `bottom-tabs` / `map-canvas` |
| `derive_actor_onboarding` | app | `plan.app_shape.auth` | derived function decides route vs. modal vs. none |
| `shell_menu_sync` | app | `plan.app_shape.nav.menu` + `plan.archetypes` | synthesizes menu with one entry per module (skipped if menu:none) |
| `page_schema_agent` | per-page | `resolve_shape(plan, route)` + owning `ArchetypeInstance` + `industry` | authors the page coherent with the module's effective shape (so Uber's `/pay` gets form-shaped output, not map) |
| `build_form_page` | per-page | `form_submit_pattern(resolve_shape(plan, route))` + owning archetype | submit pattern from effective shape; field layout from archetype |
| `translate_workflow` | per-workflow | `resolve_shape(plan, workflow.owning_route).workflows.executionMode` | switches on the four modes; a fire-and-forget checkout workflow differs from a streaming ride workflow in the same app |
| `schema_builder` | app | `plan.app_shape.data.denormalization` | `aggressive` → emit `*Name` denorm columns per FK; single decision app-wide |
| `design_agent` | app | `plan.app_shape.layout.hero` + `layout.density` + `industry` | picks the app-wide aesthetic profile |
| `signature_moves_guard` | per-archetype-instance | `plan.archetypes` | injects the archetype's signature moves into each module's pages (checkout gets checkout signatures, kanban gets kanban signatures — same app) |
| `post_generate_fixes` | per-page | `needs_root_toaster`, `form_submit_pattern`, … over `resolve_shape` | derived functions decide which guards run on which pages |
| `runtime_context_wire` (NEW) | app | `plan.runtime_context` | for each capability, emits: permission block in `app.json`/`Info.plist`/`AndroidManifest.xml`, native module import, provider/hook wiring (e.g. `<GeoProvider>` + `useGeo()`), env vars, and setup docs. Idempotent post-gen pass. |
| `mobile_scaffolding` (existing MOBILE-A) | app | `plan.runtime_context` | Expo config extras (permissions, plugins) driven by declared capabilities instead of guessed |
| `platform_integrations` (existing INT-*) | app | `plan.runtime_context` | providers that require server-side keys (FCM/APNs for `push_notifications`, geocoding key for `geo`) auto-appear in `/settings/integrations` for the user to configure |
| `page_schema_agent` | per-page | `plan.runtime_context` + `resolve_shape(plan, route)` | knows what capabilities exist app-wide so it can author, e.g., a "use current location" button on an addresses form when `geo` is declared |

Each row lands as its own PR with **five** canonical-app snapshot
tests spanning distinct profiles: (1) hero-CTA utility like Snap2App,
(2) sidebar workspace like Linear, (3) bottom-tabs feed like
Instagram, (4) map-canvas booking like Uber, (5) player-shell like
Spotify. Snapshot regression on any of the five blocks the merge.
No runtime toggle, no `intelligent-mode` alongside `legacy-mode`:
the pipeline **is** the new pipeline after each PR merges. If a bad
merge escapes review, we revert the commit — same as any other
platform change.

### Rename discipline

`domain` → `industry` is mechanical:

1. Freeze the term in the spec (this doc).
2. Codemod: `python -m services.tools.rename_domain_industry` — sed
   over ~20 Python files + JSON keys.
3. Snapshot tests on 3 fresh generations (consumer-utility,
   internal-workspace, analytics-console) show byte-identical output
   modulo the rename.
4. Ship in a single commit. No parallel-naming period.

`archetype` stays. `app_shape` is new.

---

## P2 — Uniform intelligence loop

### The loop

Every mutation — pipeline stage output, Smith tool call — passes
through the same five phases:

```
context → plan → act → verify → recover?
   ↑                              │
   └──── (on recover: re-plan) ───┘
```

Each phase has a shared implementation both pipeline and Smith call.

### Phase 1: context

**Shared substrate**: `SessionContext` (new). One Python object with
five fields:

```python
class SessionContext(BaseModel):
    plan: Plan                    # app_shape + archetype + industry + entities
    shape_profile: dict           # loaded from backend/shapes/{shape}.json
    industry_profile: dict        # loaded from backend/industries/{industry}.json
    archetype_profile: dict       # loaded from backend/archetypes/{archetype}.json
    registry: ResourceRegistry    # canonical naming authority
    app_map: dict                 # for Smith, current file structure
    verify_history: list[dict]    # last N verify runs
    edit_history: list[dict]      # last N mutations
```

Every generation stage receives this. Every Smith tool invocation
receives this. No stage or tool derives `industry` from `brief.text`
or `shape` from filesystem shape — the context is authoritative.

`smith_memory` (existing) becomes a **view** onto `SessionContext`,
not an independent memory.

### Phase 2: plan

**Existing**: `plan_and_apply` in Smith.
**New**: `Stage.plan(context) → StagePlan` interface on every
generation stage. A `StagePlan` is `{intent, files_to_touch,
files_to_read, expected_bindings, expected_workflows}`. Deterministic
where possible (e.g., `schema_builder.plan()` = "given this
entities list, emit these 3 schema files"). LLM-authored where
necessary (`page_schema_agent.plan()` = "given this brief + shape,
propose these page schemas").

**Why**: the pre-mutation plan is what verify checks against. Without
a plan, verify can only check "does it type-check?" — not "does it
match intent?"

### Phase 3: act

Existing — no change. Whatever the stage or tool already does.

### Phase 4: verify

**New**: `verify(context, plan, act_output) → VerifyReport`. Runs
after every stage output and every Smith turn.

Verify is a **stack of checks**, ordered cheapest → most expensive:

1. **Static** — type check, JSON schema validate. ~1s.
2. **Structural** — resource registry cross-refs, `_check_bindings`,
   `_check_workflows`. ~2s.
3. **Domain conformance** — did this output honor the shape profile?
   (E.g., consumer-utility page must not include `<Sidebar>`.) ~1s.
4. **Design conformance** — did this output honor the aesthetic
   profile? (Design critic in enforcement mode.) ~15s, LLM-based,
   optional per stage.
5. **Runtime** — dev server compile check, dry-run render. ~30s,
   optional per stage.

Each stage declares which checks it needs; cheap ones always run,
expensive ones opt-in. Every `VerifyReport` goes into
`context.verify_history`.

### Phase 5: recover

**Existing**: DUR-2 retry-break, `vf-self-healing`.
**New**: unified ladder every stage/tool implements the same way:

```
attempt_1: LLM-authored change
    → verify fails: attempt 2
attempt_2: LLM-authored change + verify findings in prompt (DUR-1)
    → verify fails: attempt 3
attempt_3: fall back to deterministic template
    → verify fails: escalate
escalate:
    - pipeline: surface as post_generate_fixes finding, human sees at end
    - smith:    surface to user with structured "here's what I tried"
```

Cap at 3 attempts. Cost: bounded. No infinite loops.

The recover ladder makes **workflows also recoverable**: engine-level
`continueOnError: true` on nodes means one failing `extract_N`
doesn't kill `mark_completed`. This fixes the AC10-copy class of
"scan stays pending forever."

### Interaction with existing systems

- `plan.py` → owns the `Plan`, feeds `SessionContext`.
- `smith_memory` → becomes a `SessionContext` view.
- `self_verify_pass` → becomes the runtime-check layer of phase 4,
  running per-stage instead of only at end.
- `vf-self-healing` → becomes the `escalate` action of phase 5.
- `plan_and_apply` → becomes phase 2 for Smith.

Nothing gets thrown away; everything gets a place in the loop.

---

## P3 — Rich by construction

### The three richness layers

Layered so cheap wins land first; expensive wins only when needed.

**Layer 1: aesthetic profiles (deterministic surface treatments)**

Six profiles matching real design systems:

| Profile | Character |
|---|---|
| `glass-dark` | radial gradient bg, glass cards, gradient-glow CTAs |
| `carbon` | sharp corners, dense grids, IBM-Carbon-adjacent |
| `polaris` | soft shadows, generous padding, Shopify-adjacent |
| `material-3` | tonal surfaces, filled cards, motion accents |
| `fluent-2` | acrylic surfaces, reveal-highlight, MS-Fluent-adjacent |
| `clean-editorial` | serif display, generous whitespace, letterpress-adjacent |

Each profile ships as:

- A JSON `design-spec.json` fragment (tokens: color, type, radius,
  shadow, spacing) that merges into the generated app's design spec.
- A set of library component variants (`Button.glass`,
  `Card.carbon`, `Input.polaris`) already in the component library.
- A named surface-treatment recipe applied post-gen (see Layer 3).

**Profile selection is a derived function**, not a lookup keyed on a
shape label:

```python
# services/aesthetic_profile_picker.py

def pick_aesthetic_profile(profile: ShapeProfile, industry: str,
                           user_override: str | None) -> str:
    if user_override:
        return user_override
    # heuristic — reads primitives, never a shape label
    if profile.layout.hero == "full-bleed-gradient" and profile.identity.usageMode == "single-session":
        return "glass-dark"                # hero-CTA consumer utility
    if profile.layout.hero == "media-hero" and industry in ("consumer-retail", "hospitality"):
        return "polaris"                   # marketplace-ish
    if profile.layout.density == "dense" and profile.identity.usageMode == "multi-user-team":
        return "carbon"                    # workspace
    if profile.layout.hero == "metric-row":
        return "material-3"                # analytics
    if profile.layout.shell == "three-pane":
        return "fluent-2"                  # comms
    if profile.layout.shell == "none" and profile.data.readShape == "single-record":
        return "clean-editorial"           # marketing / landing / docs
    return "carbon"                        # safe default
```

Same six profiles, but the picker composes over primitives, so
Snap2App (hero + single-session) and Duolingo (lesson + returning-
personal) can land on different profiles even though a label-based
system would have called both "consumer-utility."

**Layer 2: signature moves keyed by capability primitives**

Every signature is a **library component + schema template**
(`SignatureMoves.PulsingScanOrb`, `SignatureMoves.KanbanLaneSwap`)
and **attaches to a capability-primitive value** — not to an
archetype name. This way a novel LLM-composed module still gets
the right signatures, and any recipe that resolves to the same
primitive gets them too.

| Trigger | Signature move |
|---|---|
| `interactions` contains `drag-between-groups` | lane columns w/ drop-zone glow, card lift-on-drag, lane-swap animation |
| `interactions` contains `drag-reorder` | grip handle affordance, drag-shadow, drop-line indicator |
| `read.pattern` = `map-pins` | pin cluster w/ count badge, hover-tooltip, cluster-zoom-in |
| `read.pattern` = `timeline` | continuous axis, endpoint emphasis, hover-scrub |
| `read.pattern` = `chart` | sparkline preview, axis-hover crosshair, zoom-brush |
| `read.pattern` = `board` | column headers w/ counts, add-card ghost, WIP-limit hint |
| `write.pattern` = `capture` | pulsing scan orb, viewfinder frame, capture-flash |
| `write.pattern` = `wizard` | step progress bar, per-step summary card, back/continue rail |
| `state.realtime` = `stream` | live-dot indicator, ambient tick animation |
| `presentation.itemShape` = `card` + `read.pattern` = `grid` | image-lead card, hover-lift, quick-actions overlay |

Recipes MAY add recipe-specific signatures on top of what the
primitives yield (`recipe: checkout` adds an order-summary sticky
sidebar). Never subtract — primitive-triggered signatures always
apply first, so a "custom recipe with drag-between-groups" still
gets the lane-swap animation.

For every `ArchetypeInstance` in `plan.archetypes`, the
`page_schema_agent` MUST include the primitive-triggered
signatures on its owning routes; `signature_moves_guard`
(post-gen) walks the plan, computes expected signatures from
each instance's resolved capabilities, and verifies presence.
Workday's kanban module (composed capabilities) and Workday's
directory module (recipe) both get their own signatures on their
own routes — same app, different signature sets side-by-side,
same triggering mechanism.

**Layer 3: deterministic surface treatment pass**

New: `backend/services/surface_treatment_pass.py`. Post-gen
deterministic pass that walks every schema and applies the
aesthetic profile's recipe:

```python
def apply_surface_treatment(schema, profile):
    for page in schema.pages:
        # 1. Root Stack on hero pages → gradient background
        if page.kind == "hero" and page.root.type == "Stack":
            page.root.style.background = profile.gradient.hero
        # 2. Container acting as card → variant from profile
        for node in walk(page.root):
            if node.type == "Container" and node.role == "card":
                node.variant = profile.card_variant
            if node.type == "Button" and node.role == "primary":
                node.variant = profile.button_variant
        # 3. Loading elements → aesthetic-appropriate animation
        for node in walk(page.root):
            if node.type == "Loader":
                node.animation = profile.loader_animation
```

Zero LLM, zero tokens. Transforms every page in ~50ms. Runs as a
post-gen guard.

### Design critic in enforcement mode

Existing: design critic runs in shadow mode (findings logged, not
applied). Change: when the effective shape has `identity.usageMode
in (single-session, public-anonymous)` OR `layout.hero != none` —
i.e. surfaces where visual polish is directly visible to end users
— critic runs in **enforcement mode**: findings above severity
threshold trigger a REVISE loop (up to 2 revisions before falling
to layer-3 deterministic fix). Multi-module apps run the critic
per module, so Shopify's marketing catalog gets enforcement while
its admin dashboard runs warn-only.

Rubric (from AC10-copy analysis):

- Palette diversity ≥ 4 non-neutral colors used
- Class diversity vs. default shadcn baseline ≥ 40%
- Signature moves for the archetype present ≥ 80%
- Shape topology conformance = 100% (hard)
- Aesthetic profile conformance ≥ 75%

Score < 75 = REVISE. Score < 50 = escalate to user with structured
"here's the gap" report.

### Form-quality subsystem

Ten form patterns catalogued (single-column-progressive, wizard-3-
step, checkout-express, settings-tabbed, filter-drawer,
onboarding-carousel, inline-editable-grid, modal-quick-add,
master-detail-edit, multi-step-approval). Each pattern = schema
template + validation stances + submit behavior.

Thirty NN/g form UX invariants enforced as `form_ux_invariants.py`
post-gen pass:

- Required marker on every required field.
- Blur-time validation on every field.
- Submit disabled while in-flight.
- Error text describes the fix, not the failure.
- Numeric inputs use `inputMode="numeric"`.
- (…full list in appendix.)

All 30 checked deterministically; violations auto-fixed where
mechanical, surfaced as findings where they require intent.

### Interpolator formatters

Feel-lite gains three built-in formatters, cures the "0.87%" class
of AC10-copy bug:

- `{{item.confidenceScore | percent}}` → `87%`
- `{{item.price | currency:USD}}` → `$1,299.00`
- `{{item.createdAt | relative}}` → `2 hours ago`

Deterministic; zero LLM. Renderer changes only.

---

## What this spec is not

- **Not a plan.** The implementation plan lives at
  `docs/superpowers/plans/2026-08-11-intelligent-rich-forge.md`
  (next document). This spec defines *what* and *why*; the plan
  defines *when* and *who*.
- **Not a rewrite.** Every existing subsystem (planner,
  design_agent, self_verify_pass, Smith tools) keeps its identity;
  this spec reconciles them under one substrate.
- **Not a research project.** All three P's are directly
  implementable from the current codebase; no new ML, no new
  frameworks, no new infra.

## Non-goals

- **No changes to A/B/C/D/E scope.** They land on top of this
  substrate; they don't get rescoped.
- **No new closed enum growing forever.** `app_shape` is
  primitives + composition, not labels. `archetypes` is primitives
  + recipes, not a fixed list. `industry` remains an open string
  with a suggested set. Any "new kind of app" is a JSON edit
  (reference apps, recipes, signatures) — never a new axis and
  never a new code branch.
- **No user-visible taxonomy in the app itself.** These axes are
  internal generation controls. End users of a generated app never
  see the word "shape" or "archetype."
- **No CRDT / multiplayer / real-time in the substrate.** Those
  belong to spec E's advanced-UX wave.
- **No spec-level commitment to Figma reference library.** That is
  spec A's territory; this spec makes room for it (industry
  profiles can point at a reference file) but doesn't require it.

## Success criteria

Substrate is done when all four hold on **seven** canonical fresh
generations covering the small / large × single-module / multi-module
matrix:

- **Small, single-module** (baseline): Snap2App-style capture
  utility; tip calculator.
- **Small, multi-module**: Instagram-style feed + capture app.
- **Large, workspace**: Linear-style workspace; Workday-style HCM
  (8+ modules, sidebar shell, mixed archetypes).
- **Large, consumer**: Uber-style rider (map-canvas shell with
  form + list overrides); Shopify-style storefront (header shell
  with checkout wizard override); Swiggy-style delivery (bottom-
  tabs shell + `geo`+`push_notifications` runtime context + map
  override for order tracking).

For every one:

1. **Zero manual patches** to reach the same usability as AC10 copy
   (small apps) or the same module coverage as the reference
   product (large apps — measured by module count + per-module
   route completeness).
2. **Every stage** in the pipeline logs a `SessionContext` snapshot
   and a `VerifyReport`; `resolve_shape(plan, route)` is exercised
   on multi-module apps; `runtime_context_wire` is exercised on
   apps that declare any capabilities (permission blocks land in
   `app.json`/`Info.plist`, providers get wired at root layout).
3. **Every Smith turn** logs a plan → act → verify record; failures
   trigger the recover ladder without user intervention.
4. **Design critic score** ≥ 75 on every generation without
   hand-tuning; ≥ 85 with one round of REVISE. Multi-module apps
   are scored per-module and app-average.

Measured on the quality dashboard (spec E companion) weekly.

## Risks + how we catch them

The pipeline gets upgraded in place — no `intelligent-mode` toggle,
no parallel legacy pipeline to maintain. Each PR is the change; if
something regresses, we revert the commit. That means every risk
below is guarded by **pre-merge snapshot tests**, not a runtime
escape hatch.

| Risk | How we catch it before merge |
|---|---|
| `industry` rename breaks a hidden call site | Codemod in one commit; full `pytest` sweep + snapshot regen on 3 canonical apps. A regression is a red CI. |
| Compositional profile too permissive — LLM invents nonsense combos | Every primitive is validated against a closed value set (12 fields × ~5 values ≈ 60 tokens the LLM can emit; anything else falls to the detector for just that field). Cross-field coherence check catches nonsense combos and REVISE-loops once. |
| New primitive value needed for a real app | Add the value to `backend/shapes/vocabulary.json` — one JSON edit. Planner prompt renders from the same file, validator reads from the same file. No new bucket, no downstream branch. |
| Combinatorial space is too big — planner picks inconsistently | Reference apps in the planner prompt anchor the composition; adding more entries to `reference_apps.json` teaches the planner a new shape at zero code cost. |
| Verify loop makes every stage 2× slower | Cheap verify (~5s) always runs; expensive verify (design critic, runtime render) opt-in per stage. Total gen-time budget capped at +30s baseline; CI enforces it. |
| Recover ladder makes Smith too talkative | Cap at 3 attempts; "I tried A, then B…" narration off by default; exposed only via `explain_last_recovery` tool when user asks. |
| Aesthetic profiles look same-y across apps | `industry × shape` picks the profile; industry biases palette and iconography. Design-critic rubric scores palette diversity — CI blocks a snapshot that shows the same look across 3 different industry samples. |
| Enforcement critic blocks a legitimate design | Two tiers: strict for `consumer-utility` / `marketing-site`, warn-only for others. Escalation surfaces the gap; user can accept as-is via a single-turn override in Smith. |
| A merged PR still slips through and breaks live gens | Each PR is atomic. Revert the commit, snapshot suite goes green, we investigate. No production data is destroyed by a bad generation — it lives in `output/<slug>/`, throw-away. |

Existing already-generated apps (in `output/`) are untouched by any
of these merges — the pipeline generates *new* apps against the
new substrate. If a user asks Smith to edit an old app,
`SessionContext` reads whatever `plan.json` the app was generated
against; if that plan lacks `app_shape`, Smith computes it lazily
from the same LLM call and writes it back. No forced migration.

## Companion documents to write after this

- `docs/superpowers/plans/2026-08-11-intelligent-rich-forge.md` —
  the implementation plan (milestones, staffing, timeline).
- `docs/superpowers/patterns/app-shape-shape-profile.md` — the
  authoring guide for adding a new shape.
- `docs/superpowers/patterns/aesthetic-profile.md` — the authoring
  guide for adding a new profile.
- `docs/superpowers/patterns/signature-move.md` — the authoring
  guide for adding a new archetype signature.

None of the four is a prerequisite for starting P1; all four ship
alongside their subsystem.
