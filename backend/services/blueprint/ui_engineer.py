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
from typing import Any, Sequence

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

#: The reply when the page already has code — a change Smith was asked for, a
#: compile error to fix, a reviewer's send-back. EDITS, NOT THE PAGE AGAIN.
#: Every round used to return both files whole: a request to make three
#: fields linked dropdowns came back as 16,438 characters three times over
#: (live, 2026-09-28 — one round to add the change, one to fix a missing
#: first line, one for the reviewer), 60-80s a round, and output is what a
#: run pays for. An edit quotes the text it replaces, so the rest of the page
#: is untouched by construction rather than by the writer's restraint.
PAGE_EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rationale", "edits", "load", "view", "needs"],
    "properties": {
        "rationale": {"type": "string", "description": "One or two sentences: what you changed and why."},
        "edits": {
            "type": "array",
            "description": "The changes, applied in order to the current files.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["file", "find", "replace"],
                "properties": {
                    "file": {"type": "string", "enum": ["load", "view"]},
                    "find": {"type": "string", "description": (
                        "Text copied exactly from the current file, whitespace included, long "
                        "enough to occur exactly once.")},
                    "replace": {"type": "string", "description": "What it becomes."},
                },
            },
        },
        "load": {"type": "string", "description": (
            "Empty — unless load.ts is being rewritten whole, then its full contents.")},
        "view": {"type": "string", "description": (
            "Empty — unless view.tsx is being rewritten whole, then its full contents.")},
        "needs": {
            "type": "array",
            "description": (
                "Each change to records the brief asks for that none of the application's "
                "workflows makes, in a few words (\"delete a Worker\"). Empty when every change "
                "runs a listed workflow. When it is not empty, nothing is written: the missing "
                "workflow is added first and the page is changed after."),
            "items": {"type": "string"},
        },
    },
}


class NeedsWorkflow(RuntimeError):
    """The change asks for records to change in a way no workflow does. Carries
    what is needed, in the writer's words, so the workflow is added first."""

    def __init__(self, needs: list[str]):
        self.needs = [str(n).strip() for n in needs if str(n).strip()]
        super().__init__("needs a workflow that does not exist yet: " + "; ".join(self.needs))


class EditsDidNotApply(ValueError):
    """An edit's `find` is not in the file exactly once; nothing was applied."""


def apply_edits(current: dict, edits: list[dict]) -> dict[str, str]:
    """``{"load": …, "view": …}`` with each edit applied in order, or raise
    `EditsDidNotApply` naming every edit that could not be — all or nothing,
    so a half-applied change is never compiled as if it were the page."""
    files = {"load": str(current.get("load") or ""), "view": str(current.get("view") or "")}
    problems: list[str] = []
    for i, e in enumerate(edits, 1):
        name = "load.ts" if e.get("file") == "load" else "view.tsx"
        key = "load" if e.get("file") == "load" else "view"
        find, replace = str(e.get("find") or ""), str(e.get("replace") or "")
        if not find:
            problems.append(f"edit {i} ({name}): `find` is empty — quote the text it replaces.")
            continue
        n = files[key].count(find)
        if n != 1:
            head = find.strip().splitlines()[0][:80] if find.strip() else find[:80]
            problems.append(
                f"edit {i} ({name}): `find` occurs {n} times" + (" — copy it exactly from the current code"
                                                                  if n == 0 else " — include more of the "
                                                                  "surrounding lines so it is unique")
                + f" (it begins `{head}`).")
            continue
        files[key] = files[key].replace(find, replace, 1)
    if problems:
        raise EditsDidNotApply("\n".join(problems))
    return files


def _use_client_first(view: str) -> str:
    """The first line a view must have, put there rather than asked for — a
    round of the model to add one fixed line is a round of the whole page."""
    if view.strip() and not view.lstrip().startswith(('"use client"', "'use client'")):
        return '"use client";\n' + view
    return view


#: What the writer decides BEFORE it writes, in a call of its own.
#:
#: Thinking and code come out of one budget (`max_tokens` caps both, and this
#: model takes no separate thinking budget), so on a page the Blueprint leaves
#: open — no entity, no workflows, a direction full of interacting conditions —
#: deliberation takes a share nobody chose. The same Calculator page, same
#: prompt, same 64,000: once it left room and wrote 3,200 tokens of code; once
#: it started writing and was cut off mid-string; twice it never began.
#:
#: So the deciding is asked for on its own, in a budget that cannot swallow
#: the page, and its answer is handed to the writer as input. What was
#: variance becomes two bounded steps.
PAGE_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["state", "sections", "behaviours"],
    "properties": {
        "state": {"type": "string",
                  "description": "The state this page holds and how it changes, in a sentence or two. "
                                 "'None — it renders what load.ts fetched' is a complete answer."},
        "sections": {"type": "array", "items": {"type": "string"},
                     "description": "The parts of the page, top to bottom, each named in a few words."},
        "behaviours": {"type": "array", "items": {"type": "string"},
                       "description": "One line per rule the code must satisfy, in the order you will write "
                                      "them. Say how, not that: 'divide by zero sets display to Error and "
                                      "leaves the expression', not 'handle errors'."},
    },
}

#: The plan is a page's decisions, not its code: a few hundred tokens of
#: answer. The budget is what stops the deciding running away, so it is small
#: on purpose — and it is spent whether or not the writing goes well.
PLAN_MAX_TOKENS = 8000

#: What a page costs to WRITE, once the deciding is done.
#:
#: Measured over every page this system has written: the largest — a record
#: workspace with fifteen facts and ten workflows — is 18,984 characters, and
#: the median page is 12,400. As a JSON reply that is ~8,000 output tokens,
#: which is what the Calculator's page came to when it was finally written.
#: 24,000 is three times the median and still leaves room to think; 64,000 is
#: room to think INSTEAD of writing, which is what it was used for.
WRITE_MAX_TOKENS = 24000
#: The effort the WRITE call runs at once a plan is in hand. `low` was chosen
#: on one calculator page (2026-09-21) for cost and time; whether it costs
#: design quality is an A/B question, and this is the knob it turns.
WRITE_EFFORT = "low"

#: The page rhythm's vocabulary: each decision, its options, and what the
#: page author does with each. One place, read by the direction agent's
#: schema, its brief, the page prompt and the fallback.
RHYTHM_OPTIONS: dict[str, dict[str, str]] = {
    "header": {
        "eyebrow-title": "a small eyebrow line (where you are) over the title, the one primary action on the right",
        "title-only": "a large title with a one-line description under it; the primary action on the line below, left",
        "band": "a full-width band at the top in `bg-brand-gradient` holding the title and the primary action; content starts under it",
        "compact": "one line: title on the left, actions inline on the right, a hairline under it — no eyebrow, no description",
    },
    "lead": {
        "dark-card": "one card in `bg-inverse text-inverse-foreground`",
        "gradient-band": "one band in `bg-brand-gradient`, full width, its facts in large type",
        "outlined-panel": "one panel on `bg-card` with a 2px `border-primary` left edge — no dark fill",
        "type-only": "no container: the fact in `font-heading` display size (text-4xl) with its label above it and its action beside it",
    },
    "lists": {
        "table": "a table inside a card: columns, a header row, sortable where it matters",
        "cards": "a responsive grid of cards, one per record, the label as the card title and two or three facts under it",
        "rows": "borderless rows separated by `divide-y`, each a flex line — label left, facts and status right — no card around the list",
    },
    "figures": {
        "tiles": "a grid of tiles on `bg-card`, each a label and a big number",
        "strip": "one horizontal strip on `bg-muted`: the figures side by side, separated by `divide-x`, no tiles",
        "inline": "the figures inline under the page title as `label · value` pairs in `text-muted-foreground` — no tiles, no strip. "
              "A DASHBOARD IS THE EXCEPTION: its KPI widgets are the page, drawn as tiles (`<WidgetView />`, with their change "
              "against the period before), whatever this says for other pages",
    },
    "sections": {
        "cards": "each section a card on `bg-card` with a `CardHeader`",
        "open": "no cards: a section is an `h2` in `font-heading` with a hairline under it and its content on the page ground",
        "dense": "tight panels with 12px padding and `bg-muted/40`, separated by `space-y-2` — for a screen worked all day",
    },
}

#: What a Blueprint gets when its direction states no rhythm — the anatomy
#: every app had before this existed, so nothing regresses.
RHYTHM_DEFAULT: dict[str, str] = {"header": "eyebrow-title", "lead": "dark-card", "lists": "table",
                                  "figures": "tiles", "sections": "cards"}


def derive_rhythm(doc: dict) -> dict[str, str]:
    """The rhythm the pages follow: the direction's own when it states one;
    otherwise read off the design (density, personality) so that even a build
    whose direction step was skipped does not get the default anatomy."""
    comp = doc.get("composition") or {}
    stated = comp.get("rhythm") if isinstance(comp.get("rhythm"), dict) else {}
    out = dict(RHYTHM_DEFAULT)
    design = doc.get("designSystem") or {}
    density = str(design.get("informationDensity") or "comfortable")
    personality = str(design.get("visualPersonality") or "").lower()
    if density == "compact":
        out.update(header="compact", figures="strip", sections="dense", lead="outlined-panel")
    elif any(w in personality for w in ("warm", "editorial", "playful", "friendly", "consumer")):
        out.update(header="band", lead="gradient-band", lists="cards", sections="open", figures="inline")
    elif any(w in personality for w in ("stark", "minimal", "utility", "quiet")):
        out.update(header="title-only", lead="type-only", lists="rows", sections="open")
    for key, options in RHYTHM_OPTIONS.items():
        if str(stated.get(key) or "") in options:
            out[key] = str(stated[key])
    return out


def _rhythm(doc: dict) -> str:
    """The rhythm as the page author reads it: each decision with what to do."""
    r = derive_rhythm(doc)
    return "\n".join(f"- {key}: `{r[key]}` — {RHYTHM_OPTIONS[key][r[key]]}" for key in RHYTHM_OPTIONS)


DIRECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vision", "conventions", "rhythm"],
    "properties": {
        "rhythm": {
            "type": "object", "additionalProperties": False, "required": list(RHYTHM_OPTIONS),
            "properties": {key: {"type": "string", "enum": list(opts)} for key, opts in RHYTHM_OPTIONS.items()},
        },
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
        src = f.read_text(encoding="utf-8")
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
count(entity, where?): Promise<number>   // a foreign key in where may be { in: "Entity", where: {...} }: rows whose key points at a matching record
total(entity, fn: "sum" | "avg" | "min" | "max", numericField, where?): Promise<number>   // same where
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
runWidget(widgets.x, { range?, where? }): Promise<WidgetData>      // WidgetData = { rows: QueryRow[]; value: number | null; previous?: number | null; delta?: number | null }
                                                                    // a metric read with `range` carries `delta` vs the period before (0.12 = up 12%); <WidgetView /> shows it
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
   result.id is the id of the first record the run created (open it with href(pages.x, { id: result.id }));
   result.records maps each insert step's key to the id it created; result.status is "completed", or
   "paused" when the run waits on a person's task (the record exists; its id is still in result.id).
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
     string   → "text" (default) | "textarea" | "email" | "date" | "time" | "datetime" | "select" | "password" | "url" | "tel"
                (a time of day is "time" — a picker whose value is 24-hour HH:MM — never text with a format hint)
     enum     → "select" with options (one per value, human labels)
     number   → "number" (min?, max?, step?)
     boolean  → "checkbox" | "switch"
     string[] → "tags" | "multiselect"
     an image field → "image" (picks, uploads, and sends the stored file's id)
   A record input (an id of another entity) is { label, kind: "select", options } with the
   options loaded in load.ts. Every REQUIRED input must have an entry — the compiler checks.

<WorkflowButton workflow={workflows.x} input={{ … }} variant?="primary" | "secondary" | "outline" | "ghost" | "danger"
                size?="sm" | "md" confirm?="Delete this case?" redirectTo? successMessage?>Label</WorkflowButton>

A form input for an image field is kind: "image" (a picker that uploads); for any other stored file
(a document, a PDF) kind: "file", with accept?=".pdf,.docx" — never a text box for either. Show a stored
file with <a href={fileUrl(row.x)}>, an image with <img src={fileUrl(row.x)} />.

<ImageSearch label?="Find products that look like this" />
   The search box for similar(): an upload that sets ?image= to the picked picture (and clears it).

// ---- @/sdk/i18n — view.tsx, only in an application shown in more than one language ----
const t = useT();  t({ en: "Orders", hi: "ऑर्डर" })
   The text in the language the person chose in the frame's switch; each key a language of the
   application. The frame holds the only switch — a page never draws one of its own.
<LanguageSwitch className? />
   That switch, for the sign-in and sign-up pages only: they have no frame.

// ---- @/sdk/camera — view.tsx, only on a page that uses the camera ----
<CameraCapture onCapture={(dataUrl) => …} label?="Take photo" facing?="environment" | "user" className? />
   The live camera: a viewfinder and a shutter. onCapture gets the frame as an image data URL — what a
   workflow's image input takes. Where the device has no camera or the person declines it, it offers a
   picture from the device instead, so the page needs no second path. There is no flash control.
   Each is ONE frame (4:5 unless className sizes it) with its own controls on it — the shutter, "Scan
   again" — so set it where the viewfinder goes and draw no shutter or frame of your own.
<BarcodeScanner onScan={({ value, format, image }) => …} label? className? />
   Reads a barcode or QR code from the live camera, continuously, and calls onScan once with the value,
   its format ("EAN-13", "UPC-A", "QR", "CODE-128", …) and `image`, the frame it was read from (an image
   data URL) — pass it on where a workflow can identify from a picture; "Scan again" starts over. Where there is no camera it
   says why — keep a typed entry beside it for that case.
   A page that takes a picture or reads a code uses these: never a placeholder frame standing in for a
   camera, and never a file picker labelled as one.

<WidgetView widget={widgets.x} data={props.x} height?={260} currency?="GBP" action?={<Link …/>} title?={false}
            onSelect?={(s) => router.push(href(pages.list, {}, { status: s.category }))} />
   Draws a declared widget as its card: a KPI tile, a gauge, a chart with a table toggle, or a list.
   The card shows the widget's own label and description as its title. Say a chart's name ONCE:
   either let the card title it, or head it yourself (a section heading) and pass title={false} —
   never both.

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

The library's props are typed loosely; the shapes above are the contract. Nothing else the
library exports is for a page (its other names are the engine's); what these do not cover,
you write yourself."""


DESIGN_PRINCIPLES = """\
What a finished page looks like:

- AN `auth` PAGE IS THE WHOLE SCREEN, and the one exception to the frame below:
  nothing wraps it, so it carries the product itself — its name, a line on what
  it is for, the brand's colour — beside or above the form. The page hands the
  view one full-height cell: fill it (`min-h-full`, or `min-h-dvh`) and centre
  the form in it, so a short form does not sit at the top of an empty screen.
  A `login` page places
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

- ONE JOB, OBVIOUS. The page header says where you are and shows the one primary
  action for the page, built as the rhythm's `header` says. Secondary actions are
  outline or ghost buttons, never a row of equal primaries.
- THE ACCENT MARKS WHAT TO DO NOW — once per screen. The one action this screen is
  for (Submit claim, Book appointment, Send request) is the accent:
  <WorkflowButton variant="accent">, <WorkflowForm submitVariant="accent">, or your
  own `bg-accent text-accent-foreground` button. The active status or the selected filter
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
  not yet done — and give it its own place at the top, built as the rhythm's
  `lead` says (a dark card is `bg-inverse text-inverse-foreground`, supporting
  text `text-inverse-foreground/70`), with its facts in words ("Due in 1 day
  6 hrs · Mon 18:00") and its action. Then the rest, grouped by what the reader
  does with it (e.g. Active · Upcoming · Past), built as the rhythm's `lists`
  and `sections` say.
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
- THE GRADIENT HAS THREE HOMES, AND NO OTHERS. `bg-brand-gradient` (its text is
  already set) may paint the one leading card instead of bg-inverse, the sign-in
  page's brand panel, and a hero band at the top of a home or dashboard — one of
  these per screen at most, and where a photograph is given it goes UNDER the
  photo as its scrim (`bg-brand-gradient` on the container, the <img> at
  `opacity-80 mix-blend-multiply` or a `bg-gradient-to-t from-gradient-start/80`
  overlay). Never behind body text, tables, forms or lists; never `from-blue-500`.
  A number tile or a chart card stays on bg-card.
- PHOTOGRAPHS, WHERE THEY EARN THEIR PLACE. When the look names a photograph for a
  job, use it for that job and nothing else: `object-cover` in a container of
  fixed height (the brand panel, a 40-56 px-tall hero band on `md`, the empty
  state's picture), with `alt` as given and the credit in one small muted line —
  `Photo by <a href=link>Name</a> on Unsplash` — beside or under it. A page never
  loads a picture the look does not name, and never one from another host.
- REAL CONTENT, REAL STATES. Every list has an empty state that says what to do next
  (and offers the action). Every record page handles a missing optional field with
  a quiet em dash, not "null". Long text truncates with a title attribute.
- NUMBERS WITH CONTEXT. A figure is a label, a number and, where the data allows, a
  comparison or a sparkline, laid out as the rhythm's `figures` says. Money is
  formatted with its currency; dates with
  Intl.DateTimeFormat (en-GB unless the app says otherwise); relative times for
  recent events.
- STATUS AS A SYSTEM. Map each enum value to one tone once (a Record<Enum, string> of
  classes) and use it everywhere on the page: bg-success-subtle text-success-subtle-foreground,
  bg-warning-subtle text-warning-subtle-foreground, bg-destructive/10 text-destructive,
  bg-muted text-muted-foreground, bg-primary/10 text-primary.
- LISTS THAT WORK. Search box (writes ?q=), filter chips for the key enum (write
  ?status=), each record opening its page (href(pages.x, { id })), row actions for
  the workflows that act on one record — in the shape the rhythm's `lists` says
  (sortable columns where it is a table).
- PICTURES ARE SHOWN, NOT NAMED. An image field is a thumbnail (fileUrl) in a list
  and a real image on its record — never the id. The list of an entity that is
  "Findable by likeness" offers "Find similar": <ImageSearch /> beside the search
  box, and while ?image= (or ?q=) is set, the rows are similar()'s, closest first.
- MONEY SAYS ITS CURRENCY. A price is shown in the currency its record carries
  (Intl.NumberFormat with that currency), never a fixed symbol; amounts in different
  currencies are never added, compared or put in one range — group them by currency.
- NOTHING HIDES UNDER THE APP'S OWN BARS. On a phone the application's tab bar may sit on the
  bottom edge. A bar the page fixes to the bottom (a sticky primary action) sits above it —
  `bottom-[var(--app-bottom-inset,0px)]`, never `bottom-0` — and the page leaves that room under
  its last row.
- RECORD PAGES TELL THE STORY. Title with its status badge, key facts in a
  definition grid, the related records (notes, activity) as a timeline or table,
  and the actions available in the record's current state — nothing that cannot
  run now.
- FORMS ARE CALM. WorkflowForm with a sensible field order, the right `kind` per
  field, help text where a rule is not obvious, two columns on wide screens.
- RESPONSIVE. Mobile first: stack below `md`, grids above. Nothing overflows at
  375px; wide tables scroll horizontally inside their card.
- ACCESSIBLE. Real <button>/<a>, labels on inputs, aria-label on icon-only buttons,
  visible focus (`focus-visible:ring-2 ring-ring` on anything you build yourself),
  sufficient contrast (use the tokens). A button that picks one of several options
  (a segmented choice, a filter chip, a tab) says which is picked: `aria-pressed`
  on the picked one, or `role="tab"` with `aria-selected`.
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
  THE PAGE IS YOURS TO BUILD. It is plain React and Tailwind: write the markup the design
  wants — your own cards, rows, tiles, panels, chips, grids, drawers — with the app's token
  classes. Nothing obliges you to use a ready-made component; a page assembled from a kit is
  the page every other app has. Reach for the kit or the library below when one of its parts
  is exactly right (a dialog, a select, a chart), and write it yourself when it is not.
  Imports that resolve in this application:
    react, next/link, next/navigation (useRouter, useSearchParams, usePathname),
    lucide-react (icons), clsx, tailwind-merge, class-variance-authority, sonner (toast),
    the @radix-ui primitives the kit is built on, the UI kit and the library below (optional),
    "@/sdk" (entity types, workflows, pages, widgets, href, fileUrl), "@/sdk/client" (useWorkflow,
    WorkflowForm, WorkflowButton, WidgetView, ImageSearch, NearMe, formatDistance, distanceKm),
    "@/sdk/camera" (CameraCapture, BarcodeScanner), "@/sdk/i18n" (useT, useLanguage, LanguageSwitch), and
    `import type { Page, SeriesPoint, QueryRow, WidgetData } from "@/sdk/server"`.
  Nothing else is installed; an import of any other package fails to compile.
  WHAT IS NOT YOURS TO REWRITE — these carry the wiring, and only they do:
    <SignInForm /> and <SignUpForm /> (sign-in and sign-up), <WorkflowForm /> and <WorkflowButton />
    (every change to data), <WidgetView /> and <Chart /> (every chart and metric — ECharts, themed),
    <ImageSearch /> and <NearMe /> (likeness and nearness), <CameraCapture /> and <BarcodeScanner />
    (the camera), and href(pages.x) for every link.
  - Links: <Link href={href(pages.someKey, { id: row.id })}> — never a hand-written path.
  - Changing data: only through a workflow — <WorkflowForm workflow={workflows.x} fields={…} />,
    <WorkflowButton workflow={workflows.x} input={{ … }} />, or useWorkflow(workflows.x).run(input).
    `fields` has one entry per workflow input, keyed by the input's name; an input the page
    already knows (the record's id, a fixed decision) is { value: … } and renders nothing.
    A CHANGE NO WORKFLOW MAKES IS NEVER SIMULATED. There is no delete, save or update
    function besides the workflows listed for this application; do not invent one, and do
    not fake one — removing a row from React state, a timer that "saves", a success toast
    over nothing. The row comes back on reload and the person has been told a lie. When a
    change the brief asks for is made by none of the listed workflows, leave its control
    out and name the change in `needs` (when the reply has it).
  - Search / filters: update the URL with router.push(href(pages.thisPage, params?, query)).
  - TypeScript strict: no `any`, no non-null assertions on data that can be null, handle
    null fields. Keep it one file; small local components are fine.
  - Browser storage (localStorage, sessionStorage) can be refused — a private window, an
    embedded frame, a blocked site. Touch it only inside try/catch, in an effect or an event
    handler, never while rendering; the page renders fully without it, on a default.
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


def bar(doc: dict) -> str:
    """What a page is held to: the products this application's design names
    (`designSystem.references`), each with what to take from it — or, before
    it names any, the best of its own field. Not one bar for every app: held
    to "Linear, Stripe, Notion, Vercel", a food menu and a fashion shop came
    out as developer dashboards (2026-10-02)."""
    refs = [r for r in ((doc.get("designSystem") or {}).get("references") or [])
            if isinstance(r, dict) and str(r.get("product") or "").strip()]
    if not refs:
        return "the best products in this application's own field, for the people who use it"
    return "the products this application's users hold it against — " + "; ".join(
        f"{r['product']} ({str(r.get('takeaway') or '').strip()})" if r.get("takeaway") else str(r["product"])
        for r in refs[:4])


def _language(doc: dict) -> str:
    """The application's language section, or nothing for one in English."""
    from services.blueprint.languages import page_rule
    rule = page_rule(doc)
    return f"# Its language\n{rule}\n\n" if rule else ""


def _look(doc: dict) -> str:
    """The design system as the page author uses it: the personality, each
    colour role with the class that draws it, and the two type faces."""
    design = doc.get("designSystem") or {}
    colors = design.get("colors") or {}
    typo = design.get("typography") or {}
    classes = {"background": "bg-background", "surface": "bg-card", "textPrimary": "text-foreground",
               "textSecondary": "text-muted-foreground", "primary": "bg-primary / text-primary",
               "accent": "bg-accent / variant=\"accent\"", "accentSubtle": "bg-accent-subtle",
               "inverse": "bg-inverse", "gradientStart": "from-gradient-start",
               "gradientEnd": "to-gradient-end"}
    from services.blueprint.verification import PALETTE_ROLES
    lines = [str(design.get("visualPersonality") or "")[:600]]
    for role, job in PALETTE_ROLES.items():
        value = colors.get(role)
        lines.append(f"- {classes[role]}{f' ({value})' if value else ''}: {job}")
    head = typo.get("fontFamilyHeading") or typo.get("fontFamilyDisplay") or typo.get("headingFontFamily")
    body = typo.get("fontFamilyBase") or typo.get("fontFamily") or typo.get("fontFamilyBody")
    if head or body:
        lines.append(f"- font-heading: {head or body}; body: {body or head}")
    gs, ge = colors.get("gradientStart"), colors.get("gradientEnd")
    lines.append("- bg-brand-gradient" + (f" ({gs} → {ge})" if gs and ge else " (primary → accent)")
                 + ": the brand gradient — the leading card, the sign-in panel, a hero band; its text is set")
    from services.blueprint.imagery import imagery_brief
    lines.append(imagery_brief(doc))
    return "\n".join(x for x in lines if x)


def system_prompt(doc: dict) -> str:
    """Identical for every page of one application — the cached prefix."""
    comp = doc.get("composition") or {}
    conventions = "\n".join(f"- {c.get('topic')}: {c.get('rule')}"
                            for c in comp.get("conventions") or []) or "- (none stated)"
    app = doc.get("application") or {}
    # "IT IS SHIPPED AS YOU WRITE IT" WAS NOT TRUE, AND IT COST A PAGE.
    # `compose_page` compiles every reply (tsc --strict, the wiring and design
    # checks) and hands the errors back for another round — but the page was
    # told the opposite, so it behaved accordingly: it resolved the whole
    # design before writing a character. On a page that IS the application —
    # forge-v3's Calculator, whose direction specifies numeric precision, a
    # memory row, AC-versus-C, error semantics and a 480px collapse — that
    # deliberation ran to 64,000 tokens with no code written, twice, and the
    # page shipped from its layout instead (2026-09-20).
    return f"""You are the UI engineer of {app.get('name') or 'this application'}: you write one page of a \
Next.js 15 (App Router, React 19, TypeScript strict, Tailwind) application, and you are held to the \
standard of {bar(doc)}. The page must be complete, beautiful and correct — and look like THIS product, \
not like every other generated application.

WRITE IT, THEN IMPROVE IT. Your reply is compiled the moment it arrives — TypeScript strict, plus \
checks that every control is wired and that the page follows the direction below — and anything wrong \
comes straight back to you with the errors, up to {COMPILE_ROUNDS} times. So begin writing early and \
keep going: a working page you refine beats a perfect one you never start. Deciding every detail before \
the first line is how a page runs out of room and arrives empty.

# The application
{app.get('name')}
{_about(doc)}

{_language(doc)}# Its direction — follow it on every page
{comp.get('vision') or '(no vision stated — choose a calm, professional, information-dense style)'}
{conventions}

# Its page rhythm — decided once for this application; every page keeps to it
{_rhythm(doc)}

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

# Ready-made parts — there if one fits, never required
A UI kit (shadcn, themed by the app's tokens). Use a part when it is exactly what the page needs;
otherwise write the element yourself in Tailwind — your own button, badge, table or panel is as
welcome as the kit's, and often better suited.
```ts
{_kit_exports()}
```
Button variants: default | secondary | outline | ghost | destructive | link; sizes: default | sm | lg | icon.
Badge variants: default | secondary | destructive | outline | success | warning | muted.
Icons: any lucide-react icon, e.g. `import {{ Plus, Search, Filter }} from "lucide-react"`.
Charts: the library's Chart (ECharts) — every chart the page draws goes through it (that one is
not optional: it is what themes and validates the palette).

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

# The component library — the same rule: a part when it fits, your own markup when not
```ts
{LIBRARY_PALETTE}
```

# Design
{DESIGN_PRINCIPLES}
Reply with the rationale and the full contents of both files."""


def _page_brief(doc: dict, page: dict) -> dict:
    from services.blueprint.page_usage import page_requirements
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
        # ADDING HAPPENS HERE (`addsHere`): no page of its own exists for a new
        # record, so this page carries the form — a panel over the list, or
        # the workspace opening empty — and runs the workflow that creates it.
        **({"addsHere": "New " + str((ents.get(str(data.get("primaryEntity"))) or {}).get("name") or "records")
            + " are added on this page: give it the form for one (a panel or drawer over the list, or "
            "this workspace opening empty) that runs the workflow below which creates it. There is "
            "no separate page to send anyone to."} if page.get("addsHere") else {}),
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
        # WHAT IT ANSWERS TO: the requirements of its module, of the processes
        # it launches and of the rules on its records (`page_usage`).
        **({"requirements": reqs} if (reqs := page_requirements(doc, page)) else {}),
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


def plan_prompt(doc: dict, page: dict, brief: str = "") -> str:
    """Ask for the decisions, not the code."""
    wanted = (f"\n\nWhat is wanted of it — this decides the layout:\n{brief}" if brief else "")
    return ("Decide how to build this page — do not write it yet.\n\n```json\n"
            + json.dumps(_page_brief(doc, page), indent=2) + "\n```" + wanted + "\n\n"
            "Answer with its state, its sections in order, and one line per behaviour the code must "
            "satisfy. Short lines. You will be asked for the code next, with this plan in front of you, "
            "so decide here and write there.")


def user_prompt(doc: dict, page: dict, *, feedback: str = "", brief: str = "",
                current: dict | None = None, plan: dict | None = None,
                relayout_of: dict | None = None) -> str:
    out = ["Write this page.\n\n```json\n" + json.dumps(_page_brief(doc, page), indent=2) + "\n```"]
    if plan:
        # THE DECIDING IS DONE. Handed the plan it made a moment ago, the
        # writer has little left to weigh — which is the point: the budget
        # below is for the page, not for making up its mind again.
        out.append("\nYour plan for it — follow it, and write the code now:\n```json\n"
                   + json.dumps(plan, indent=2) + "\n```")
    if brief:
        out.append(f"\nWhat is wanted of it now:\n{brief}")
    if current:
        out.append("\nIts current code:\n"
                   f"```ts\n// load.ts\n{current.get('load')}\n```\n```tsx\n// view.tsx\n{current.get('view')}\n```")
        out.append(
            "\nTHIS PAGE EXISTS — CHANGE IT WITH EDITS, NOT BY WRITING IT AGAIN. Reply with `edits`: "
            "each names the file (`load` or `view`), a `find` copied exactly from the current code "
            "above (whitespace included, long enough to occur once) and its `replace`. They apply "
            "in order. Touch only what this change needs; everything else stays as it is. Leave "
            "`load` and `view` empty — fill one with a file's full contents only when most of that "
            "file must change.")
    if relayout_of and not current:
        # LAID OUT AGAIN, NOT EDITED. "Rebuild every screen like Myntra" came
        # back as one page with its dock moved and its grid widened: a change
        # is made with edits, and edits keep the layout they are made in.
        out.append(
            "\nTHIS PAGE IS LAID OUT AGAIN FROM THE START, to what is wanted above and the "
            "application's direction — its structure, its sections, their order and their look are "
            "yours to decide afresh; do not keep the old arrangement because it was there. What it "
            "DOES stays: the data it shows and every action it offers (each button, form, link and "
            "workflow below is kept, working). The page as it is now, for what it does only:\n"
            f"```ts\n// load.ts\n{relayout_of.get('load')}\n```\n```tsx\n// view.tsx\n{relayout_of.get('view')}\n```")
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
            try:
                unchanged = dst.exists() and dst.read_text(encoding="utf-8") == f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                unchanged = False
            if not unchanged:
                shutil.copyfile(f, dst)
        # The fixed half imports scaffold files a newer scaffold ships
        # (`./auth` → `@/lib/account`); an older tree gets the defaults it lacks.
        from services.blueprint.assembly import fill_scaffold_defaults
        fill_scaffold_defaults(app_root)
        # What `@/sdk/i18n` reads: the interface's languages.
        from services.blueprint.languages import project_languages
        project_languages(doc, app_root)
        project_app_sdk(doc, app_root)


#: SDK modules built on a package the scaffold did not always carry: a page
#: that imports one needs it in the tree it compiles and runs in.
SDK_PACKAGES: dict[str, tuple[str, ...]] = {"@/sdk/camera": ("@zxing/browser", "@zxing/library")}


def ensure_sdk_packages(app_root: Path, view: str) -> list[str]:
    """A page that imports an SDK module built on a package gets that package:
    listed in the app's package.json (what a publish installs) and installed in
    the tree when it is missing. Apps built before the camera had neither, and
    an import that does not resolve fails the whole build. Returns what it added."""
    need = [p for mod, pkgs in SDK_PACKAGES.items() if f'"{mod}"' in view or f"'{mod}'" in view for p in pkgs]
    if not need:
        return []
    versions = json.loads((_SDK_TEMPLATE.parents[1] / "package.json").read_text(encoding="utf-8"))["dependencies"]
    with _SDK_LOCK:
        pj = app_root / "package.json"
        data = json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else {}
        deps = data.setdefault("dependencies", {})
        added = [p for p in need if p not in deps]
        if added:
            deps.update({p: versions[p] for p in added})
            pj.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        modules = app_root / "node_modules"
        missing = [p for p in need if not (modules / p / "package.json").exists()]
        if missing and modules.is_dir():
            _install_beside(modules, [f"{p}@{versions[p]}" for p in missing])
        return added


def _install_beside(modules: Path, specs: list[str]) -> None:
    """Install into a scratch folder and copy in only the packages the tree
    lacks. `npm install` in the app itself reifies the WHOLE tree: on a local
    copy whose node_modules links into another app's, a failed run left both
    with packages renamed away (@swc/helpers, @babel/runtime) and every page 500."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="forge-sdk-pkg-") as tmp:
        (Path(tmp) / "package.json").write_text('{"name": "sdk-packages", "private": true}', encoding="utf-8")
        proc = subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--no-package-lock", *specs],
                              cwd=tmp, capture_output=True, text=True, timeout=300)
        if proc.returncode:
            logger.warning("installing %s failed: %s", specs, proc.stderr[-500:])
            return
        got = Path(tmp) / "node_modules"
        for pkg in got.glob("*/package.json"):
            _copy_package(pkg.parent, modules / pkg.parent.name)
        for pkg in got.glob("@*/*/package.json"):
            _copy_package(pkg.parent, modules / pkg.parent.parent.name / pkg.parent.name)


def _copy_package(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        return  # the tree's own copy wins
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, symlinks=True)


class CompileError(RuntimeError):
    """The page's code did not type-check; the message is the compiler's."""


def typecheck(doc: dict, app_root: Path, page_id: str, load: str, view: str,
              timeout: float = 180.0) -> list[str]:
    """Compile one page — its route module, load and view — against the SDK.

    Only errors in the page's own three files count: the scaffold's modules
    are built with type errors ignored and carry some, and a page is not the
    place they are fixed. Returns the errors, empty when it compiles."""
    # npm links every `.bin` entry as `tsc` (a `#!/usr/bin/env node` shebang
    # script), `tsc.cmd` and `tsc.ps1`, on every platform — never only one.
    # `subprocess.run([app_root/"node_modules/.bin/tsc", ...])` executed the
    # shebang script directly on Windows, which has no shebang interpreter:
    # `OSError: [WinError 193] %1 is not a valid Win32 application`. Asking
    # `shutil.which` for the name (not the shebang file) resolves the right
    # one per platform — `tsc.cmd` here, plain `tsc` on POSIX.
    tsc_path = shutil.which("tsc", path=str(app_root / "node_modules" / ".bin"))
    if not tsc_path:
        raise RuntimeError(f"no TypeScript compiler under {app_root} — install has not run")
    tsc = Path(tsc_path)
    ensure_sdk(doc, app_root)
    ensure_sdk_packages(app_root, view)
    files = code_page_files(doc, {"page": page_id, "load": load, "view": view})
    if not files:
        return [f"{page_id} is not a live page"]
    check = app_root / ".forge-check" / f"{page_id}-{os.getpid()}-{threading.get_ident()}"
    if check.exists():
        shutil.rmtree(check, ignore_errors=True)
    check.mkdir(parents=True)
    try:
        for rel, content in files.items():
            (check / Path(rel).name).write_text(content, encoding="utf-8")
        (check / "tsconfig.json").write_text(json.dumps({
            "extends": "../../tsconfig.json",
            "compilerOptions": {"incremental": False, "noEmit": True},
            "include": ["page.tsx", "load.ts", "view.tsx", "../../next-env.d.ts",
                        "../../src/types/**/*.d.ts"],
        }))
        proc = subprocess.run([str(tsc), "-p", str(check / "tsconfig.json"), "--pretty", "false"],
                              cwd=str(app_root), capture_output=True, text=True, encoding="utf-8", timeout=timeout)
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


def _unread_handoffs(doc: dict, page: dict, load: str, view: str) -> list[str]:
    """What another page hands this one in its address, that this one never
    reads. F&B's Place Order was opened with the basket in `?items=` and
    started empty (fxa532bj, 2026-10-02)."""
    from services.blueprint.functional_completeness import handoffs, reads_query

    pid = str(page.get("id"))
    names = {str(p.get("id")): str(p.get("route") or p.get("id")) for p in doc.get("pages") or []
             if isinstance(p, dict)}
    out = []
    for src, dst, key in handoffs(doc):
        if dst == pid and src != pid and not reads_query(load + "\n" + view, key):
            out.append(f"load.ts: {names.get(src, src)} opens this page with `?{key}=` — read "
                       f"`ctx.searchParams.{key}` and start the page from it; what the person chose "
                       f"there must not be lost on arrival.")
    return out


#: A pause dressed as work: `await new Promise((r) => setTimeout(r, 300))`.
_TIMED_PRETENCE = re.compile(r"await\s+new\s+Promise\s*\([^)]*=>\s*setTimeout\s*\(")
#: A row taken out of the page's own copy of the records.
_STATE_REMOVAL = re.compile(r"\bset[A-Z]\w*\(\s*\(?\s*\w+\s*\)?\s*=>\s*\w+\.filter\(")
#: Something that actually reaches the records.
_REAL_WRITE = re.compile(r"\brun\(|\bworkflows\.\w+|\.mutate(?:Async)?\(")


def _function_bodies(src: str) -> list[str]:
    """The body of each `=> {` / `function … {` in `src`, by brace matching."""
    bodies = []
    for m in re.finditer(r"=>\s*\{|\bfunction\b[^{(]*\([^)]*\)[^{]*\{", src):
        depth, i = 1, m.end()
        while i < len(src) and depth:
            depth += {"{": 1, "}": -1}.get(src[i], 0)
            i += 1
        bodies.append(src[m.end():i - 1])
    return bodies


def _simulated_writes(view: str) -> list[str]:
    """A change to records the page only pretends to make.

    Test 5's Delete (2026-09-28) waited 300ms and filtered the row out of
    React state; it compiled, the reviewer scored it 8/10, and the person
    watched it come back on every reload. Only a workflow reaches the records,
    so a handler that removes a row or waits on a timer without running one is
    refused, with the way out: say the change is needed."""
    out = []
    for body in _function_bodies(view):
        if _REAL_WRITE.search(body):
            continue
        if _TIMED_PRETENCE.search(body) or _STATE_REMOVAL.search(body):
            out.append("view.tsx: a handler removes a row from the page's state or waits on a timer "
                       "without running a workflow — the records do not change and the row comes "
                       "back on reload. Run the workflow that makes this change; when none of the "
                       "application's workflows does, leave the control out and name the change "
                       "in `needs`.")
            break
    return out


#: A button or form, its attributes read through `{…}` so an `=>` inside one
#: does not end the tag.
_CONTROL = re.compile(r"<(Button|WorkflowButton|WorkflowForm)\b((?:[^>{]|\{(?:[^{}]|\{[^{}]*\})*\})*)>(.*?)</\1>",
                      re.S)
#: Words that say a control is to go or to be renamed.
_TAKE_AWAY = re.compile(r"\b(remove|hide|drop|get rid of|take (?:it )?(?:off|away|out)|without|rename|relabel|"
                        r"call it|instead of|replace)\b", re.I)


def _control_labels(view: str) -> list[str]:
    """What each button and form in a view says — its literal text, the
    strings it switches between, a form's submit label."""
    labels: list[str] = []
    for m in _CONTROL.finditer(view):
        attrs, inner = m.group(2), m.group(3)
        texts = re.findall(r'"([^"{}<>]{2,80})"', inner)
        texts += [s.strip() for s in re.sub(r"\{[^{}]*\}|<[^>]*>", "\n", inner).split("\n")]
        for s in texts:
            s = s.strip()
            if len(s) >= 2 and re.search(r"\w", s) and s not in labels:
                labels.append(s)
    for s in re.findall(r'submitLabel="([^"]+)"', view):
        if s not in labels:
            labels.append(s)
    return labels


def _dropped_controls(before: str, after: str, brief: str) -> list[str]:
    """Controls the page had that the rewrite no longer has, when the brief
    did not ask for them to go.

    "It's not deleting from the table" came back as a page with no Delete
    button, reported as "Rewrote /register (version 27)" (Test 5,
    2026-09-28). A control disappears only when the ask says so — a word
    of the control's label beside a word for taking it away or renaming it."""
    asked = brief.lower()
    out = []
    for label in _control_labels(before):
        if label in after:
            continue
        stems = [w[:5] for w in re.findall(r"[a-z]{3,}", label.lower())]
        if _TAKE_AWAY.search(brief) and any(s in asked for s in stems):
            continue
        out.append(label)
    gone = sorted(set(re.findall(r"\bworkflows\.(\w+)", before)) - set(re.findall(r"\bworkflows\.(\w+)", after)))
    if gone and not _TAKE_AWAY.search(brief):
        out += [f"the control that runs workflows.{k}" for k in gone]
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
        out.append("load.ts/view.tsx: imports app internals — only @/sdk, @/sdk/server, @/sdk/client, @/sdk/camera, @/sdk/i18n.")
    # SIGNING IN IS THE SDK'S. F&B's sign-in page was rewritten to call
    # next-auth itself and send everyone to two fixed addresses, so a person
    # landed wherever the page guessed rather than on their role's own page
    # (fxa532bj, 2026-10-02). `SignInForm`/`useSignIn` and `SignUpForm`/
    # `useSignUp` land each role where the definition says.
    if re.search(r"""from\s+["']next-auth""", load + view):
        out.append("load.ts/view.tsx: imports next-auth — sign in and up through @/sdk/client "
                   "(SignInForm, useSignIn, SignUpForm, useSignUp); they send each role to its own page.")
    if re.search(r"lorem ipsum|coming soon", view, re.I) or re.search(r"\bTODO\b", view):
        out.append("view.tsx: placeholder copy.")
    # AN ESCAPE IN JSX TEXT IS PRINTED, NOT DECODED. SnapIT's redesigned home
    # read "app \\u2014 verified listings" (2026-10-01): JSX text and attribute
    # strings are not JavaScript strings, so `\u2014` reaches the screen as six
    # characters. Write the character itself (— · ₹), or {"\u2014"} in braces.
    if re.search(r">[^<{}]*\\u[0-9a-fA-F]{4}[^<{}]*<", view) or re.search(r'\s[a-zA-Z]+="[^"]*\\u[0-9a-fA-F]{4}', view):
        out.append("view.tsx: a `\\uXXXX` escape in JSX text or an attribute string is shown literally — "
                   "write the character itself.")
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


def _with(client: Any, **changes: Any) -> Any:
    """The same client, asked differently — or the same client, when it is
    not one of ours (a test's stub, a plain callable)."""
    import dataclasses

    if not dataclasses.is_dataclass(client) or not hasattr(client, "max_tokens"):
        return client
    return dataclasses.replace(client, **changes)


def _page_plan(doc: dict, page: dict, client: Any, system: str, spent: list[Any],
               brief: str = "") -> dict | None:
    """The page's decisions, in a budget that cannot swallow the page.

    A plan that fails is not a page that fails: the writer is asked as it
    always was, and the run carries on."""
    t0 = time.monotonic()
    try:
        # LOW EFFORT, BECAUSE DECIDING IS NOT THE HARD PART — measured: asked
        # for this same plan at `high` the model spent all 8,000 tokens
        # thinking and answered nothing (98s); at `low` it answered in 10-15s
        # with five sections and a dozen behaviours. Effort buys deliberation,
        # and deliberation is the thing that was already running away.
        reply = _with(client, max_tokens=PLAN_MAX_TOKENS, effort="low")(
            system=system, user=plan_prompt(doc, page, brief), schema=PAGE_PLAN_SCHEMA)
        if getattr(reply, "usage", None) is not None:
            spent.append((reply.usage, time.monotonic() - t0))
        plan = json.loads(getattr(reply, "text", reply))
        logger.info("[ui_engineer] %s planned in %.0fs: %d section(s), %d behaviour(s)",
                    page.get("id"), time.monotonic() - t0,
                    len(plan.get("sections") or []), len(plan.get("behaviours") or []))
        return plan
    except Exception as exc:  # noqa: BLE001 — a plan is a help, never a gate
        logger.warning("[ui_engineer] %s could not be planned (%s: %s); writing it unplanned",
                       page.get("id"), type(exc).__name__, str(exc)[:160])
        return None


def compose_page(doc: dict, page: dict, app_root: Path, client: Any, *,
                 feedback: str = "", brief: str = "", current: dict | None = None,
                 usage: Any = None, node: str = "page_code", critic: Any = None,
                 on_look: Any = None, relayout_of: dict | None = None) -> tuple[dict, list[Any]]:
    """Author one page and compile it, returning the accepted `pageCode` body
    and the usage of every call. Raises CompileError when the last round still
    does not compile — the message carries the errors for the next attempt.

    With a ``critic``, a page that compiles is LOOKED AT before it is accepted
    (`page_look`): rendered and judged, and sent back once with the review
    as its brief. The better-scoring version is returned; a look that cannot
    happen here accepts the page as the compiler did. The critic's calls are
    in `spent` as `(usage, elapsed, "page_reviewer")`."""
    from services.blueprint import page_look

    system = system_prompt(doc)
    spent: list[Any] = []
    note = feedback
    last_errors: list[str] = []
    looks_left = page_look.LOOKS if critic is not None else 0
    #: A page that already existed is being CHANGED: the reviewer checks the
    #: change did not break it, and sends it back only for that. Its taste
    #: notes are about the page as it was — sent back for a 7/10 the first
    #: time, a changed page was rewritten whole, scored 7/10 again and cost
    #: two minutes for nothing (live, 2026-09-28).
    changing = current is not None
    #: The page as it was before this change, to hold the rewrite to it — an
    #: edit's current code, or the page a whole re-layout replaces.
    original_view = str((current or relayout_of or {}).get("view") or "")
    #: What the reviewer is told was asked of the page, when it is changed.
    change = (brief or feedback or "").strip() if changing else ""
    #: The best version seen by the reviewer: (rank, body). Returned when a
    #: rewrite scores lower, fails to compile, or the rounds run out.
    best: tuple[tuple[int, int], dict] | None = None
    # DECIDE, THEN WRITE — in two calls, because one budget holds both and
    # the deciding will take all of it. Skipped on a repair (the decisions
    # were made and the code exists; what is wanted now is a fix).
    plan = None if (current or feedback) else _page_plan(doc, page, client, system, spent,
                                                         brief if relayout_of else "")
    # WITH THE DECIDING DONE, WRITING NEEDS LITTLE DELIBERATION AND NO ROOM
    # FOR IT. Measured on the page that failed four times: plan at `low` (15s),
    # then write at `low` in 24,000 — 64s, 12,655 characters. The same page
    # asked in one call at `high`/64,000 spent 758s, then 867s, and wrote
    # nothing at all. Without a plan the client is left as it was: that is the
    # old path, and it is what a repair round uses.
    writer = _with(client, effort=WRITE_EFFORT, max_tokens=WRITE_MAX_TOKENS) if plan else client
    # A look's rewrite has its own round: the compile rounds are for
    # compiling, and a page sent back by the reviewer on the last of them
    # would have nowhere to go.
    rounds = COMPILE_ROUNDS + (page_look.LOOKS - 1 if looks_left else 0)
    for round_ in range(1, rounds + 1):
        t0 = time.monotonic()
        editing = current is not None
        reply = writer(system=system, user=user_prompt(doc, page, feedback=note, brief=brief,
                                                       current=current, plan=plan,
                                                       relayout_of=relayout_of),
                       schema=PAGE_EDIT_SCHEMA if editing else PAGE_CODE_SCHEMA)
        text = getattr(reply, "text", reply)
        if getattr(reply, "usage", None) is not None:
            spent.append((reply.usage, time.monotonic() - t0))
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            note = f"Your reply was not valid JSON ({exc}). Return the object only."
            continue
        load, view = str(body.get("load") or ""), str(body.get("view") or "")
        emitted = len(load) + len(view)
        if editing and [n for n in body.get("needs") or [] if str(n).strip()]:
            # NOTHING IS WRITTEN AROUND A MISSING WORKFLOW. The writer says
            # what the change needs; the caller adds it and asks again.
            raise NeedsWorkflow(list(body.get("needs") or []))
        if editing:
            # A file left empty keeps its current contents; the edits apply
            # to whatever each file then is.
            base = {"load": load or str(current.get("load") or ""),
                    "view": view or str(current.get("view") or "")}
            edits = [e for e in body.get("edits") or [] if isinstance(e, dict)]
            emitted += sum(len(str(e.get("find") or "")) + len(str(e.get("replace") or "")) for e in edits)
            try:
                files = apply_edits(base, edits)
            except EditsDidNotApply as exc:
                note = ("Nothing was applied — these edits did not match the current code exactly:\n"
                        f"{exc}\nThe current code is unchanged; quote from it exactly.")
                logger.warning("[ui_engineer] %s round %d: edits did not apply: %s",
                               page.get("id"), round_, str(exc)[:300])
                continue
            load, view = files["load"], files["view"]
        view = _use_client_first(view)
        design = _design_findings(doc, page, view)
        errors = (_static_findings(load, view) + _simulated_writes(view) + _unwired_actions(doc, page, view)
                  + _unread_handoffs(doc, page, load, view)
                  + typecheck(doc, app_root, str(page.get("id")), load, view))
        if original_view:
            dropped = _dropped_controls(original_view, view, change or brief)
            if dropped:
                errors.append("view.tsx: the rewrite took away what the page had and the ask did not "
                              "say to remove: " + "; ".join(f"`{d}`" for d in dropped[:6]) + " — keep "
                              "them; if one cannot work as asked, keep it and name the change in `needs`.")
        # THE STYLE RULES ASK AGAIN; THEY NEVER COST A PAGE. A page that
        # compiles and runs is kept on the last round whatever its design
        # findings — losing the page is worse than an unaccented button.
        if design and not errors and round_ >= COMPILE_ROUNDS:
            logger.warning("[ui_engineer] %s accepted with design findings: %s",
                           page.get("id"), "; ".join(design)[:400])
        else:
            errors += design
        if not errors:
            body = {"page": str(page.get("id")), "rationale": str(body.get("rationale") or ""),
                    "load": load, "view": view,
                    "requirements": list(page.get("requirements") or [])}
            if looks_left:
                # LOOK BEFORE ACCEPTING. Rendered with sample data and judged
                # on the screenshots; a `revise` is one more round with the
                # review as the brief. The reviewer's rank decides between
                # the versions it saw — a rewrite is not always better.
                looks_left -= 1
                try:
                    verdict, cost = page_look.look_at(doc, page, Path(app_root), load, view, critic,
                                                      attempt=page_look.LOOKS - looks_left,
                                                      change=change)
                except page_look.LookUnavailable as exc:
                    logger.info("[ui_engineer] %s not looked at (%s); accepted as compiled", page.get("id"), exc)
                    looks_left = 0
                else:
                    if cost[0] is not None:
                        spent.append((cost[0], cost[1], "page_reviewer"))
                    if on_look is not None:
                        try:
                            on_look(verdict)
                        except Exception:  # noqa: BLE001 — narration never fails a page
                            pass
                    seen = (page_look.rank(verdict), body)
                    if best is None or seen[0] > best[0]:
                        best = seen
                    # A CHANGE GOES BACK FOR WHAT IT CAUSED: something proved
                    # broken, or an issue the reviewer marks as the change's.
                    must_fix = (verdict.get("verdict") != "pass" and not changing) or (
                        changing and bool(verdict.get("broken") or page_look.caused_by_change(verdict)))
                    if must_fix and looks_left and round_ < rounds:
                        # THE REVIEW IS A REFUSAL, NOT A WISH. Handed as the
                        # brief ("what is wanted of it now") the first trial's
                        # rewrite of a list page changed one border and kept
                        # every issue; as feedback it is what the writer is
                        # told to fix, every one, keeping what worked.
                        current = {"load": load, "view": view}
                        note = page_look.look_brief(verdict, change_only=changing)
                        logger.info("[ui_engineer] %s sent back by the reviewer (%s/10)",
                                    page.get("id"), verdict.get("score"))
                        continue
                    body = best[1]
            # WHAT IT COST, WHERE SOMEBODY CAN COUNT IT. This node is the
            # longest in a build — 343s of a 616s run on a ONE-PAGE
            # calculator — and nothing recorded whether that was one round or
            # three. The run ledger says `ok: true` and a duration; the usage
            # ledger had no row for it at all. So the only honest answer to
            # "why is it slow" was to guess, and neither COMPILE_ROUNDS nor
            # the 36k-character system prompt can be tuned on a guess.
            #
            # The loop already knows: one entry in `spent` per model call.
            logger.info("[ui_engineer] %s composed in %d round(s), %d chars emitted "
                        "(page now load %d + view %d)",
                        page.get("id"), round_, emitted, len(body["load"]), len(body["view"]))
            return body, spent
        last_errors = errors
        current = {"load": load, "view": view}
        note = ("The TypeScript compiler (strict) and the page rules refused it:\n"
                + "\n".join(f"- {e}" for e in errors[:40]))
        logger.warning("[ui_engineer] %s round %d: %d error(s): %s", page.get("id"), round_,
                       len(errors), "; ".join(errors[:3])[:400])
    if best is not None:
        # The rewrite the reviewer asked for did not compile; the version it
        # judged did. A look never loses a page.
        logger.info("[ui_engineer] %s keeps the version the reviewer saw", page.get("id"))
        return best[1], spent
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
              "thirty pages written separately read as one product, as good as "
              f"{bar(doc)}. Be concrete: a page author must be able to follow each rule "
              "without guessing. Rules are about layout, hierarchy, density, tone of copy, how "
              "status and money read, empty/loading/error states, where actions live, and how "
              "lists, records and forms are built — never about colours by hex (the design "
              "system owns the palette).")
    pages = [{k: p.get(k) for k in ("name", "route", "pattern", "purpose")}
             for p in doc.get("pages") or [] if p.get("status") != "DEPRECATED"]
    roles = [r.get("name") for r in doc.get("roles") or []]
    user = (f"The application: {app.get('name')}\n{str(app.get('description') or '')[:2000]}\n\n"
            f"Who uses it: {', '.join(r for r in roles if r) or 'staff'}\n\n"
            # THE DESIGN AS IT IS NAMED. This read `density` and `personality`,
            # which the design system has never had (`informationDensity`,
            # `visualPersonality`): the director saw the fonts and the radius
            # and nothing of what the product is like (2026-10-02).
            f"Its design system (personality, density, frame, type, radius):\n"
            f"{json.dumps({k: ds.get(k) for k in ('visualPersonality', 'informationDensity', 'shell', 'navigationApproach', 'typography', 'radius') if ds.get(k)}, indent=1)[:3000]}\n\n"
            + _references_brief(ds) +
            f"Its pages:\n{json.dumps(pages, indent=1)[:12000]}\n\n"
            "Return `vision` — one paragraph a page author reads before every page — and "
            "8 to 14 `conventions`, each a topic and a precise rule.\n\n"
            "CHARTS GO WHERE THE ANALYTICS PUTS THEM. The application's analytics "
            "attaches KPIs and charts to the pages its staff work in — their "
            "dashboards and lists of records — and those pages must show "
            "them. A convention may say HOW a chart or tile sits on a page (its size, "
            "its place, whether it gets a heading); it never reserves charts or tiles "
            "to the dashboard. A reading list's direction said \"tiles and charts are "
            "for the dashboard only\", the list page drew the chart its analytics "
            "required, and was marked down for it (2026-09-27).\n\n"
            "AND THE PAGE RHYTHM — five anatomy decisions, made once, that every page then "
            "shares and that make this product's pages differ from another's. Choose each "
            "from its personality, its density and how it is used, not by habit:\n"
            + "\n".join(f"- `{key}`: " + "; ".join(f"`{o}` ({what})" for o, what in opts.items())
                        for key, opts in RHYTHM_OPTIONS.items())
            + "\nA product read all day at a desk wants a compact header, figures in a strip "
            "and dense sections; a consumer product wants a band, cards and open sections; a "
            "quiet tool wants a title alone and rows. Make the vision agree with what you chose.")
    return system, user


def _references_brief(ds: dict) -> str:
    """What to take from the products this one is held to, for the director:
    the layouts they are known for, adapted — not a style word."""
    refs = [r for r in ds.get("references") or [] if isinstance(r, dict) and r.get("product")]
    if not refs:
        return ""
    return ("THE PRODUCTS IT IS HELD TO, and what to take from each:\n"
            + "\n".join(f"- {r['product']}: {r.get('takeaway') or ''}" for r in refs[:4])
            + "\nTake the LAYOUT patterns these are known for and adapt them to this product: what a "
            "person sees first on each kind of page, how the main record is presented (photo-led "
            "cards, rows, a timeline, a map), where the main action lives, how the person moves "
            "between pages. Write those into the vision, the conventions and the rhythm — this is "
            "what makes the product look like its own field rather than like every other "
            "generated application.\n\n")


def compose_direction(doc: dict, client: Any, *, references: Sequence[Path] = ()) -> tuple[dict, Any]:
    """The director's decision — shown the user's reference images when
    there are any, read for the feel (`references.READ_FOR["ui_direction"]`)."""
    from services.blueprint.references import READ_FOR

    system, user = direction_prompts(doc)
    shown = [str(p) for p in references] if getattr(client, "accepts_images", False) else []
    if shown:
        user += (f"\n\nThe {len(shown)} image(s) attached are what the user showed to convey what "
                 f"they mean. {READ_FOR['ui_direction']}")
        reply = client(system=system, user=user, schema=DIRECTION_SCHEMA, images=shown)
    else:
        reply = client(system=system, user=user, schema=DIRECTION_SCHEMA)
    body = json.loads(getattr(reply, "text", reply))
    rhythm = body.get("rhythm") if isinstance(body.get("rhythm"), dict) else {}
    rhythm = {k: str(v) for k, v in rhythm.items() if k in RHYTHM_OPTIONS and str(v) in RHYTHM_OPTIONS[k]}
    return ({"vision": str(body.get("vision") or ""),
             "conventions": [{"topic": str(c.get("topic")), "rule": str(c.get("rule"))}
                             for c in body.get("conventions") or []],
             **({"rhythm": rhythm} if len(rhythm) == len(RHYTHM_OPTIONS) else {})},
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
            for u, elapsed, *_ in spent:
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
