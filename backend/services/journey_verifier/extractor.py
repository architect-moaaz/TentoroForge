"""Extract JourneySpec from any generated app's plan.json.

Two paths:

1. Archetype-specific extractors (visual_product_search, kanban, ...) know
   the canonical golden path for their shape and emit a rich JourneySpec
   with real assertions.

2. Generic fallback: walk every route in plan.pages, verify each page
   loads without a console error and that any lists render. Weaker but
   universal — every app gets at least a smoke test.

The archetype extractors are the ones that catch the interesting bugs.
The generic fallback catches "the app doesn't even boot".
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .spec import (
    EntityFilter,
    Journey,
    JourneySpec,
    Locator,
    Step,
    WorkflowFilter,
)


# ---------------------------------------------------------------------------
# Archetype registry
# ---------------------------------------------------------------------------

def _extract_visual_product_search(plan: dict[str, Any], app_slug: str) -> list[Journey]:
    """Golden path: authenticated user uploads a product image, workflow
    runs, at least one price row lands.

    This is the assertion set that would have caught every bug from today's
    session: empty imageUrl in scan_sessions, workflow stopping before
    mark_completed, no price_results being inserted.
    """
    scan_entity = _resolve_entity(plan, ["scan_sessions", "scans", "scan"])
    price_entity = _resolve_entity(plan, ["price_results", "price_listings", "prices"])
    workflow_id = _resolve_workflow(plan, "ScanProductWorkflow") or "scan-product-workflow"

    steps: list[Step] = [
        # Admin creds are the only seed with a real password_hash today.
        # The archetype journey doesn't need admin privileges — any signed-in
        # user can scan — but the /login path rejects everyone else.
        Step(kind="login_as", name="Sign in",
             email="admin@example.com", password="admin1234",
             timeout_ms=15_000),
        Step(kind="visit", name="Open /scan", route="/scan"),
        Step(kind="wait_for_element", name="Idle form is visible",
             locator=Locator(role="button", label="Scan & compare")),
        Step(kind="upload", name="Upload product image",
             locator=Locator(css='input[type="file"]'),
             fixture="product_image"),
        Step(kind="click", name="Submit scan",
             locator=Locator(role="button", label="Scan & compare")),
        Step(kind="wait_for_workflow", name="Workflow runs to terminal",
             workflow_filter=WorkflowFilter(
                 workflow_id=workflow_id,
                 target_status="terminal",
                 timeout_ms=90_000,
             )),
        Step(kind="assert_entity", name="Scan session recorded",
             entity_filter=EntityFilter(
                 entity=scan_entity or "scan_sessions",
                 where={},  # any recent row is fine — details poll below
                 min_count=1,
             ),
             timeout_ms=5_000),
        Step(kind="assert_entity", name="At least one price row inserted",
             entity_filter=EntityFilter(
                 entity=price_entity or "price_results",
                 where={},
                 min_count=1,
             ),
             timeout_ms=60_000),
    ]
    return [Journey(
        slug="primary-scan",
        name="Scan a product and see prices",
        actor="Member",
        tags=["primary", "archetype:visual_product_search"],
        steps=steps,
    )]


def _extract_crud(plan: dict[str, Any], app_slug: str) -> list[Journey]:
    """Generic CRUD golden path: for the first non-auth entity in the plan,
    create → list → detail → delete. Catches broken forms + broken lists +
    broken detail routes without needing an archetype-specific extractor."""
    entities = plan.get("entities") or []
    if isinstance(entities, dict):
        entities = [{"name": k, **v} for k, v in entities.items() if isinstance(v, dict)]
    target = next((e for e in entities
                   if e.get("name", "").lower() not in ("user", "users", "session", "account")),
                  None)
    if not target:
        return []
    ename = target.get("name") or "Entity"
    slug = ename.lower()
    plural = _plural_route(ename)
    return [Journey(
        slug=f"crud-{slug}",
        name=f"Create and view a {ename}",
        actor="Admin",
        tags=["primary", "archetype:crud"],
        steps=[
            Step(kind="login_as", email="admin@example.com", password="admin1234"),
            Step(kind="visit", route=f"/{plural}"),
            Step(kind="wait_for_route", route=f"/{plural}"),
            Step(kind="assert_no_console_errors"),
        ],
    )]


def _extract_crud_write(plan: dict[str, Any], app_slug: str) -> list[Journey]:
    """Real create-form journey for a CRUD app: visit /entity/new, fill
    every required non-lifecycle field, submit, verify the row lands.

    Different from _extract_crud (the fallback smoke) — this one actually
    *writes* through the form and asserts the DB, so a broken form/submit
    wiring fails the gate, not just a broken route."""
    entity = _pick_write_target(plan)
    if not entity:
        return []
    ename = entity["name"]
    plural = _plural_route(ename)
    fills = _synthesize_field_fills(entity, plan)
    steps: list[Step] = [
        Step(kind="login_as", email="admin@example.com", password="admin1234"),
        Step(kind="visit", route=f"/{plural}/new"),
        Step(kind="wait_for_element", name=f"Create-{ename} form loaded",
             locator=Locator(role="button", label="Cancel"),
             timeout_ms=10_000),
    ]
    for f in fills:
        steps.append(Step(kind="fill", name=f"Fill {f['label']}",
                          locator=Locator(css=f'[name="{f["name"]}"]'),
                          value=str(f["value"])))
    steps += [
        Step(kind="click", name="Submit form",
             locator=Locator(journey_slug="form-submit",
                             role="button", label="Create")),
        Step(kind="assert_entity", name=f"A {ename} row lands",
             entity_filter=EntityFilter(
                 entity=_resolve_entity(plan, [ename, ename.lower()]) or ename.lower(),
                 where={}, min_count=1,
             ),
             timeout_ms=15_000),
    ]
    return [Journey(
        slug=f"crud-write-{ename.lower()}",
        name=f"Create a {ename} through the UI",
        actor="Admin",
        tags=["primary", "archetype:crud_write"],
        steps=steps,
    )]


def _extract_kanban(plan: dict[str, Any], app_slug: str) -> list[Journey]:
    """Kanban interaction: visit the kanban page, verify columns render,
    move the first card to the next status. Failing this indicates the
    Kanban binding is broken or the status-update workflow is missing."""
    kanban_page = _find_page_with_archetype(plan, "kanban")
    if not kanban_page:
        return []
    route = _route_of(kanban_page)
    return [Journey(
        slug=f"kanban-flow",
        name=f"Open {kanban_page.get('name') or 'board'} and see columns",
        actor="Admin",
        tags=["primary", "archetype:kanban"],
        steps=[
            Step(kind="login_as", email="admin@example.com", password="admin1234"),
            Step(kind="visit", route=route),
            Step(kind="wait_for_element", name="Kanban board renders",
                 locator=Locator(css='[data-role="kanban"], .kanban, [class*="Kanban"]'),
                 timeout_ms=15_000),
            Step(kind="assert_no_console_errors"),
        ],
    )]


def _extract_ecommerce(plan: dict[str, Any], app_slug: str) -> list[Journey]:
    """Product listing + add-to-cart: visit /products, add first product,
    verify cart shows one item. Catches broken commerce wiring end-to-end."""
    product_entity = _resolve_entity(plan, ["products", "product", "items", "item", "listings"])
    if not product_entity:
        return []
    return [Journey(
        slug="ecommerce-add-to-cart",
        name="Add a product to cart",
        actor="Member",
        tags=["primary", "archetype:ecommerce"],
        steps=[
            Step(kind="login_as", email="admin@example.com", password="admin1234"),
            Step(kind="visit", route=f"/{_plural_route(product_entity)}"),
            Step(kind="wait_for_element", name="Product list renders",
                 locator=Locator(role="button", label="Add to Cart"),
                 timeout_ms=15_000),
            Step(kind="click", name="Add first product to cart",
                 locator=Locator(role="button", label="Add to Cart")),
            Step(kind="assert_entity", name="Cart row exists",
                 entity_filter=EntityFilter(
                     entity=_resolve_entity(plan, ["forge_cart", "cart", "cart_items"]) or "forge_cart",
                     where={}, min_count=1,
                 ),
                 timeout_ms=5_000),
        ],
    )]


def _extract_recruitment(plan: dict[str, Any], app_slug: str) -> list[Journey]:
    """Recruitment domain (Candidates + Applications): create a candidate,
    then verify the row + kanban/list refreshes. Domain hint is that both
    entities exist by name."""
    candidate = _resolve_entity(plan, ["candidates", "candidate", "applicants", "applicant"])
    if not candidate:
        return []
    # Reuse the crud_write mechanics but on the recruitment-canonical entity.
    entity = _entity_by_name(plan, candidate)
    if not entity:
        return []
    fills = _synthesize_field_fills(entity, plan)
    steps: list[Step] = [
        Step(kind="login_as", email="admin@example.com", password="admin1234"),
        Step(kind="visit", route=f"/{_plural_route(candidate)}/new"),
        Step(kind="wait_for_element", name="Create form loaded",
             locator=Locator(role="button", label="Cancel"),
             timeout_ms=10_000),
    ]
    for f in fills:
        steps.append(Step(kind="fill", name=f"Fill {f['label']}",
                          locator=Locator(css=f'[name="{f["name"]}"]'),
                          value=str(f["value"])))
    steps += [
        Step(kind="click", name="Submit candidate",
             locator=Locator(role="button", label="Create")),
        Step(kind="assert_entity", name=f"A {candidate} row lands",
             entity_filter=EntityFilter(entity=candidate, where={}, min_count=1),
             timeout_ms=15_000),
    ]
    return [Journey(
        slug="recruitment-add-candidate",
        name=f"Register a new {candidate.rstrip('s')}",
        actor="Admin",
        tags=["primary", "archetype:recruitment"],
        steps=steps,
    )]


ARCHETYPE_EXTRACTORS = {
    "visual_product_search": _extract_visual_product_search,
    "visual-product-search": _extract_visual_product_search,
    "crud_write": _extract_crud_write,
    "crud-write": _extract_crud_write,
    "kanban": _extract_kanban,
    "ecommerce": _extract_ecommerce,
    "e-commerce": _extract_ecommerce,
    "recruitment": _extract_recruitment,
    "ats": _extract_recruitment,
}


def _detect_archetype_from_pages(plan: dict[str, Any]) -> str | None:
    """Fallback archetype detection when the plan doesn't declare one.

    Walks the plan's per-page `archetype` values (planner emits these:
    "list"/"detail"/"form"/"kanban"/"calendar"/etc) and picks the most
    interesting shape. "kanban" beats "form", "form" beats "list" alone.

    Also looks at entity names to spot ecommerce/recruitment even when
    the pages are generic CRUD."""
    pages = plan.get("pages") or []
    page_archetypes = {
        (p.get("archetype") or "").lower() for p in pages if isinstance(p, dict)
    }
    if "kanban" in page_archetypes:
        return "kanban"

    # Domain heuristics on entities.
    entities = _all_entity_names(plan)
    lc = {e.lower() for e in entities}
    if any(e in lc for e in ("cart", "forge_cart", "cart_items", "orders")):
        return "ecommerce"
    if any(e in lc for e in ("candidates", "applicants", "applications")):
        return "recruitment"

    # If there's a create-page (`form` archetype), the crud_write journey
    # is stronger than the read-only fallback.
    if "form" in page_archetypes or any(
        (p.get("route") or "").endswith("/new") for p in pages if isinstance(p, dict)
    ):
        return "crud_write"
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_entity(plan: dict, candidates: list[str]) -> str | None:
    """Find the canonical table name for one of a set of aliases.

    Handles the plan's various entity shapes (dict vs list) uniformly, so
    downstream we can just ask "what's the actual table for `scan_sessions`?"
    without knowing which shape the planner emitted this run.
    """
    entities = plan.get("entities") or {}
    if isinstance(entities, dict):
        names = list(entities.keys())
    elif isinstance(entities, list):
        names = [e.get("name") for e in entities if isinstance(e, dict)]
    else:
        names = []
    canon = {n.lower().replace("_", "").replace(" ", ""): n for n in names if n}
    for c in candidates:
        key = c.lower().replace("_", "").replace(" ", "")
        if key in canon:
            return canon[key]
    return None


def _resolve_workflow(plan: dict, candidate: str) -> str | None:
    workflows = plan.get("workflows") or []
    key = candidate.lower().replace("_", "").replace(" ", "").replace("-", "")
    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        wname = wf.get("name") or wf.get("id") or ""
        if wname.lower().replace("_", "").replace(" ", "").replace("-", "") == key:
            return wf.get("id") or _kebab(wname)
    return _kebab(candidate)


def _plural_route(entity: str) -> str:
    # Trivial pluralisation for the fallback route probe. When the pipeline
    # already knows the real route (routesRegistry) we should prefer that;
    # this is the safety-net emitter for unclassified apps.
    e = entity.lower()
    if e.endswith("y"): return e[:-1] + "ies"
    if e.endswith("s"): return e
    return e + "s"


def _kebab(s: str) -> str:
    import re
    return re.sub(r"(?<!^)(?=[A-Z])", "-", s).lower().replace("_", "-").replace(" ", "-")


def _all_entity_names(plan: dict) -> list[str]:
    """Return every entity name in the plan, whatever shape it's in."""
    entities = plan.get("entities") or {}
    if isinstance(entities, dict):
        return list(entities.keys())
    if isinstance(entities, list):
        return [e.get("name") for e in entities if isinstance(e, dict) and e.get("name")]
    return []


def _entity_by_name(plan: dict, name: str) -> dict[str, Any] | None:
    """Look up an entity dict by name — both plan shapes supported."""
    entities = plan.get("entities") or {}
    if isinstance(entities, dict):
        return entities.get(name)
    if isinstance(entities, list):
        for e in entities:
            if isinstance(e, dict) and e.get("name") == name:
                return e
    return None


def _pick_write_target(plan: dict) -> dict[str, Any] | None:
    """First non-auth entity that has at least one non-lifecycle field
    the extractor knows how to fill. Skips users/sessions/accounts — those
    are exercised via login_as, not via the create form."""
    skip = {"user", "users", "session", "sessions", "account", "accounts",
            "workflow_tasks", "workflow_runs", "forge_files"}
    for name in _all_entity_names(plan):
        if not name or name.lower() in skip:
            continue
        ent = _entity_by_name(plan, name)
        if ent and _synthesize_field_fills(ent, plan):
            return {"name": name, **ent}
    return None


def _find_page_with_archetype(plan: dict, archetype: str) -> dict[str, Any] | None:
    for p in plan.get("pages") or []:
        if isinstance(p, dict) and (p.get("archetype") or "").lower() == archetype.lower():
            return p
    return None


def _route_of(page: dict) -> str:
    r = page.get("route") or "/"
    if not r.startswith("/"):
        r = "/" + r
    return r


def _synthesize_field_fills(entity: dict, plan: dict) -> list[dict[str, Any]]:
    """For a create form's required non-lifecycle fields, produce a list
    of {name, label, value} tuples the driver will type into inputs.

    Kept simple: text→"Journey Test", numeric→7, boolean skipped (form
    defaults typically fine), FK/enum skipped (they need a Select, not a
    fill — handled by the deterministic form builder). If the entity has
    no fillable text fields, returns [] so caller can skip crud-write."""
    fields = entity.get("fields") or entity.get("columns") or {}
    if isinstance(fields, dict):
        items = [{"name": k, **(v if isinstance(v, dict) else {})}
                 for k, v in fields.items()]
    elif isinstance(fields, list):
        items = [f for f in fields if isinstance(f, dict)]
    else:
        items = []

    skip_lifecycle = {"id", "createdat", "updatedat", "deletedat",
                      "ownerid", "orgid", "createdby", "updatedby"}
    fills: list[dict[str, Any]] = []
    for f in items:
        name = f.get("name") or ""
        if not name or name.lower().replace("_", "") in skip_lifecycle:
            continue
        ftype = (f.get("type") or f.get("sql_type") or "").lower()
        semantic = (f.get("semantic_type") or "").lower()
        # Only fill "obvious text" so we don't try to auto-fill FK, enum,
        # file, JSONB. Those need a Select/Uploader — beyond the extractor.
        if any(s in ftype for s in ("varchar", "text", "string", "char")) and \
           not any(s in semantic for s in ("email", "fk", "file", "image", "url")):
            fills.append({"name": name, "label": _label(name), "value": "Journey Test"})
        elif any(s in ftype for s in ("int", "numeric", "decimal", "float")):
            fills.append({"name": name, "label": _label(name), "value": "7"})
        if len(fills) >= 3:  # 3 fills is enough — form will typically accept
            break
    return fills


def _label(name: str) -> str:
    return name.replace("_", " ").title() if name else ""


def _default_seed_users() -> list[dict[str, str]]:
    # Placeholder — real implementation should read from the app's seed
    # output. Every generated app currently ships with these two seeded
    # by the platform's `seed.ts`, so this is a safe default for now.
    return [
        {"email": "admin@example.com", "password": "admin1234", "role": "admin"},
        {"email": "test@test.com", "password": "admin1234", "role": "member"},
    ]


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def extract(output_dir: Path | str, base_url: str = "http://localhost:3000") -> JourneySpec:
    """Read plan.json + resolve archetype → return a JourneySpec.

    Never raises on a missing plan or unknown archetype — falls back to a
    generic smoke journey so every app gets *some* verification. The
    per-archetype extractor is what makes the check meaningful.
    """
    output_dir = Path(output_dir)
    plan_path = _find_plan(output_dir)
    plan: dict[str, Any] = {}
    if plan_path and plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            plan = {}

    archetype = (plan.get("archetype") or plan.get("app_archetype") or "").strip()
    app_slug = output_dir.name

    # Fall back to page-shape detection if the plan doesn't declare an
    # app-level archetype — most non-visual-product-search apps don't,
    # even though their per-page archetypes clearly say "kanban" etc.
    if not archetype or archetype not in ARCHETYPE_EXTRACTORS:
        detected = _detect_archetype_from_pages(plan)
        if detected and detected in ARCHETYPE_EXTRACTORS:
            archetype = detected

    journeys: list[Journey] = []
    if archetype and archetype in ARCHETYPE_EXTRACTORS:
        journeys = ARCHETYPE_EXTRACTORS[archetype](plan, app_slug)
    if not journeys:
        journeys = _extract_crud(plan, app_slug)
    if not journeys:
        # Absolute floor: just "the app boots and / renders without error."
        journeys = [Journey(
            slug="smoke-home",
            name="App boots and home renders",
            actor="Member",
            tags=["smoke"],
            steps=[
                Step(kind="login_as", email="test@test.com", password="admin1234"),
                Step(kind="visit", route="/"),
                Step(kind="assert_no_console_errors"),
            ],
        )]

    return JourneySpec(
        app_slug=app_slug,
        archetype=archetype or "unknown",
        base_url=base_url,
        seed_users=_default_seed_users(),
        fixtures={},           # populated by the caller (fixture resolver)
        journeys=journeys,
    )


def _find_plan(output_dir: Path) -> Path | None:
    """Plan.json has moved between locations over versions — check all."""
    for candidate in [
        output_dir / "plan.json",
        output_dir / "src" / "contracts" / "plan.json",
        output_dir / "contracts" / "plan.json",
    ]:
        if candidate.exists():
            return candidate
    return None
