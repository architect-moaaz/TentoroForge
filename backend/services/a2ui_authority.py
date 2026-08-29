"""A2UI-over-MCP as the page-composition authority, behind ``FORGE_A2UI``.

What this is
------------
Forge's dashboard today is decided by ``dashboard_maquette`` (an LLM that reads
the plan and names the KPIs, the chart and the activity feed) and rendered by
``apply_dashboard_maquette``. This module offers a second composer for the same
slot: hand the requirement to an A2UI server over MCP, get back a declarative
surface, and translate it into a Forge page (``a2ui_to_forge.translate``).

The reason to bother is not that an LLM composes the page — one already does.
It is that A2UI composes against a **closed catalog generated from Forge's own
Zod contracts**, validates each component against that catalog, and retries with
the errors fed back. Forge's composers have no such loop, which is why the
DRIFT-1..6 fixes exist: MetricTile shipped without ``format``, Chart without
``series``, Tag with ``content`` instead of ``label``. Each was a component and
a composer holding plausible, disagreeing contracts with nothing checking.

Two writers, one decides
------------------------
Adding a composer to a slot that already has one is exactly the failure the
dashboard single-writer fix just removed, so the handoff here is explicit and
one-directional: **A2UI ships only if the page it produces clears the substance
floor** (``dashboard_anatomy.dashboard_findings``, the gate built for this).
Anything else — MCP unreachable, invalid payload, unresolved bindings, a page
with no chart — and this returns ``applied: False`` having written nothing, so
the maquette composer runs untouched immediately after.

That means the flag can be turned on without a rollback plan: the worst case is
the composition is thrown away and the existing path runs, which is what would
have happened anyway.

The subtractive step matters
----------------------------
An A2UI payload carries an invented ``updateDataModel`` — 142 tasks, a "Follow
up with client" row. ``translate`` reads it for shape and discards the values.
A page that imported them would look finished, be fiction, and pass every
structural gate in the pipeline, because structurally it would be perfect.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# The A2UI checkout carrying the MCP server. Sibling of this repo by default;
# the flag is useless without it, which `availability()` reports rather than
# discovering halfway through a build.
A2UI_REPO = os.environ.get(
    "A2UI_REPO", "/Users/m/Work/code/poc/desgin2ui-forge-a2ui"
)
# NOT a constant. The catalog file names itself, the server validates the id
# against what it discovered on disk, and hardcoding a second copy here is the
# same two-places-hold-a-contract failure the catalog exists to prevent — it
# cost a live run to find ("tentoro.com" vs "tentoroforge.local").

# The composer is a network round trip with up to three validate-and-retry
# attempts inside it, each generating a whole surface. Measured live at ~4
# minutes for a first-attempt success, so 240s cut a working composition off
# mid-flight. A ceiling, not a target — post-gen runs inside a build someone
# is watching, and the fallback costs nothing.
DEFAULT_TIMEOUT = int(os.environ.get("FORGE_A2UI_TIMEOUT", "600"))

SurfaceProvider = Callable[[str, str], dict]

# What each kind of screen is FOR, in the words the composer needs to make its
# own call. Deliberately a job statement and not a parts list — see
# `build_requirement` for why the maquette stopped being sent.
_JOB = {
    "dashboard": (
        "This is the first screen someone sees after signing in. Decide what "
        "belongs on it: which numbers matter in this domain, what breakdown is "
        "worth charting, what a person needs to see happened recently, and what "
        "they are most likely to want to do next. Use the composition your "
        "judgement of the domain calls for — you are not filling in a template."
    ),
    "collection": (
        # NAMES NO COMPONENTS, DELIBERATELY. The A2UI server scans this text
        # for capability keywords and makes any match mandatory
        # (tools/a2ui-mcp/checks.py, _CAPABILITIES) — chart, kpi, metric,
        # stats, pill, badge, chip, table, data grid, timeline, gantt, kanban,
        # swimlane. A component named as an *example* reads as a demand.
        #
        # "a table, a board, a calendar, a timeline" offered four ways to think
        # about a list; the checker read two demands, so every collection page
        # had to carry a Table and a Timeline or be rejected. That is where the
        # Timeline on a two-entity plant tracker came from, and a table
        # demanded on a create form. Naming shapes rather than components says
        # the same thing to a reader and nothing to the scanner.
        "This screen shows many records of one kind. Decide how they are best "
        "surveyed in this domain: rows of fields, cards on a board, positions "
        "on a calendar, points along a sequence. Choose the shape the data "
        "actually has — which fields or facets help someone find what they "
        "came for, how they narrow the set down, and what they do to a record "
        "once they have found it. A list nobody can act on is a reading dead "
        "end."
    ),
    "record": (
        "This screen shows ONE record in detail. Decide what a reader needs to "
        "understand about it at a glance, what supporting detail belongs "
        "alongside, what related records matter here, and — most importantly — "
        "what they can DO with it: the actions that move this record forward in "
        "the domain, not just a way back."
    ),
    "form": (
        "This screen collects or edits ONE record. Decide which fields a person "
        "actually has to supply, how they group into a sequence someone can "
        "work through, and what the submit does. Field names must be real "
        "columns of the entity — anything else is dropped."
    ),
}


#: Blueprint page patterns, in the four shapes _JOB describes. page_family
#: knows the old pipeline's kinds and returns None for every one of these
#: except `form`, so a create screen was asked to "decide which numbers matter
#: and what breakdown is worth charting" — the dashboard job, sent verbatim to
#: /recipes/new. Falling back to dashboard is right for an unknown kind and
#: wrong for a known one nobody mapped.
_PATTERN_FAMILY = {
    "dashboard": "dashboard",
    "entity_list": "collection",
    "approval_inbox": "collection",
    "record_workspace": "record",
    "master_detail": "record",
    "form": "form",
    "wizard": "form",
}


def _family_of(kind: Any) -> str:
    """Every declared kind reduced to one of the four shapes above."""
    from services.page_kind_anatomy import page_family
    fam = page_family(kind)
    if fam:
        return fam
    return _PATTERN_FAMILY.get(str(kind or "").strip().lower(), "dashboard")


def is_a2ui_enabled() -> bool:
    """Always. §34: "The Page Design Agent shall use A2UI MCP as its primary
    page-generation capability."

    This was off unless FORGE_A2UI was set, for an A/B that has since been
    decided by the PRD. A flag gating the specified default is the divergence,
    not the default.

    What is NOT a flag, and stays: `availability()` reports a missing checkout
    up front, and a composition that does not clear its substance floor returns
    `applied: False` having written nothing, so the deterministic composer runs
    untouched. That is a handoff, and it is what keeps an unreachable MCP
    server from taking down a build.

    Kept as a function rather than deleted: three call sites read it, and a
    later decision to gate on something real — a per-project setting, a page
    kind — has somewhere to live.
    """
    return True


def availability() -> tuple[bool, str]:
    """Can the MCP composer actually run here? Reported up front so a build
    does not spend its dashboard budget discovering a missing checkout."""
    server = Path(A2UI_REPO) / "tools" / "a2ui-mcp" / "server.py"
    if not server.is_file():
        return False, f"no A2UI MCP server at {server} (set A2UI_REPO)"
    try:
        import mcp  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "the `mcp` package is not installed in this environment"
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        return False, "ANTHROPIC_API_KEY is unset — the server cannot compose"
    return True, "ok"


# ------------------------------------------------------------------ registry

def registry_from_blueprint(doc: dict) -> dict:
    """The Blueprint's entities in the shape ``a2ui_to_forge`` reads.

    ``registry_for_binder`` adapts ``plan.json``, which is what the old
    pipeline resolved names against. The Blueprint pipeline has no plan file,
    so every page declined with "no entities in the plan — every binding would
    be a guess" and fell through to the authoring agent. The composer was
    right to refuse: a binder with no entities invents them.

    Not a second source of truth, which is what that docstring warns against —
    the same adapter, over the source this pipeline actually has. §115: the
    Blueprint is what the application is.
    """
    out: dict[str, Any] = {}
    for ent in (doc.get("data") or {}).get("entities") or []:
        name = ent.get("name") or ent.get("id")
        if not name:
            continue
        cols = []
        for f in ent.get("fields") or []:
            if not isinstance(f, dict) or not f.get("name"):
                continue
            col: dict[str, Any] = {"name": f["name"],
                                   "type": f.get("type") or "varchar"}
            if f.get("enumValues"):
                col["enum"] = list(f["enumValues"])
            cols.append(col)
        out[name] = {"slug": ent.get("table") or str(name).lower(),
                     "columns": cols}
    return {
        "entities": out,
        # Identity, not just a label. The generated route is
        # `/api/workflows/{id}/execute` (api_derivation._workflow_path), so the
        # id is what a Button or a Form has to carry; a name reaches nothing.
        # `launchedFrom` is the workflow agent's own declaration of which pages
        # start it, which is what scopes this list per page.
        "workflows": [
            {"id": w.get("id"), "name": w.get("name"),
             "purpose": w.get("purpose") or "",
             "trigger": (w.get("trigger") or {}).get("kind") or "",
             "launchedFrom": list(w.get("launchedFrom") or [])}
            for w in doc.get("workflows") or [] if w.get("id")
        ],
    }


def registry_for_binder(root: Path) -> dict:
    """The plan's entities in the shape ``a2ui_to_forge`` reads.

    Deliberately an adapter over ``plan.json`` rather than a new reader: the
    plan is what every other generator resolves names against, and a second
    source of entity truth here would reintroduce the drift this whole effort
    is closing.
    """
    plan_p = root / "src" / "contracts" / "plan.json"
    if not plan_p.is_file():
        return {"entities": {}}
    try:
        plan = json.loads(plan_p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[a2ui] unreadable plan: %s", exc)
        return {"entities": {}}

    out: dict[str, Any] = {}
    for name, ent in (plan.get("entities") or {}).items():
        if not isinstance(ent, dict):
            continue
        cols = []
        for f in ent.get("fields") or []:
            if not isinstance(f, dict) or not f.get("name"):
                continue
            sem = f.get("semantic") if isinstance(f.get("semantic"), dict) else {}
            enum = f.get("enum_values") or sem.get("enum_values") or []
            col: dict[str, Any] = {"name": f["name"], "type": f.get("type") or "varchar"}
            if enum:
                col["enum"] = list(enum)
            cols.append(col)
        out[name] = {"slug": ent.get("table") or name.lower(), "columns": cols}

    # Workflow names, so the binder can tell a real submit target from an
    # invented one. Read from the same plan, for the same reason as the
    # entities: a second source of truth here is how names start to drift.
    flows: list[dict] = []
    for w in plan.get("workflows") or []:
        nm = w.get("name") if isinstance(w, dict) else w
        if not nm:
            continue
        wid = w.get("id") if isinstance(w, dict) else None
        # The plan predates workflow ids; falling back to the name keeps this
        # path validating exactly what it validated before.
        flows.append({"id": str(wid or nm), "name": str(nm),
                      "purpose": "", "trigger": "manual", "launchedFrom": []})

    return {"entities": out, "workflows": flows}


def build_requirement(root: Path, kind: str = "dashboard",
                      route: str = "/", shared_context: str = "") -> str:
    # `shared_context` is accepted and ignored — it belongs to
    # `build_domain_context` now. See the note there; in short, this string is
    # the one the A2UI server scans for feature keywords, and a design system
    # pasted into it reads as a list of demands.
    """What to ask for — a JOB, not a parts list.

    This used to hand over the maquette with "the content has already been
    decided — render exactly these", which made A2UI a renderer of Forge's
    decisions and nothing more. Measured on a real app, it obeyed: the four
    KPI labels, the chart, the activity feed and even the Kanban all came
    straight from the maquette's own ``signature_moves``. Everything the
    composition step is worth having — a second opinion about what this domain
    needs on a landing screen — was constrained away before the model saw it.

    So the maquette is no longer sent. The composer gets the domain, the real
    entities and columns, and the job. What it chooses to put on the screen is
    its own call; the binder's job is to make whatever it chose point at real
    data (see ``a2ui_to_forge``), not to check it against a list.
    """
    plan = _load_plan(root)
    app = (plan.get("app_name") or plan.get("name") or "this application")
    purpose = (plan.get("description") or plan.get("purpose")
               or plan.get("summary") or "")
    actors = [a.get("name") or a.get("role") for a in (plan.get("actors") or [])
              if isinstance(a, dict)]

    parts = [f"Compose the {route} screen of {app}.", "", _JOB[_family_of(kind)]]
    if purpose:
        parts.append(f"\nWHAT THE APPLICATION IS FOR:\n{purpose}")
    if actors:
        parts.append("\nWHO USES IT: " + ", ".join(str(a) for a in actors if a))
    guidance = build_composition_guidance(root, _family_of(kind))
    if guidance:
        parts.append("\n" + guidance)
    parts.append(
        # "a trend" cost every page an attempt and a chart it did not need.
        # The A2UI server reads the requirement for words that name a chart —
        # chart, graph, trend, plot, over time — and rejects any payload
        # without one (tools/a2ui-mcp/checks.py, _CAPABILITIES). The sentence
        # forbidding invented trends was itself read as asking for a trend, so
        # a two-entity plant tracker got a bar chart on all three pages,
        # including its create form. "proportion" says the same thing and
        # names no component.
        "\nEvery number, row and category you show must come from the "
        "entities and columns listed in the domain context, and every action "
        "must name one of its workflows. Do not write a number, a proportion "
        "or a comparison as a literal — bind it, or leave it out. Do not give "
        "a control an action the domain context does not list. Inventing "
        "either produces a screen that looks finished and is false."
    )
    return "\n".join(parts)


def _load_plan(root: Path) -> dict:
    p = root / "src" / "contracts" / "plan.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[a2ui] unreadable plan: %s", exc)
        return {}


def build_composition_guidance(root: Path,
                               screen: str = "dashboard") -> str:
    """The montage's layout language for a dashboard — shape, not content.

    Every other composer in the pipeline gets this. ``ensure_composition_reference``
    runs first in the maquettes node precisely so the dashboard, collection and
    record authors all inherit one house style, and it is why the maquette wrote
    exactly five KPIs on the legislative build: the reference reads "dense — 5 KPIs
    above the fold". A2UI was composing without it, which made the two composers
    incomparable — one following a design reference, one working from the domain
    alone.

    This is NOT the maquette returning through a side door. The reference
    describes REGIONS and DENSITY: how much belongs on the screen and roughly
    where. It names no entity, no metric and no number, so passing it restores the
    shared design language without restoring the "render exactly these" constraint
    that reduced A2UI to a renderer.
    """
    # The montage describes three screen kinds. A form has no reference of its
    # own — it is a record page being written rather than read — so it borrows
    # the record's proportions rather than being handed a dashboard's density.
    screen = {"form": "record"}.get(screen, screen)

    p = root / "src" / "contracts" / "composition-reference.json"
    if not p.is_file():
        return ""
    try:
        ref = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[a2ui] unreadable composition reference: %s", exc)
        return ""

    dash = (ref.get("screens") or {}).get(screen)
    if not isinstance(dash, dict):
        return ""

    head = ("HOUSE LAYOUT for a dashboard in this product, read off the design "
            "reference every other screen in this app follows")
    if ref.get("source"):
        head += f" ({ref['source']})"
    lines = [head + ":"]
    for region in dash.get("regions") or []:
        lines.append(f"  - {region}")
    if dash.get("density"):
        lines.append("")
        lines.append(f"DENSITY: {dash['density']}")
    if dash.get("hero_kind"):
        lines.append(f"HERO: {dash['hero_kind']}")
    lines.append("")
    lines.append(
        "This describes SHAPE — how much belongs on the screen and roughly "
        "where. It names no metric, no entity and no number: what to actually "
        "show is still your call from the domain. Match its density and its "
        "sense of proportion, and depart from it where this domain genuinely "
        "needs something else."
    )
    return "\n".join(lines)


def build_domain_context(root: Path, registry: dict | None = None,
                         page_id: str = "", shared_context: str = "") -> str:
    """The entities, columns and workflows a composition may bind to.

    Came back empty for every Blueprint-pipeline page — it read plan.json
    through registry_for_binder, the same missing file that emptied the
    registry. A composer told to bind only what exists, and handed nothing,
    has nothing to bind.

    Then it listed entities and columns and nothing else, which is nouns with
    no verbs. A composed /plants came back with no button of any kind for an
    app whose description says marking a plant watered is the only action —
    correctly, on what it was given: the job asks for "what they do to a
    record", the closing rule says do not invent, and `Record Watering Today`
    was sitting in the registry one key over, unmentioned. A2UI knew the action
    existed (the page purpose says so in prose) and had no id to put in
    `Button.workflow`, so it left the button out.
    """
    reg = registry if registry is not None else registry_for_binder(root)
    lines = []
    for name, ent in (reg.get("entities") or {}).items():
        cols = ", ".join(
            c["name"] + (f" [{'|'.join(map(str, c['enum']))}]" if c.get("enum") else "")
            for c in ent.get("columns") or []
        )
        lines.append(f"- {name}: {cols}")
    flows = [w for w in (reg.get("workflows") or []) if isinstance(w, dict)]
    # Scoped by two fields the workflow agent already declares: which pages
    # launch it, and how it is triggered. `trigger.kind` is a required enum —
    # manual | event | schedule | condition — and only `manual` is something a
    # user starts. This app declares four workflows and all four name both
    # pages in `launchedFrom`; listing them unfiltered offers a button for
    # "Evaluate Plant Watering Status" (a derivation that runs on every read)
    # and one for "Seed Plant Catalogue" (database initialisation).
    mine = [w for w in flows
            if page_id and page_id in (w.get("launchedFrom") or [])
            and w.get("trigger") == "manual"]
    if not lines and not mine and not shared_context:
        return ""

    parts = []
    if lines:
        parts.append(
            "The application's real entities and columns. Every number and "
            "every row on this screen comes from these — do not invent "
            "fields:\n" + "\n".join(lines)
        )
    if shared_context:
        # THE DESIGN SYSTEM IS CONTEXT, NOT A REQUEST. This used to ride in
        # the requirement, which is the one string the A2UI server scans for
        # capability keywords (checks.coverage_findings, called on
        # `requirement` alone). A design system carries `typography`, and
        # `radius: {badge, pill}` — so every page was held to have asked for a
        # chart and a status pill, and every payload without them was
        # rejected. Whole-word matching fixed `graph` inside `typography`;
        # `badge` and `pill` are whole words and it could not.
        #
        # The fix is structural rather than another keyword: design tokens are
        # not feature requests, and the field that gets parsed as requests is
        # not where they belong. The model still sees all of it — the server
        # emits `DOMAIN CONTEXT:` as its own block (generator.py) — and §35's
        # reason for sending it is unchanged: navigation presentation and
        # density are properties of a set, not of one page.
        parts.append(
            "\nTHE REST OF THIS APPLICATION — compose this screen so it "
            "belongs beside them. Reuse a pattern already established rather "
            "than inventing a second one for the same job, and keep the "
            "density and the voice consistent with what is here:\n"
            + shared_context
        )
    if mine:
        parts.append(
            "\nThe workflows this screen launches. An action on this screen "
            "runs one of these and nothing else — put the id in `workflow` on "
            "the Button or Form that runs it:\n"
            + "\n".join(
                f"- {w['id']}: {w.get('name') or w['id']}"
                + (f" — {w['purpose']}" if w.get("purpose") else "")
                for w in mine
            )
        )
    return "\n".join(parts)


# ---------------------------------------------------------------- MCP client

def _unwrap_group(exc: BaseException) -> BaseException:
    """Peel anyio's TaskGroup wrappers down to the error that actually fired.

    ``str()`` of an ExceptionGroup is "unhandled errors in a TaskGroup
    (1 sub-exception)" — true, and useless. Worse, the groups NEST: peeling one
    level off a stdio-session failure hands back another group carrying the
    same unhelpful message, which reads exactly as though the unwrap never ran.
    That cost a live composition its diagnosis twice.

    So peel while there is exactly one child. A group holding several real
    errors keeps its shape — collapsing that to the first child would hide the
    rest — but it reports them, which the bare message never did.
    """
    for _ in range(10):
        subs = getattr(exc, "exceptions", None)
        if not subs:
            return exc
        if len(subs) == 1:
            exc = subs[0]
            continue
        joined = "; ".join(f"{type(e).__name__}: {e}" for e in subs)
        return RuntimeError(f"{len(subs)} concurrent failures — {joined}")
    return exc


def _mcp_surface(requirement: str, domain_context: str,
                 timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Call ``generate_a2ui_surface`` over stdio MCP. Raises on any failure —
    the caller turns that into a fallback, never a broken page."""
    from services.a2ui_catalog import write_a2ui_catalog

    # Regenerate the catalog into the server's search path on every call. A
    # stale catalog is the one way this composer can author against components
    # Forge no longer has, and it costs nothing to rule out.
    catalog_dir = Path(A2UI_REPO) / "specification" / "v0_9" / "catalogs" / "forge"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = write_a2ui_catalog(catalog_dir / "catalog.json")
    catalog_id = json.loads(catalog_path.read_text(encoding="utf-8"))["catalogId"]

    async def _go() -> dict:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        here = Path(A2UI_REPO) / "tools" / "a2ui-mcp"
        env = dict(os.environ)
        env["A2UI_REPO"] = A2UI_REPO
        params = StdioServerParameters(
            command=sys.executable, args=[str(here / "server.py")], env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                out = await s.call_tool("generate_a2ui_surface", {
                    "requirement": requirement,
                    "catalogId": catalog_id,
                    "domainContext": domain_context,
                })
                if out.isError:
                    text = getattr(out.content[0], "text", "") if out.content else ""
                    raise RuntimeError(f"a2ui server: {text[:400]}")
                for block in out.content:
                    text = getattr(block, "text", None)
                    if text:
                        return json.loads(text)
        raise RuntimeError("a2ui server returned no content")

    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["v"] = asyncio.run(asyncio.wait_for(_go(), timeout))
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            # anyio wraps everything the stdio session raises in an
            # ExceptionGroup, whose str() is "unhandled errors in a TaskGroup
            # (1 sub-exception)" — true, and useless. The sub-exception is the
            # one carrying the server's actual complaint.
            exc = _unwrap_group(exc)
            if isinstance(exc, asyncio.CancelledError):
                # str(CancelledError) is "", so the timeout reported itself as
                # "composition failed: " — true, unactionable, and easy to
                # misread as a server fault rather than a clock.
                exc = TimeoutError(
                    f"a2ui composition exceeded {timeout}s "
                    "(raise FORGE_A2UI_TIMEOUT)")
            box["e"] = exc

    # Own thread with its own loop: post-gen may or may not be running inside
    # one already, and `asyncio.run` inside a live loop raises.
    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout + 30)
    if t.is_alive():
        raise TimeoutError(f"a2ui composition exceeded {timeout}s")
    if "e" in box:
        raise box["e"]
    return box["v"]


# ------------------------------------------------------------------ compose

def _floor_findings(kind: str, route: str, schema: dict, registry: dict) -> list[dict]:
    """The substance floor for this page kind. One dispatch point, so the
    decline criterion can never drift from what the delivery gate reports."""
    from services.dashboard_anatomy import dashboard_findings
    from services.page_kind_anatomy import page_kind_findings

    from services.a2ui_to_forge import dangling_bindings

    if _family_of(kind) == "dashboard":
        findings = dashboard_findings(route, schema, registry)
    else:
        findings = page_kind_findings(kind, route, schema)

    # EVERY BINDING NEEDS A SOURCE BEHIND IT. A composed /plants shipped four
    # stat tiles reading {{plantstracked.value}}, {{overdue.value}},
    # {{duetoday.value}} and {{neverwatered.value}} against one declared
    # source, `plants` — A2UI invented a source per metric, the binder passed
    # names it had never seen straight through, and the page rendered four
    # blanks. Nothing else catches this: `unresolved` reports pointers the
    # binder could not bind, and these bound fine, to nothing.
    #
    # Named as `ref` so salvage treats it like any other bad widget: drop the
    # tiles that read phantom data and re-judge. A page missing four tiles is
    # a page; a page of four blanks reads as broken.
    findings += [{"rule": f"binding '{name}' has no declared data source",
                  "ref": name}
                 for name in dangling_bindings(schema)]
    return findings


def compose_page_via_a2ui(
    output_dir: str,
    route: str,
    kind: str,
    *,
    surface_provider: Optional[SurfaceProvider] = None,
    shared_context: str = "",
    page_id: str = "",
    registry: dict | None = None,
) -> dict[str, Any]:
    """Try to own one page. Writes nothing unless the result clears the floor
    for that page's kind.

    Returns ``{applied, reason, ...}``. ``applied: False`` is an ordinary
    outcome, not an error — the caller carries on to the deterministic
    composer that owns this route today.
    """
    root = Path(output_dir)

    if not is_a2ui_enabled():
        return {"applied": False, "route": route, "kind": kind,
                "reason": "A2UI composition is disabled"}
    if surface_provider is None:
        ok, why = availability()
        if not ok:
            return {"applied": False, "route": route, "kind": kind, "reason": why}
        surface_provider = _mcp_surface

    from services.a2ui_to_forge import translate

    # No schema file is required. This used to decline when
    # `_schema_path_for_route` found nothing, which made it a post-projection
    # composer: it could only improve a page `frontend` had already written.
    # §34 puts A2UI inside the Page Design Agent's own generation step, so it
    # has to compose before anything is projected — and at that point no file
    # exists by definition.
    target = _schema_path_for_route(root, route)

    # A caller that has the entities passes them; the plan.json
    # adapter remains for the pipeline that has a plan.
    registry = registry if registry is not None else registry_for_binder(root)
    if not registry.get("entities"):
        return {"applied": False, "route": route, "kind": kind,
                "reason": "no entities in the plan — every binding would be a guess"}

    try:
        payload = surface_provider(build_requirement(root, kind, route,
                                                     shared_context),
                                   build_domain_context(root, registry,
                                                        page_id,
                                                        shared_context))
    except Exception as exc:  # noqa: BLE001 — a composer must never fail a build
        logger.warning("[a2ui] %s composition failed: %s", route, exc)
        return {"applied": False, "route": route, "kind": kind,
                "reason": f"composition failed: {exc}"}

    # Keep the raw surface per route, decline or not. When a composition ships
    # something wrong the first question is always what the composer actually
    # said, and without this the only way to answer it is another LLM call.
    try:
        art = root / "src" / "contracts" / "a2ui-surfaces"
        art.mkdir(parents=True, exist_ok=True)
        (art / f"{_route_slug(route)}.json").write_text(
            json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — debug artifact, never a blocker
        logger.warning("[a2ui] could not persist the %s surface: %s", route, exc)

    # The caller knows the page id — `page_layouts` fans out over them. Read
    # from an existing schema only when improving one, and fall back to the
    # route slug when there is neither.
    if not page_id:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            page_id = str(existing.get("id") or _route_slug(route))
        except Exception:  # noqa: BLE001
            page_id = _route_slug(route)

    # `kind` reaches the binder: a dashboard's Selects and date pickers are
    # filter chrome, not form fields naming missing columns.
    result = translate(payload, registry, route=route, page_id=page_id,
                       kind=kind)

    # TWO PASSES, and only when the first one had to guess. The deterministic
    # binder resolves most bindings for free; what it cannot resolve is a
    # judgement no string operation reaches — a quorum gauge labelled
    # 'نسبة النصاب القانوني' contains no entity name in any language. Pass one
    # asks, the resolver answers from the CLOSED entity set, pass two binds.
    #
    # Re-translating rather than patching keeps one code path: the second pass
    # is the same function with better inputs, so nothing can drift between
    # "bound normally" and "bound after a hint".
    questions = result.get("questions") or []
    if questions and _resolver_enabled():
        try:
            from services.binding_resolver import resolve_entities
            hints = resolve_entities(questions, registry=registry,
                                     route=route, kind=kind)
        except Exception as exc:  # noqa: BLE001 — quality degrades, not the build
            logger.warning("[a2ui] entity resolver failed: %s", exc)
            hints = {}
        if hints:
            logger.info("[a2ui] resolver answered %d of %d guessed binding(s): %s",
                        len(hints), len(questions),
                        ", ".join(f"{k}->{v}" for k, v in sorted(hints.items())))
            result = translate(payload, registry, route=route, page_id=page_id,
                               kind=kind, entity_hints=hints)
            result["resolved_entities"] = hints

    schema = result["schema"]

    findings = _floor_findings(kind, route, schema, registry)
    pruned: list[str] = []
    if findings:
        # SALVAGE BEFORE DECLINE. All-or-nothing cost a real build a 95-node
        # dashboard over 3 unreadable charts — the app shipped a 13-node stub
        # titled "Dashboard Page" instead. Drop the widgets the floor named
        # and re-judge; a dashboard missing one chart is still a dashboard.
        candidate, pruned = _prune_failing_widgets(schema, findings)
        if pruned:
            still = _floor_findings(kind, route, candidate, registry)
            if not still:
                logger.info("[a2ui] %s salvaged — dropped %d widget(s) the "
                            "floor rejected: %s", route, len(pruned),
                            ", ".join(pruned))
                schema, findings = candidate, []
            else:
                # Pruning did not clear it: what remains is structural, and
                # shipping a page the floor still rejects would make the gate
                # meaningless. Report both rounds so the cause is legible.
                findings = still
    if findings:
        return {"applied": False, "route": route, "kind": kind,
                "reason": f"composed page failed the {_family_of(kind)} floor: "
                          + ", ".join(f["rule"] for f in findings),
                "findings": [f["rule"] for f in findings],
                "pruned": pruned,
                "unresolved": result["unresolved"],
                "warnings": result["warnings"]}

    # Written only when this is improving a page that already exists on disk.
    # Composing into a `pageLayouts` artifact is the §115 path: the Blueprint
    # is the source of truth, `frontend` projects it, and every binder built
    # around that artifact — data_sources, gate_states, bind_workflows — runs
    # over A2UI's tree exactly as it runs over an agent's. A composer that
    # writes the output file instead leaves the Blueprint saying something
    # different, which is the divergence codeMap and the API routes both were.
    if target is not None:
        tmp = target.with_suffix(".json.a2ui-tmp")
        tmp.write_text(json.dumps(schema, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(target)

    logger.info("[a2ui] composed %s (%s) — %d dataSources, %d unresolved",
                route, kind, len(schema.get("dataSources") or []),
                len(result["unresolved"]))
    return {
        "applied": True, "route": route, "kind": kind, "reason": "ok",
        "pruned": pruned,
        # The composition itself, for a caller emitting an artifact rather
        # than reading the file back.
        "root": schema.get("root"),
        "schema": schema,
        "page_id": page_id,
        "schema_path": str(target) if target is not None else None,
        "data_sources": len(schema.get("dataSources") or []),
        "assumptions": result["assumptions"],
        "unresolved": result["unresolved"],
        "warnings": result["warnings"],
        "dropped_data_model_keys": result["dropped_data_model_keys"],
    }


def compose_dashboard_via_a2ui(
    output_dir: str,
    *,
    surface_provider: Optional[SurfaceProvider] = None,
) -> dict[str, Any]:
    """The landing dashboard. A thin alias now that every kind shares one
    path — kept because the dashboard is the one route with an existing
    caller and an existing test suite pinned to this name."""
    root = Path(output_dir)
    target = _dashboard_schema_path(root)
    route = "/"
    if target is not None:
        try:
            route = str(json.loads(target.read_text(encoding="utf-8")).get("route") or "/")
        except Exception:  # noqa: BLE001
            pass
    elif is_a2ui_enabled():
        return {"applied": False, "reason": "no landing dashboard schema to own"}
    return compose_page_via_a2ui(output_dir, route, "dashboard",
                                 surface_provider=surface_provider)


def compose_pages_via_a2ui(
    output_dir: str,
    *,
    surface_provider: Optional[SurfaceProvider] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Offer A2UI every page the plan declares a shape for.

    THE COST IS THE DESIGN CONSTRAINT HERE. One composition is a network round
    trip with up to three validate-and-retry attempts inside it — measured at
    4-6 minutes. A twenty-page app composed page by page is two hours, which is
    not a build anybody waits for. So this is capped, and what the cap skipped
    is logged rather than silently dropped: a run that quietly did half the
    work reads exactly like a run that did all of it.

    Ordered dashboard-first, then by the plan's own page order, so the cap
    spends its budget on the screens a reader reaches first.
    """
    root = Path(output_dir)
    if not is_a2ui_enabled():
        return {"attempted": 0, "applied": 0, "reason": "FORGE_A2UI is off",
                "pages": []}

    cap = limit if limit is not None else int(
        os.environ.get("FORGE_A2UI_MAX_PAGES", "4"))
    # SCOPE. Page authority proved out on four kinds, but each composition is
    # a 2-4 minute round trip and one of four live attempts failed on a
    # transient fault a retry cleared. Until that rate is measured, the shipped
    # scope is the dashboard — the screen the whole app is judged by, and the
    # kind with the most evidence behind it. "pages" restores the capped
    # multi-kind behaviour with no code change.
    scope = (os.environ.get("FORGE_A2UI_SCOPE") or "dashboard").strip().lower()

    plan = _load_plan(root)
    candidates: list[tuple[str, str]] = []
    for pg in plan.get("pages") or []:
        if not isinstance(pg, dict) or not pg.get("route"):
            continue
        kind = pg.get("kind") or pg.get("type") or ""
        from services.page_kind_anatomy import page_family
        from services.dashboard_anatomy import is_dashboard_route
        route = "/" + str(pg["route"]).strip("/")
        if page_family(kind) is None and not is_dashboard_route(route):
            continue  # auth, static, and anything with no shape opinion
        if scope == "dashboard" and not is_dashboard_route(route):
            continue  # out of scope — left to the deterministic composers
        candidates.append((route, str(kind)))

    from services.dashboard_anatomy import is_dashboard_route
    candidates.sort(key=lambda rk: (not is_dashboard_route(rk[0]),))

    chosen, skipped = candidates[:cap], candidates[cap:]
    results = []
    for route, kind in chosen:
        results.append(compose_page_via_a2ui(output_dir, route, kind,
                                             surface_provider=surface_provider))

    applied = [r for r in results if r.get("applied")]
    if skipped:
        logger.info("[a2ui] cap of %d reached — %d page(s) left to the "
                    "deterministic composers: %s", cap, len(skipped),
                    ", ".join(r for r, _ in skipped))
    logger.info("[a2ui] composed %d of %d attempted page(s)",
                len(applied), len(results))
    return {
        "attempted": len(results),
        "applied": len(applied),
        "applied_routes": [r["route"] for r in applied],
        "declined": [{"route": r["route"], "reason": r.get("reason")}
                     for r in results if not r.get("applied")],
        "skipped_by_cap": [r for r, _ in skipped],
        "cap": cap,
        "pages": results,
    }


def _route_slug(route: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (route or "/").lower()).strip("-")
    return slug or "home"


def _iter_schema_files(schemas: Path):
    """Every page schema in the app, shallowest first.

    Detail and nested-create pages live in SUBDIRECTORIES: ``/sessions/[id]``
    is ``src/schemas/sessions/[id].json``, and a real app carries roughly three
    nested files for every top-level one. A shallow glob here reads as a
    missing page and reports as one, which is how page authority came to cover
    a quarter of an app while claiming the rest had no schema at all.

    Shallowest first so a top-level file wins its own route before any nested
    namesake, and sorted within a depth so the choice is stable across runs.
    """
    return sorted(
        (f for f in schemas.rglob("*.json") if f.name != "shell.json"),
        key=lambda f: (len(f.relative_to(schemas).parts), f.parts),
    )


def _resolver_enabled() -> bool:
    """The entity resolver is ON with A2UI unless explicitly disabled.

    It costs one small call, and only on pages where the binder ALREADY had to
    guess — the alternative to paying for it is shipping the guess, which is
    what put Bill behind a quorum gauge. `FORGE_BINDING_RESOLVER=off` restores
    the guess-and-report behaviour.
    """
    mode = (os.environ.get("FORGE_BINDING_RESOLVER") or "").strip().lower()
    return mode not in ("off", "0", "false", "no")


def _reads(blob: str, ref: str) -> bool:
    """Whether serialised JSON binds to the source named `ref`.

    Three shapes, because a binding is written three ways: `{{plants}}` whole,
    `{{plants.count}}` into a field, and a bare `"plants"` where a prop names
    its source. Matching only the first let `{{plantstracked.value}}` survive a
    prune that was supposed to remove it.
    """
    return (f"{{{{{ref}}}}}" in blob
            or f"{{{{{ref}." in blob
            or f'"{ref}"' in blob)


def _prune_failing_widgets(schema: dict,
                           findings: list[dict]) -> tuple[dict, list[str]]:
    """Drop the dataSources a floor rejected, and whatever bound to them.

    The floor used to be all-or-nothing: any finding meant the whole page was
    declined and the app fell back to a deterministic stub. On a real build
    that traded a 95-node composition for 13 nodes titled "Dashboard Page" —
    over 3 charts. Dropping the 3 is strictly better than dropping the 92.

    Only findings that NAME a dataSource (`ref`) can be repaired this way.
    Structural ones — no KPI row, no content at all — describe the page rather
    than a widget, so they prune nothing and the caller still declines.

    Returns a NEW schema; the caller keeps the original to report on.
    """
    refs = {str(f.get("ref")) for f in findings or [] if f.get("ref")}
    if not refs:
        return schema, []

    out = copy.deepcopy(schema)
    kept = [s for s in (out.get("dataSources") or [])
            if str(s.get("name")) not in refs]
    pruned = [s for s in (out.get("dataSources") or [])
              if str(s.get("name")) in refs]
    out["dataSources"] = kept

    def binds_to_pruned(node: dict) -> bool:
        """Whether this subtree reads one of the removed sources. Checked over
        the serialised node so a `{{name}}` anywhere in props counts."""
        return any(_reads(json.dumps(node), r) for r in refs)

    def strip(node: Any) -> Optional[dict]:
        if not isinstance(node, dict):
            return node
        children = node.get("children")
        if isinstance(children, list):
            new_children = [c for c in (strip(c) for c in children) if c is not None]
            node = {**node, "children": new_children}
            # A container whose children all went is an empty box on the page.
            if not new_children and not _draws_on_its_own(node):
                return None
        elif binds_to_pruned(node):
            return None
        if binds_to_pruned(node) and not (node.get("children") or []):
            return None
        return node

    root = strip(out.get("root") or {})
    out["root"] = root if root is not None else {"type": "Stack", "children": []}
    before = json.dumps(schema)
    named = {str(s.get("name")) for s in pruned}
    return out, sorted(r for r in refs if r in named or _reads(before, r))


# Leaf types that are worth keeping even with no children — they render their
# own content, so an empty `children` is not an empty box.
_SELF_DRAWING = frozenset({
    "Text", "Heading", "MetricTile", "Stat", "Badge", "Tag", "Image", "Icon",
    "Divider", "Button", "EmptyStateRich", "IllustratedEmpty",
})


def _draws_on_its_own(node: dict) -> bool:
    return str(node.get("type") or "") in _SELF_DRAWING


def _schema_path_for_route(root: Path, route: str) -> Optional[Path]:
    """The schema file serving this route, found BY ROUTE rather than by
    filename — the two do not reliably agree (``/dashboard`` lives in
    ``dashboard.json``, ``/`` sometimes in ``home.json``)."""
    schemas = root / "src" / "schemas"
    if not schemas.is_dir():
        return None
    want = "/" + str(route or "").strip("/")
    for p in _iter_schema_files(schemas):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict) and "/" + str(doc.get("route") or "").strip("/") == want:
            return p
    return None


def _dashboard_schema_path(root: Path) -> Optional[Path]:
    """The landing dashboard's schema file, found the same way the maquette
    composer finds it — by route, not by filename."""
    schemas = root / "src" / "schemas"
    if not schemas.is_dir():
        return None
    from services.dashboard_anatomy import is_dashboard_route

    for p in _iter_schema_files(schemas):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict) and is_dashboard_route(str(doc.get("route") or "")):
            return p
    return None
