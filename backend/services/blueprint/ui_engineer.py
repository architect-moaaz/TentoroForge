"""The UI engineer — pages written as React, checked by the compiler.

Two agents:

* ``ui_director`` — one call for the whole application, before any page. It
  decides what the product should feel like and the conventions every page
  follows (header rhythm, where filters and the primary action live, how
  empty and error states read, density). Writes `composition.vision` and
  `composition.conventions`.
* ``ui_engineer`` — one call per page. It writes the page as two modules,
  `load.ts` (server: what the page shows, read through the typed SDK) and
  `view.tsx` (client: the screen, from the app's UI kit and the component
  library). Writes `pageCode`.

WHAT IT MAY SAY IS WHAT THE APPLICATION HAS. The SDK (`app_sdk`) types every
entity, workflow input and page route from the Blueprint, and each page is
type-checked against it before it is accepted: a field the entity lacks, a
form that leaves a workflow input out, a link to a route that does not exist,
a component prop that is not there — each is a compiler error, returned to
the author verbatim to fix. The compiler runs here, in the author's own
worker, so pages are checked in parallel and never queue behind the writer.

A page whose code never compiles keeps its `pageLayouts` tree — every page
has one — so a refused page is plainer, never missing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from services.blueprint.app_sdk import (
    code_page_files, project_app_sdk, sdk_reference,
)

logger = logging.getLogger(__name__)

#: How many times one call's code goes back to its author with the compiler's
#: errors before the call gives up (and the node's own retry takes over).
COMPILE_ROUNDS = 3

#: The kit a view composes from, relative to the backend. Read, not listed, so
#: the prompt names exactly what the scaffold ships.
_UI_KIT = Path(__file__).resolve().parents[2] / "templates/app-foundation/src/components/ui"
_SDK_TEMPLATE = Path(__file__).resolve().parents[2] / "templates/app-foundation/src/sdk"

PAGE_CODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rationale", "load", "view"],
    "properties": {
        "rationale": {"type": "string",
                      "description": "Two or three sentences: the layout you chose and why, for this page's users."},
        "load": {"type": "string", "description": "The full contents of load.ts."},
        "view": {"type": "string", "description": "The full contents of view.tsx."},
    },
}

DIRECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vision", "conventions"],
    "properties": {
        "vision": {"type": "string"},
        "conventions": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False,
                      "required": ["topic", "rule"],
                      "properties": {"topic": {"type": "string"}, "rule": {"type": "string"}}},
        },
    },
}


# ---------------------------------------------------------------------------
# What the engineer is told
# ---------------------------------------------------------------------------

def _kit_exports() -> str:
    lines = []
    for f in sorted(_UI_KIT.glob("*.tsx")):
        src = f.read_text()
        names: list[str] = []
        for block in re.findall(r"export\s*\{([^}]+)\}", src):
            names += [n.strip() for n in block.split(",") if n.strip() and "Variants" not in n]
        if names:
            lines.append(f'  import {{ {", ".join(names)} }} from "@/components/ui/{f.stem}";')
    return "\n".join(lines)


SDK_GUIDE = """\
// ---- @/sdk/server — load.ts only. Every read runs as the signed-in user. ----
interface PageContext { params: Record<string, string>; searchParams: Record<string, string | undefined>; user: SessionUser | null }
interface SessionUser { id: string; name: string | null; email: string | null; role: string | null }
type Where<E> = Partial<{ [field of E]: string | number | boolean }>          // equality filters
interface ListOptions<E> { where?: Where<E>; search?: string; sort?: field of E; order?: "asc" | "desc"; limit?: number /* ≤200, default 50 */; page?: number }
interface Page<T> { rows: T[]; total: number; page: number; limit: number }
interface SeriesPoint { label: string; value: number }

currentUser(): Promise<SessionUser | null>
list(entity, opts?: ListOptions): Promise<Row[]>
listPage(entity, opts?: ListOptions): Promise<Page<Row>>
record(entity, id: string | undefined): Promise<Row | null>
recordsById(entity, ids: (string | null | undefined)[]): Promise<Record<id, Row>>   // the rows foreign keys point at — show a related record by NAME
near(entity, locationField, from: GeoPoint | null, { where?, radiusKm?, limit? }?): Promise<(Row & { distanceKm: number | null })[]>   // closest first
whereAmI(ctx): Promise<GeoPoint | null>     // the reader: ?near= (set by <NearMe />), else their account's location
distanceKm(a, b): number | null;  formatDistance(km): string   // "0.4 mi" — also from "@/sdk/client"
count(entity, where?): Promise<number>
total(entity, fn: "sum" | "avg" | "min" | "max", numericField, where?): Promise<number>
series(entity, { groupBy: field; bucket?: "day" | "week" | "month"; fn?: "count" | "sum" | "avg" | "min" | "max"; field?: numericField }): Promise<SeriesPoint[]>
query(entity, { measures: { [key]: { fn: "count" } | { fn: "count_distinct" | "min" | "max", field } | { fn: "sum" | "avg", field: numericField } };
                dimensions?: [field | { field, bucket?: "day" | "week" | "month" | "quarter" | "year" }
                              | { field: numericField, ranges: { label?, from?, to? }[] }, …at most 2];
                where?; range?: { from?: iso; to?: iso }; timeField?; sort?: { by, order? }; limit? }): Promise<QueryRow[]>
   Measures by dimensions, one GROUP BY: query("Order", { measures: { revenue: { fn: "sum", field: "total" } },
   dimensions: [{ field: "placedAt", bucket: "month" }, "region"] }) → [{ placedAt: "2026-01", region: "EU", revenue: 1840 }, …].
   A bucketed date reads "2026-03-02" / "2026-03" / "2026-Q1" / "2026"; a foreign-key dimension also carries `<field>Label`.
   A number grouped into `ranges` (from ≤ value < to) reads as each band's label, bands in the order given — age groups,
   price bands; a value in no band is left out.
myAccount(): Promise<Row | null>
   The signed-in person's own record — the account entity's row, whose id IS their login's id
   (`$user.id` in a workflow). Null when signed out or when the application has no account entity.
runWidget(widgets.x, { range?, where? }): Promise<WidgetData>      // WidgetData = { rows: QueryRow[]; value: number | null }
   Reads one of the page's declared widgets exactly as the Blueprint defines it. `value` is the number of a
   metric or gauge. `where` narrows it (a record page passes its own id: { customerId: params.id }).
similar(entity, { image?: ctx.searchParams.image, text?: ctx.searchParams.q, limit? }): Promise<{ rows: (Row & { similarity })[]; error: string | null }>
   Only for an entity whose type says "Findable by likeness". Rows closest first to the picture (or the
   words — they share one space). No image and no text is no rows. `error` is set when the service that
   compares pictures is not connected: show it. Show the order, not `similarity` — it is relative.
   `entity` is the entity's name as a string literal: list("Case", …). Rows are typed (Entities["Case"]).
   Dates arrive as ISO strings, numbers as numbers, optional fields as null.

// ---- @/sdk/client — view.tsx ----
useWorkflow(workflows.x, { successMessage?, redirectTo?, silent? })
   → { run(input): Promise<{ ok: boolean; result: Record<string, unknown>; error: string | null }>, pending: boolean, error: string | null }
   On success the page's data refreshes (or it navigates to redirectTo) and a toast is shown.
   When the workflow's own rules refuse the input, `ok` is false and `error` is the workflow's
   sentence, shown as an error toast — `successMessage` is only ever shown for a real success.

<SignInForm submitLabel? className? />          // an `auth` login page: email, password, signs in, goes home
<SignUpForm submitLabel? className? columns?={1 | 2} />   // an `auth` signup page: the person's details + login,
   creates both, signs in, and sends them where a new account goes first. `signupFields` lists what it asks.
   `useSignIn()` / `useSignUp()` give the same with your own inputs, if the design needs them.

<WorkflowForm workflow={workflows.x} fields={{ …one entry per input… }} initial?={partial input}
              submitLabel? cancelHref? redirectTo? successMessage? columns?={1 | 2} onDone?={(r) => …} />
   The form marks the workflow's required inputs itself (an asterisk, and the browser holds an
   empty one back), shows the workflow's refusal, and clears after a create that stays on the
   page — do not add your own asterisks, required markers or reset logic.
   Each entry is either { value: … } (fixed — the record's id, a decided value; renders nothing)
   or a field: { label, kind?, options?, placeholder?, help? }, where kind follows the input's type:
     string   → "text" (default) | "textarea" | "email" | "date" | "datetime" | "select" | "password" | "url" | "tel"
     enum     → "select" with options (one per value, human labels)
     number   → "number" (min?, max?, step?)
     boolean  → "checkbox" | "switch"
     string[] → "tags" | "multiselect"
     an image field → "image" (picks, uploads, and sends the stored file's id)
   A record input (an id of another entity) is { label, kind: "select", options } with the
   options loaded in load.ts. Every REQUIRED input must have an entry — the compiler checks.

<WorkflowButton workflow={workflows.x} input={{ … }} variant?="primary" | "secondary" | "outline" | "ghost" | "danger"
                size?="sm" | "md" confirm?="Delete this case?" redirectTo? successMessage?>Label</WorkflowButton>

<ImageSearch label?="Find products that look like this" />
   The search box for similar(): an upload that sets ?image= to the picked picture (and clears it).

<WidgetView widget={widgets.x} data={props.x} height?={260} currency?="GBP" action?={<Link …/>}
            onSelect?={(s) => router.push(href(pages.list, {}, { status: s.category }))} />
   Draws a declared widget as its card: a KPI tile, a gauge, a chart with a table toggle, or a list.

// ---- @/sdk — anywhere ----
Entity types (Case, User, …), `workflows`, `pages`, `href(page, params?, query?)`,
`fileUrl(row.photo)` — the src for an image field (a stored file's id), or null when it is empty,
e.g. href(pages.caseRecord, { id }) or href(pages.allCases, {}, { q: "late", status: "OPEN" }).
"""


LIBRARY_PALETTE = """\
import { Chart, MetricTile, Sparkline, Gauge, Kanban, Timeline, ActivityFeed, Calendar,
         DataGrid, DescriptionList, PersonCard, ApprovalStepper, Stepper, KeyValueList,
         MoneyDisplay, Tag, Progress as ProgressRing } from "@tentoroforge/library";

Every one of these renders on its own with plain props; pass resolved data, never
`{{binding}}` strings. Verified shapes:

  <Chart chartType="bar" | "line" | "area" | "pie" | "donut" | "funnel" | "radar" | "scatter" | "heatmap" | "treemap"
                   | "sunburst" | "graph" | "map"
         data={rows} xKey="placedAt" series={[{ name: "Revenue", dataKey: "revenue" }]}
         colorKey?="region" yKey? valueKey? sizeKey? labelKey? format?="number" | "currency" | "percent" | "duration"
         currency?="GBP" encoding?={{ stacked?, horizontal?, sorted?: "asc" | "desc", topN?, valueLabels? }}
         height={260} onSelect?={(s: ChartSelection) => …} />
      ECharts, themed from the app's tokens; colours come from a validated palette — do not pass them.
      Rows are QueryRow[] from `query()` (or SeriesPoint[] with xKey="label", dataKey "value").
      colorKey splits long-format rows into one series per value (a line per status); heatmap takes
      xKey + yKey + valueKey; scatter takes xKey + yKey (two measures), sizeKey for bubbles;
      sunburst nests xKey under colorKey like treemap; graph links xKey → yKey, valueKey the link's
      weight; map colours the country named (or ISO-coded) in xKey by valueKey.
      One value axis only — never plot two measures of different scale on one chart.
  <MetricTile label="Open cases" value={42} format="number" | "currency" | "percent"
              delta={{ value: 0.12, direction: "up" }} trend={[3, 5, 4, 7]} />
      delta.value is a FRACTION (0.12 = 12%). Omit delta when you have no comparison.
  <Sparkline data={[3, 5, 4, 7]} width={120} height={32} />
  <Gauge value={72} min={0} max={100} label="SLA met" unit="%" />
  <Kanban data={rows} groupBy="status" columnOrder={["OPEN", "IN_PROGRESS", "RESOLVED"]}
          cardTitle="title" cardDescription="requesterName" cardBadge="priority"
          cardHref="/cases/{{id}}" />      (cardHref is the one place `{{field}}` is allowed)
  <Timeline entries={[{ title, timestamp, description }]} />
  <ActivityFeed title="Activity" entries={[{ actorName, action, target, timestamp }]} />
  <Calendar events={rows} dateField="dueDate" titleField="title" view="month" | "week" | "agenda" />
  <DataGrid columns={[{ key: "title", label: "Title", sortable: true }]} rows={rows} rowKey="id" />
  <DescriptionList items={[{ label: "Guest", value: "Emma Clarke" }]} orientation="horizontal" />
      value is TEXT (a string or number) — it is printed, so a JSX value renders as
      "[object Object]". For a badge, a link or formatted markup in a value, write your
      own <dl> grid instead. The same holds for KeyValueList.
  <PersonCard name="Maya Patel" role="Case manager" email="maya@hotel.test" />
  <ApprovalStepper steps={[{ id: "a", label: "Submitted", status: "complete" | "current" | "pending" | "rejected" }]} />
  <KeyValueList items={[{ label: "Folio", value: "RSV-88037" }]} />      (value is text)
  <MoneyDisplay value={1240.5} currency="GBP" />
  <Tag label="Urgent" variant="default" | "primary" | "success" | "warning" | "danger" />

The library's props are typed loosely; the shapes above are the contract. Do not use
any other library component."""


DESIGN_PRINCIPLES = """\
What a finished page looks like:

- AN `auth` PAGE IS THE WHOLE SCREEN, and the one exception to the frame below:
  nothing wraps it, so it carries the product itself — its name, a line on what
  it is for, the brand's colour — beside or above the form. A `login` page places
  <SignInForm /> and links to the signup page; a `signup` page places
  <SignUpForm /> (it already asks for the person's own details and the login)
  and links to sign in. Both from "@/sdk/client". Never hand-roll the sign-in or
  the signup request, and never ask again for what the form asks. Its `load`
  returns `{}` or what the page shows beside the form.
- THE FRAME IS NOT YOURS. The application wraps every page in its own frame —
  the sidebar for signed-in pages, the top bar for public ones — with the
  app's name or logo, the menu, and sign-in. Never draw a sidebar, a top
  navigation bar, an app-name or logo header, a menu of the app's pages, or a
  footer. A page that does looks different from its neighbours, and the app
  shows two menus. Your page is the content area: start with its own header.
  Links to related pages belong in the content (a back link, a "view all").
  The frame also sets the page's width and outer padding — do not wrap the
  page in a max-width container or add outer page padding; fill the width you
  are given (a narrow form may sit in a card of its own width inside it).

- ONE JOB, OBVIOUS. The page header says where you are (small eyebrow + title) and
  shows the one primary action for the page on the right. Secondary actions are
  outline or ghost buttons, never a row of equal primaries.
- THE ACCENT MARKS WHAT TO DO NOW — once per screen. The one action this screen is
  for (Submit claim, Book appointment, Send request) is the accent:
  <Button variant="accent">, <WorkflowButton variant="accent">, or
  <WorkflowForm submitVariant="accent">. The active status or the selected filter
  chip is its tint: bg-accent-subtle text-accent-subtle-foreground. Everything
  else stays in the primary and the neutrals; an accent on every row is no accent.
- THE CONTENT PLAN IS THE PAGE. When the brief carries `content`, every fact in it
  is on the page, in its prominence: `lead` leads the screen, `key` facts sit with
  the title, `supporting` further down, `reassurance` beside the main action. Each
  comes with its `read` — do it in load.ts (in parallel) and show the value in
  words, labelled as the plan labels it. `process` facts are copy you write from
  `writeProcessCopyFrom`: plain sentences for the reader, true to those rules and
  steps. Add nothing the data cannot produce.
- LEAD WITH WHAT MATTERS NOW. Before the list, decide what this person came to see
  first — the appointment that is next, the request waiting on them, the step
  not yet done — and give it one card of its own at the top in the dark surface
  (bg-inverse text-inverse-foreground, supporting text text-inverse-foreground/70)
  with its facts in words ("Due in 1 day 6 hrs · Mon 18:00") and its action.
  Then the rest, grouped by what the reader does with it (e.g. Active · Upcoming
  · Past), not by table.
- PLACES ARE DISTANCES. A `location` is never shown as numbers or a map pin of
  someone's home: show how far it is (formatDistance → "0.4 mi"), rank lists with
  near(…, await whereAmI(ctx)), offer <NearMe /> beside the search on a list of
  nearby things, and in a form it is { label, kind: "location" } — the person
  shares an approximate position with a button.
- NAMES, NEVER IDS. A reader never sees an id or a shortened one ("Order #a1b2…"). A
  foreign key is shown as the record it points at — its name, its owner, its
  picture: load them with recordsById(Entity, rows.map(r => r.customerId)) in load.ts
  and show `customers[r.customerId]?.name`. A row that names a thing says which one.
- SAY WHAT HAPPENS NEXT. Before an action with consequences (a complaint, a payment,
  a cancellation) say plainly what it does and what follows — a short numbered
  "What happens next", or one reassuring line drawn from the app's own rules and
  steps. Copy is written for the person, in the domain's words.
- HIERARCHY BEFORE DECORATION. Size, weight and spacing carry the structure; colour
  is for meaning (status, priority, money in/out). Use tabular-nums for figures.
- REAL CONTENT, REAL STATES. Every list has an empty state that says what to do next
  (and offers the action). Every record page handles a missing optional field with
  a quiet em dash, not "null". Long text truncates with a title attribute.
- NUMBERS WITH CONTEXT. A KPI is a label, a big number and, where the data allows, a
  comparison or a sparkline. Money is formatted with its currency; dates with
  Intl.DateTimeFormat (en-GB unless the app says otherwise); relative times for
  recent events.
- STATUS AS A SYSTEM. Map each enum value to one tone once (a Record<Enum, string> of
  classes) and use it everywhere on the page: bg-success-subtle text-success-subtle-foreground,
  bg-warning-subtle text-warning-subtle-foreground, bg-destructive/10 text-destructive,
  bg-muted text-muted-foreground, bg-primary/10 text-primary.
- LISTS THAT WORK. Search box (writes ?q=), filter chips for the key enum (write
  ?status=), sortable columns where it matters, a row that opens the record
  (href(pages.x, { id })), row actions for the workflows that act on one record.
- PICTURES ARE SHOWN, NOT NAMED. An image field is a thumbnail (fileUrl) in a list
  and a real image on its record — never the id. The list of an entity that is
  "Findable by likeness" offers "Find similar": <ImageSearch /> beside the search
  box, and while ?image= (or ?q=) is set, the rows are similar()'s, closest first.
- RECORD PAGES TELL THE STORY. Title with its status badge, key facts in a
  definition grid, the related records (notes, activity) as a timeline or table,
  and the actions available in the record's current state — nothing that cannot
  run now.
- FORMS ARE CALM. WorkflowForm with a sensible field order, the right `kind` per
  field, help text where a rule is not obvious, two columns on wide screens.
- RESPONSIVE. Mobile first: stack below `md`, grids above. Nothing overflows at
  375px; wide tables scroll horizontally inside their card.
- ACCESSIBLE. Real <button>/<a>, labels on inputs, aria-label on icon-only buttons,
  visible focus (the kit handles it), sufficient contrast (use the tokens).
- TOKENS, NOT HEX. Only the semantic classes, each for its job: bg-background (the
  ground), bg-card (panels), bg-muted / bg-secondary (quiet fills), text-foreground,
  text-muted-foreground, border, bg-primary / text-primary (brand, default button,
  links), bg-accent / bg-accent-subtle (what to do now, see above), bg-inverse (the
  one leading card), ring-ring, and the success / warning / destructive / info
  families. Never a hex colour or an arbitrary palette like bg-blue-500.
- TYPE IN TWO VOICES. Page titles and card titles are `font-heading` (the design's
  display face; h1–h3 get it by default); everything else is the body face. Never
  `font-serif` or `font-mono` for a title — they are the browser's, not the design's.
"""


TECH_RULES = """\
You write exactly two files for the page.

load.ts — server only.
  import { … } from "@/sdk/server";   (reads: list, listPage, record, recordsById, near, whereAmI, count, total, series, similar, currentUser, myAccount)
  export async function load(ctx: PageContext) { … return { …props } }
  - Return a plain object: the view's props. Return null for a record that does not
    exist (the route answers 404).
  - Read everything the view shows here, in parallel with Promise.all.
  - Record routes: the id is ctx.params.id (the param named in the route's [brackets]).
  - Filters and search come from ctx.searchParams.
  - Options for a record input (a select of Users, Properties…) are loaded here too:
    (await list("User", { limit: 200 })).map(u => ({ label: u.name ?? u.email, value: u.id })).
  - Nothing else: no fetch, no database, no process.env.

view.tsx — "use client" on the first line.
  export default function View(props: Props), with Props exactly what load returns:
    import type { load } from "./load";
    type Props = NonNullable<Awaited<ReturnType<typeof load>>>;
  Imports allowed, and only these:
    react, next/link, next/navigation (useRouter, useSearchParams, usePathname),
    lucide-react (icons), the UI kit and library below,
    "@/sdk" (entity types, workflows, pages, widgets, href, fileUrl), "@/sdk/client" (useWorkflow,
    WorkflowForm, WorkflowButton, WidgetView, ImageSearch, NearMe, formatDistance, distanceKm), and
    `import type { Page, SeriesPoint, QueryRow, WidgetData } from "@/sdk/server"`.
  - Links: <Link href={href(pages.someKey, { id: row.id })}> — never a hand-written path.
  - Changing data: only through a workflow — <WorkflowForm workflow={workflows.x} fields={…} />,
    <WorkflowButton workflow={workflows.x} input={{ … }} />, or useWorkflow(workflows.x).run(input).
    `fields` has one entry per workflow input, keyed by the input's name; an input the page
    already knows (the record's id, a fixed decision) is { value: … } and renders nothing.
  - Search / filters: update the URL with router.push(href(pages.thisPage, params?, query)).
  - TypeScript strict: no `any`, no non-null assertions on data that can be null, handle
    null fields. Keep it one file; small local components are fine.
  - No placeholder copy ("Lorem", "TODO", "Coming soon"), no fake data, no alert().
"""


def _about(doc: dict) -> str:
    """What the application is for — its objectives and who uses it, and its
    description without the connection instructions a brief can carry."""
    app = doc.get("application") or {}
    prod = doc.get("product") or {}
    desc = " ".join(line for line in str(app.get("description") or "").splitlines()
                    if line.strip() and not re.search(r"https?://|token|environment variable", line, re.I))
    out = [desc[:1200]]
    objectives = [o.get("statement") or o.get("text") or o.get("name") if isinstance(o, dict) else str(o)
                  for o in prod.get("objectives") or []]
    if objectives:
        out.append("Objectives: " + "; ".join(str(o) for o in objectives[:6] if o))
    personas = [f"{p.get('name')} ({p.get('goal') or p.get('description') or ''})".strip(" ()")
                for p in prod.get("personas") or [] if isinstance(p, dict)]
    if personas:
        out.append("Who uses it: " + "; ".join(personas[:6]))
    return "\n".join(x for x in out if x)


def _look(doc: dict) -> str:
    """The design system as the page author uses it: the personality, each
    colour role with the class that draws it, and the two type faces."""
    design = doc.get("designSystem") or {}
    colors = design.get("colors") or {}
    typo = design.get("typography") or {}
    classes = {"background": "bg-background", "surface": "bg-card", "textPrimary": "text-foreground",
               "textSecondary": "text-muted-foreground", "primary": "bg-primary / text-primary",
               "accent": "bg-accent / variant=\"accent\"", "accentSubtle": "bg-accent-subtle",
               "inverse": "bg-inverse"}
    from services.blueprint.verification import PALETTE_ROLES
    lines = [str(design.get("visualPersonality") or "")[:600]]
    for role, job in PALETTE_ROLES.items():
        value = colors.get(role)
        lines.append(f"- {classes[role]}{f' ({value})' if value else ''}: {job}")
    head = typo.get("fontFamilyHeading") or typo.get("fontFamilyDisplay") or typo.get("headingFontFamily")
    body = typo.get("fontFamilyBase") or typo.get("fontFamily") or typo.get("fontFamilyBody")
    if head or body:
        lines.append(f"- font-heading: {head or body}; body: {body or head}")
    return "\n".join(x for x in lines if x)


def system_prompt(doc: dict) -> str:
    """Identical for every page of one application — the cached prefix."""
    comp = doc.get("composition") or {}
    conventions = "\n".join(f"- {c.get('topic')}: {c.get('rule')}"
                            for c in comp.get("conventions") or []) or "- (none stated)"
    app = doc.get("application") or {}
    return f"""You are the UI engineer of {app.get('name') or 'this application'}: you write one page of a \
Next.js 15 (App Router, React 19, TypeScript strict, Tailwind) application, and you are held to the \
standard of the best modern SaaS products — Linear, Stripe, Notion, Vercel. The page must be complete, \
beautiful and correct: it is shipped as you write it.

# The application
{app.get('name')}
{_about(doc)}

# Its direction — follow it on every page
{comp.get('vision') or '(no vision stated — choose a calm, professional, information-dense style)'}
{conventions}

# Its look — what each colour class means here
{_look(doc)}

# Rules
{TECH_RULES}
# The app SDK — generated from this application's Blueprint

How to use it:
```ts
{SDK_GUIDE}
```

This application's entities, workflows and pages:
```ts
{sdk_reference(doc)}
```

# The UI kit (shadcn, themed by the app's tokens)
```ts
{_kit_exports()}
```
Button variants: default | secondary | outline | ghost | destructive | link; sizes: default | sm | lg | icon.
Badge variants: default | secondary | destructive | outline | success | warning | muted.
Icons: any lucide-react icon, e.g. `import {{ Plus, Search, Filter }} from "lucide-react"`.
Charts: the library's Chart (ECharts) — every chart the page draws goes through it.

# Analytics
A page's brief lists the widgets the Blueprint attaches to it — its KPIs, charts and breakdowns. Every one
of them appears on the page: read each in `load.ts` with `runWidget(widgets.x)` (in parallel, with
Promise.all) and draw it with `<WidgetView widget={{widgets.x}} data={{…}} />`, or with `Chart` when the page
needs a custom arrangement of the same rows. Lead with the metrics as a row of tiles, then the charts in a
responsive grid (`size`: sm = a quarter, md = a half, lg = two thirds, full = the whole row); on a record
page, narrow each widget to the record with `where`. A dashboard with widgets over dates gets a date range
filter in the URL (`?from=&to=`, presets such as last 30 days / 90 days / 12 months) passed to every
`runWidget` as `range`, and a chart whose category is a status, a type or a record links to the list it
summarises through `onSelect`. You may add a chart the brief does not list when the page's job calls for it
(use `query()`), never a number the data cannot produce.

# The component library
```ts
{LIBRARY_PALETTE}
```

# Design
{DESIGN_PRINCIPLES}
Reply with the rationale and the full contents of both files."""


def _page_brief(doc: dict, page: dict) -> dict:
    pages = {str(p.get("id")): p for p in doc.get("pages") or []}
    from services.blueprint.app_sdk import page_keys, workflow_keys
    pkeys, wkeys = page_keys(doc), workflow_keys(doc)
    launched = [w for w in doc.get("workflows") or []
                if str(page.get("id")) in [str(x) for x in (w.get("launchedFrom") or [])]
                and w.get("status") != "DEPRECATED"]
    ents = {str(e.get("id")): e for e in (doc.get("data") or {}).get("entities") or []}
    data = page.get("data") or {}
    return {
        "page": {k: page.get(k) for k in ("id", "name", "route", "pattern", "purpose", "primaryTasks",
                                          "actions", "states", "users", "access", "responsive")
                 if page.get(k) not in (None, [], "")},
        "sdkKey": pkeys.get(str(page.get("id"))),
        "primaryEntity": (ents.get(str(data.get("primaryEntity"))) or {}).get("name"),
        "supportingEntities": [(ents.get(str(x)) or {}).get("name") for x in data.get("supportingEntities") or []],
        "leadsTo": [{"page": pages[t].get("name"), "sdkKey": pkeys.get(t), "route": pages[t].get("route")}
                    for t in (str(x) for x in page.get("navigatesTo") or []) if t in pages],
        "workflowsLaunchedHere": [{"sdkKey": wkeys.get(str(w.get("id"))), "name": w.get("name"),
                                   "purpose": w.get("purpose"),
                                   "trigger": (w.get("trigger") or {}).get("detail")} for w in launched],
        "roles": [r.get("name") for r in doc.get("roles") or [] if r.get("id") in (page.get("users") or [])],
        "widgets": page_widget_brief(doc, page),
        **_content_part(doc, page),
    }


def _content_part(doc: dict, page: dict) -> dict:
    """The page's content plan, each fact with the read that produces it, and
    the rules and steps its `process` facts are written from."""
    from services.blueprint.page_content import content_brief, process_grounding

    content = content_brief(doc, page)
    if not content:
        return {}
    grounding = process_grounding(doc, page)
    return {"content": content, **({"writeProcessCopyFrom": grounding} if grounding else {})}


def page_widget_brief(doc: dict, page: dict) -> list[dict]:
    """The analytics the Blueprint attaches to this page, by their SDK key,
    in the order the page shows them."""
    from services.blueprint.app_sdk import widget_keys, widget_query

    keys = widget_keys(doc)
    mine = sorted((w for w in doc.get("widgets") or []
                   if str(w.get("page")) == str(page.get("id")) and w.get("status") != "DEPRECATED"),
                  key=lambda w: w.get("order") or 0)
    out = []
    for w in mine:
        src = widget_query(doc, w)
        if src is None:
            continue
        item = {"sdkKey": keys.get(str(w.get("id"))), "label": w.get("label"), "kind": w.get("kind"),
                "unit": w.get("unit") or "number"}
        for k in ("description", "chart", "size"):
            if w.get(k):
                item[k] = w[k]
        if src.get("op") == "query":
            item["reads"] = {"entity": src["entity"],
                             "measures": [m["key"] for m in src.get("measures") or []],
                             "by": [d["field"] + (f" per {d['bucket']}" if d.get("bucket") else "")
                                    for d in src.get("dimensions") or []]}
        out.append(item)
    return out


def user_prompt(doc: dict, page: dict, *, feedback: str = "", brief: str = "",
                current: dict | None = None) -> str:
    out = ["Write this page.\n\n```json\n" + json.dumps(_page_brief(doc, page), indent=2) + "\n```"]
    if brief:
        out.append(f"\nWhat is wanted of it now:\n{brief}")
    if current:
        out.append("\nIts current code, to improve rather than start over:\n"
                   f"```ts\n// load.ts\n{current.get('load')}\n```\n```tsx\n// view.tsx\n{current.get('view')}\n```")
    if feedback:
        out.append(f"\nYour previous version was refused. Fix every one of these and keep what worked:\n{feedback}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

_SDK_LOCK = threading.Lock()


def ensure_sdk(doc: dict, app_root: Path) -> None:
    """The SDK the check compiles against: the fixed half from the scaffold
    (when the tree does not have it yet) and the half generated from `doc`."""
    with _SDK_LOCK:
        target = app_root / "src/sdk"
        target.mkdir(parents=True, exist_ok=True)
        for f in _SDK_TEMPLATE.glob("*.ts*"):
            dst = target / f.name
            if not dst.exists() or dst.read_text() != f.read_text():
                shutil.copyfile(f, dst)
        project_app_sdk(doc, app_root)


class CompileError(RuntimeError):
    """The page's code did not type-check; the message is the compiler's."""


def typecheck(doc: dict, app_root: Path, page_id: str, load: str, view: str,
              timeout: float = 180.0) -> list[str]:
    """Compile one page — its route module, load and view — against the SDK.

    Only errors in the page's own three files count: the scaffold's modules
    are built with type errors ignored and carry some, and a page is not the
    place they are fixed. Returns the errors, empty when it compiles."""
    tsc = app_root / "node_modules/.bin/tsc"
    if not tsc.exists():
        raise RuntimeError(f"no TypeScript compiler under {app_root} — install has not run")
    ensure_sdk(doc, app_root)
    files = code_page_files(doc, {"page": page_id, "load": load, "view": view})
    if not files:
        return [f"{page_id} is not a live page"]
    check = app_root / ".forge-check" / f"{page_id}-{os.getpid()}-{threading.get_ident()}"
    if check.exists():
        shutil.rmtree(check, ignore_errors=True)
    check.mkdir(parents=True)
    try:
        for rel, content in files.items():
            (check / Path(rel).name).write_text(content)
        (check / "tsconfig.json").write_text(json.dumps({
            "extends": "../../tsconfig.json",
            "compilerOptions": {"incremental": False, "noEmit": True},
            "include": ["page.tsx", "load.ts", "view.tsx", "../../next-env.d.ts",
                        "../../src/types/**/*.d.ts"],
        }))
        proc = subprocess.run([str(tsc), "-p", str(check / "tsconfig.json"), "--pretty", "false"],
                              cwd=str(app_root), capture_output=True, text=True, timeout=timeout)
        # tsc prints paths relative to its own idea of the cwd — under a
        # symlinked root (`/tmp` on macOS) that is `../../../../tmp/…/<check>/`,
        # so the check directory is looked for anywhere in the path, not at
        # the start; a prefix match dropped every error there.
        marker = check.name + "/"
        errors: list[str] = []
        ours = False
        for line in (proc.stdout + proc.stderr).splitlines():
            where = line.split("(", 1)[0]
            if marker in where:
                errors.append(line[line.index(marker) + len(marker):])
                ours = True
            elif ours and line.startswith(" "):
                errors[-1] += " " + line.strip()          # continuation of OUR last error
            else:
                ours = False                              # a scaffold file's error, and its tail
        return errors
    finally:
        shutil.rmtree(check, ignore_errors=True)


def _unwired_actions(doc: dict, page: dict, view: str) -> list[str]:
    """Each workflow launched from this page, that the view never runs.

    The contract says what a person does on this page; a workflow launched
    from it is one of those things. A view that leaves it out compiles, looks
    finished, and has no way to do it — the missing button no one notices
    until they need it."""
    from services.blueprint.app_sdk import workflow_keys

    keys = workflow_keys(doc)
    out = []
    for w in doc.get("workflows") or []:
        if w.get("status") == "DEPRECATED":
            continue
        if str(page.get("id")) not in [str(x) for x in (w.get("launchedFrom") or [])]:
            continue
        key = keys.get(str(w.get("id")))
        if key and not re.search(r"\bworkflows\." + re.escape(key) + r"\b", view):
            out.append(f"view.tsx: `{w.get('name')}` is launched from this page (workflows.{key}) "
                       f"but nothing on it runs it — give it a control: a WorkflowForm, a "
                       f"WorkflowButton, or useWorkflow(workflows.{key}).")
    return out


def _static_findings(load: str, view: str) -> list[str]:
    """What the compiler cannot see and the rules forbid."""
    out = []
    if not view.lstrip().startswith(('"use client"', "'use client'")):
        out.append('view.tsx: the first line must be "use client".')
    if re.search(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", view):
        out.append("view.tsx: uses a hex colour — use the semantic token classes.")
    if re.search(r"\bfetch\(", load + view):
        out.append("load.ts/view.tsx: calls fetch — read through @/sdk/server, write through workflows.")
    if re.search(r"@/lib/|@/db", load + view):
        out.append("load.ts/view.tsx: imports app internals — only @/sdk, @/sdk/server, @/sdk/client.")
    if re.search(r"lorem ipsum|TODO|coming soon", view, re.I):
        out.append("view.tsx: placeholder copy.")
    return out


#: An id shown to a reader: a helper that shortens one, a `#` before a
#: foreign key, a key sliced for display, or a key as the whole of an
#: element's text. Keys in `href`, `key=` and `input` are not text and do
#: not match.
_ID_AS_TEXT = (
    re.compile(r"\{\s*short[A-Z]?[a-z]*Id\s*\("),
    re.compile(r"#\$?\{[^}]*(?:\.id\b|[a-z]Id\b)[^}]*\}"),
    re.compile(r"\.(?:id|[a-z]\w*Id)\s*\.\s*slice\("),
    re.compile(r">\s*\{\s*[\w?.]+\.(?:id|[a-z]\w*Id)\s*\}\s*<"),
)
#: A class that draws in the accent (hover and focus states do not count).
_ACCENT_USE = re.compile(r'(?<![:\w-])(?:bg|text|border|ring)-accent\b|variant="accent"|submitVariant="accent"')


def _design_findings(doc: dict, page: dict, view: str) -> list[str]:
    """What the design principles make checkable in the source."""
    out = []
    for rx in _ID_AS_TEXT:
        m = rx.search(view)
        if m:
            out.append(f"view.tsx: shows an id to the reader (`{m.group(0).strip()[:60]}`) — show the "
                       f"record it points at by name instead: load it with recordsById(...) in load.ts.")
            break
    if re.search(r"(?<![:\w-])font-(?:serif|mono)\b", view):
        out.append("view.tsx: `font-serif`/`font-mono` are the browser's faces, not the design's — "
                   "titles use `font-heading`, the rest the body face.")
    launches = any(str(page.get("id")) in [str(x) for x in (w.get("launchedFrom") or [])]
                   for w in doc.get("workflows") or [] if w.get("status") != "DEPRECATED")
    if launches and not _ACCENT_USE.search(view) and str(page.get("pattern") or "") != "auth":
        out.append("view.tsx: nothing on this page is in the accent — the one action this screen is "
                   "for (or its active state) is variant=\"accent\" / submitVariant=\"accent\" / "
                   "bg-accent-subtle.")
    return out


def compose_page(doc: dict, page: dict, app_root: Path, client: Any, *,
                 feedback: str = "", brief: str = "", current: dict | None = None,
                 usage: Any = None, node: str = "page_code") -> tuple[dict, list[Any]]:
    """Author one page and compile it, returning the accepted `pageCode` body
    and the usage of every call. Raises CompileError when the last round still
    does not compile — the message carries the errors for the next attempt."""
    system = system_prompt(doc)
    spent: list[Any] = []
    note = feedback
    last_errors: list[str] = []
    for round_ in range(1, COMPILE_ROUNDS + 1):
        t0 = time.monotonic()
        reply = client(system=system, user=user_prompt(doc, page, feedback=note, brief=brief,
                                                         current=current),
                       schema=PAGE_CODE_SCHEMA)
        text = getattr(reply, "text", reply)
        if getattr(reply, "usage", None) is not None:
            spent.append((reply.usage, time.monotonic() - t0))
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            note = f"Your reply was not valid JSON ({exc}). Return the object only."
            continue
        load, view = str(body.get("load") or ""), str(body.get("view") or "")
        design = _design_findings(doc, page, view)
        errors = (_static_findings(load, view) + _unwired_actions(doc, page, view)
                  + typecheck(doc, app_root, str(page.get("id")), load, view))
        # THE STYLE RULES ASK AGAIN; THEY NEVER COST A PAGE. A page that
        # compiles and runs is kept on the last round whatever its design
        # findings — losing the page is worse than an unaccented button.
        if design and not errors and round_ == COMPILE_ROUNDS:
            logger.warning("[ui_engineer] %s accepted with design findings: %s",
                           page.get("id"), "; ".join(design)[:400])
        else:
            errors += design
        if not errors:
            # WHAT IT COST, WHERE SOMEBODY CAN COUNT IT. This node is the
            # longest in a build — 343s of a 616s run on a ONE-PAGE
            # calculator — and nothing recorded whether that was one round or
            # three. The run ledger says `ok: true` and a duration; the usage
            # ledger had no row for it at all. So the only honest answer to
            # "why is it slow" was to guess, and neither COMPILE_ROUNDS nor
            # the 36k-character system prompt can be tuned on a guess.
            #
            # The loop already knows: one entry in `spent` per model call.
            logger.info("[ui_engineer] %s composed in %d round(s), %d chars "
                        "emitted (load %d + view %d)",
                        page.get("id"), round_, len(load) + len(view),
                        len(load), len(view))
            return ({"page": str(page.get("id")), "rationale": str(body.get("rationale") or ""),
                     "load": load, "view": view,
                     "requirements": list(page.get("requirements") or [])}, spent)
        last_errors = errors
        current = {"load": load, "view": view}
        note = ("The TypeScript compiler (strict) and the page rules refused it:\n"
                + "\n".join(f"- {e}" for e in errors[:40]))
        logger.warning("[ui_engineer] %s round %d: %d error(s): %s", page.get("id"), round_,
                       len(errors), "; ".join(errors[:3])[:400])
    raise CompileError(f"{page.get('id')}: still does not compile after {COMPILE_ROUNDS} rounds — "
                       + "; ".join(last_errors[:12]))


# ---------------------------------------------------------------------------
# The direction
# ---------------------------------------------------------------------------

def direction_prompts(doc: dict) -> tuple[str, str]:
    app = doc.get("application") or {}
    ds = doc.get("designSystem") or {}
    system = ("You are the design director of a software product. You decide, once, what the whole "
              "application should feel like and the conventions every page will follow, so that "
              "thirty pages written separately read as one product of the quality of Linear, "
              "Stripe or Notion. Be concrete: a page author must be able to follow each rule "
              "without guessing. Rules are about layout, hierarchy, density, tone of copy, how "
              "status and money read, empty/loading/error states, where actions live, and how "
              "lists, records and forms are built — never about colours by hex (the design "
              "system owns the palette).")
    pages = [{k: p.get(k) for k in ("name", "route", "pattern", "purpose")}
             for p in doc.get("pages") or [] if p.get("status") != "DEPRECATED"]
    roles = [r.get("name") for r in doc.get("roles") or []]
    user = (f"The application: {app.get('name')}\n{str(app.get('description') or '')[:2000]}\n\n"
            f"Who uses it: {', '.join(r for r in roles if r) or 'staff'}\n\n"
            f"Its design system (palette, type, radius, density):\n"
            f"{json.dumps({k: ds.get(k) for k in ('register', 'density', 'typography', 'radius', 'tone', 'personality') if ds.get(k)}, indent=1)[:3000]}\n\n"
            f"Its pages:\n{json.dumps(pages, indent=1)[:12000]}\n\n"
            "Return `vision` — one paragraph a page author reads before every page — and "
            "8 to 14 `conventions`, each a topic and a precise rule.")
    return system, user


def compose_direction(doc: dict, client: Any) -> tuple[dict, Any]:
    system, user = direction_prompts(doc)
    reply = client(system=system, user=user, schema=DIRECTION_SCHEMA)
    body = json.loads(getattr(reply, "text", reply))
    return ({"vision": str(body.get("vision") or ""),
             "conventions": [{"topic": str(c.get("topic")), "rule": str(c.get("rule"))}
                             for c in body.get("conventions") or []]},
            getattr(reply, "usage", None))


def settle_code_pages(svc: Any, app_root: str | Path, client: Any = None,
                      usage: Any = None) -> dict[str, str]:
    """Compile every coded page against the FINISHED tree, just before it is built.

    A page is compiled when it is written, but that tree is not yet the one
    that ships — the scaffold's last layer lands at assembly — and `next build`
    ignores type errors, so a page that fails here would ship broken. On
    2g13o6yz (2026-09-19) the root page was accepted with a `load()` its route
    calls as `load(ctx)`. So: each coded page is compiled again, in parallel;
    one that fails goes back to its author once with the compiler's words; one
    that still fails loses its code and is served by its layout, which every
    page has. Returns `{page_id: outcome}` for the pages that did not pass."""
    import concurrent.futures as cf
    import copy as _copy

    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
    from services.blueprint.app_sdk import project_code_pages

    root = Path(app_root)
    with svc.lock:
        doc = _copy.deepcopy(svc.doc)
    rows = [r for r in doc.get("pageCode") or [] if r.get("status") != "DEPRECATED"]
    pages = {str(p.get("id")): p for p in doc.get("pages") or []}

    def check(row: dict) -> tuple[dict, list[str]]:
        return row, typecheck(doc, root, str(row["page"]), str(row["load"]), str(row["view"]))

    with cf.ThreadPoolExecutor(6) as pool:
        failing = [(r, e) for r, e in pool.map(check, rows) if e]
    outcome: dict[str, str] = {}
    if not failing:
        return outcome

    def fix(item: tuple[dict, list[str]]) -> tuple[str, dict | None, list[str]]:
        row, errors = item
        pid = str(row["page"])
        if client is None or pid not in pages:
            return pid, None, errors
        note = ("It compiled when you wrote it, but not in the finished application. The "
                "TypeScript compiler (strict) says:\n" + "\n".join(f"- {e}" for e in errors[:40]))
        try:
            body, spent = compose_page(doc, pages[pid], root, client, feedback=note, current=row)
        except CompileError as exc:
            return pid, None, [str(exc)]
        if usage is not None:
            for u, elapsed in spent:
                usage.record(node="page_code", agent="ui_engineer", usage=u, elapsed_s=elapsed,
                             project=str((doc.get("application") or {}).get("id", "")))
        return pid, body, []

    with cf.ThreadPoolExecutor(6) as pool:
        fixed = list(pool.map(fix, failing))
    with svc.lock:
        for pid, body, errors in fixed:
            if body is not None:
                apply_agent_result(svc, AgentResult(
                    task_id=f"TASK-settle-{pid}", agent="ui_engineer", confidence=0.9,
                    proposals=[ArtifactProposal(section="pageCode", natural_key=pid, body=body)]),
                    commit=True)
                outcome[pid] = "rewritten"
            else:
                svc.doc["pageCode"] = [r for r in svc.doc.get("pageCode") or []
                                       if str(r.get("page")) != pid]
                svc.save()
                outcome[pid] = "served by its layout: " + "; ".join(errors[:3])[:300]
                logger.warning("[ui_engineer] %s does not compile in the finished app — "
                               "its layout serves it: %s", pid, "; ".join(errors[:3])[:300])
        project_code_pages(svc.doc, root)
    return outcome


__all__ = ["settle_code_pages", "compose_page", "compose_direction", "typecheck", "ensure_sdk", "system_prompt",
           "user_prompt", "CompileError", "PAGE_CODE_SCHEMA", "DIRECTION_SCHEMA", "COMPILE_ROUNDS"]
