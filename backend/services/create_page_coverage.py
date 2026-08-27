"""Create-page coverage: guarantee that every `/{entity}/new` route a page links to
actually exists. The page agent emits "New X" buttons for each entity, but the planner
often only declares one create page — so the others 404. This deterministically builds
a Form page (from the entity's registry fields + its Create<Entity> workflow) for any
referenced-but-missing create route."""
from __future__ import annotations

import json
import logging
import re
from glob import glob
from pathlib import Path

logger = logging.getLogger(__name__)

# Allow hyphens so multi-word kebab routes (`/interview-feedback/new`) are discovered,
# not just single-word slugs.
_NEW_REF = re.compile(r'"/([a-zA-Z][a-zA-Z0-9_-]*)/new"')
_SKIP_COLS = {"id", "createdat", "updatedat", "deletedat"}
_FIELD_TYPES = {"Input", "Textarea", "Select", "NumberInput", "DatePicker",
                "Switch", "Combobox", "MultiSelect", "RadioGroup", "MaskedInput", "KeyValueInput"}


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _page_has_fields(schema) -> bool:
    """True if the page schema already contains at least one form field node.
    A create page with none is a husk (e.g. the minimal form ensure_create_routes
    synthesizes) that create-page coverage should upgrade to a real form."""
    if isinstance(schema, (str, Path)):
        try:
            schema = json.loads(Path(schema).read_text(encoding="utf-8"))
        except Exception:
            return True  # unreadable → don't touch it
    stack = [schema.get("root") if isinstance(schema, dict) and "root" in schema else schema]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("type") in _FIELD_TYPES and (cur.get("props") or {}).get("name"):
                return True
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)
    return False


def _form_bindings(schema) -> tuple[list[str], set[str]]:
    """(Form workflow names, field-node names) declared in a page schema."""
    if isinstance(schema, (str, Path)):
        try:
            schema = json.loads(Path(schema).read_text(encoding="utf-8"))
        except Exception:
            return [], set()
    workflows: list[str] = []
    fields: set[str] = set()
    stack = [schema.get("root") if isinstance(schema, dict) and "root" in schema else schema]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("type") == "Form":
                wf = (cur.get("props") or {}).get("workflow")
                if wf:
                    workflows.append(str(wf))
            if cur.get("type") in _FIELD_TYPES:
                nm = (cur.get("props") or {}).get("name")
                if nm:
                    fields.add(str(nm))
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)
    return workflows, fields


def _page_bound_to_entity(schema, entity: str, cols: dict | None) -> bool:
    """True when an existing create page is already bound to THIS route's entity — the
    ONLY case coverage leaves untouched. A page whose Form workflow is `Create<Other>`
    (≠ `Create<RouteEntity>`), or whose field set belongs to a different entity, is a
    husk to rebuild. An empty (no-field) page is never "bound" → rebuild.

    Workflow is the authoritative signal; when absent we fall back to matching the page's
    field names against the route entity's columns."""
    workflows, fields = _form_bindings(schema)
    if not fields:
        return False  # husk
    want = _norm(f"Create{entity}")
    wf_norms = {_norm(w) for w in workflows}
    if wf_norms:
        if want in wf_norms:
            return True                                   # bound to the route entity
        if any(w.startswith("create") for w in wf_norms):
            return False                                  # bound to a different entity
        # workflows present but none Create<X> — fall through to field matching
    col_norms = {_norm(c) for c in (cols or {})}
    if not col_norms:
        return True                                       # can't tell → don't destroy it
    f_norms = {_norm(f) for f in fields}
    overlap = len(f_norms & col_norms)
    return overlap >= max(1, (len(f_norms) + 1) // 2)     # majority of fields are its columns


def _datasource_segment_map(output_dir: Path) -> dict[str, str]:
    """Map a route segment ('bookings') → entity ('ClassBooking') from each list
    page's OWN dataSource. Bridges friendly routes the entity slug can't reach
    (a page at /bookings backed by dataSource entity ClassBooking)."""
    out: dict[str, str] = {}
    sroot = output_dir / "src" / "schemas"
    for f in glob(str(sroot / "**" / "*.json"), recursive=True):
        try:
            sc = json.loads(Path(f).read_text(encoding="utf-8"))
        except Exception:
            continue
        route = str(sc.get("route") or "")
        if not route or "/new" in route or "/edit" in route or "[" in route or ":" in route:
            continue
        segs = [s for s in route.strip("/").split("/") if s]
        if not segs:
            continue
        ds = sc.get("dataSources")
        if not isinstance(ds, list):
            continue
        for d in ds:
            if isinstance(d, dict) and d.get("entity") and d.get("op") in ("list", None):
                out.setdefault(segs[0].lower(), d["entity"])
                break
    return out


def _humanize(col: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", col).replace("_", " ").strip()
    s = re.sub(r"\bId\b", "", s, flags=re.I).strip() or col
    return s[:1].upper() + s[1:]


def _input_type(col: str) -> str:
    # Allowed Input types: text | email | password | number | url | tel (no "date").
    c = col.lower()
    if "email" in c:
        return "email"
    if "phone" in c or "tel" in c:
        return "tel"
    if any(k in c for k in ("amount", "total", "subtotal", "tax", "price", "qty", "count", "duration")):
        return "number"
    return "text"


def _entity_fields(registry: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, ent in (registry.get("entities") or {}).items():
        if not isinstance(ent, dict):
            continue
        f = ent.get("fields")
        cols = list(f.keys()) if isinstance(f, dict) else [
            c.get("name") for c in (f or []) if isinstance(c, dict) and c.get("name")
        ]
        out[name] = [c for c in cols if c and c.lower() not in _SKIP_COLS]
    return out


def _entity_columns(registry: dict) -> dict[str, dict]:
    """entity name → its columns metadata dict (name→meta), UNFILTERED — build_form_page
    does the PK/system/lifecycle filtering. Tolerates the registry `fields` being either
    a {name: meta} dict or a list of {name, ...} dicts."""
    out: dict[str, dict] = {}
    for name, ent in (registry.get("entities") or {}).items():
        if not isinstance(ent, dict):
            continue
        f = ent.get("fields")
        out[name] = f if isinstance(f, dict) else {
            c.get("name"): c for c in (f or []) if isinstance(c, dict) and c.get("name")}
    return out


def _segment_entity_map(output_dir: Path, registry: dict) -> dict[str, str]:
    """Map a route segment ('owners') → the registry entity name ('Owner'), keyed off the
    Create<Entity> workflows that actually exist (the form's submit target)."""
    wf_dir_candidates = [output_dir / "workflows", output_dir / "src" / "workflows"]
    entities = set()
    for d in wf_dir_candidates:
        for f in glob(str(d / "Create*.json")):
            entities.add(Path(f).stem[len("Create"):])
    entities |= {e for e in (registry.get("entities") or {})}
    seg_map: dict[str, str] = {}
    for e in entities:
        if not e:
            continue
        low = e.lower()
        seg_map.setdefault(low, e)
        seg_map.setdefault(low + "s", e)
        if low.endswith("y"):
            seg_map.setdefault(low[:-1] + "ies", e)
        # Kebab id/slug so multi-word routes resolve (/interview-feedback → InterviewFeedback);
        # a single-word entity's lower-case already covers its kebab form.
        try:
            from services.name_normalizer import name_family
            fam = name_family(e)
            for key in (fam.get("id"), fam.get("slug")):
                if key:
                    seg_map.setdefault(str(key).lower(), e)
        except Exception:
            pass
    # An explicit registry slug/id on the entity record wins for resolution when present.
    for nm, ent in (registry.get("entities") or {}).items():
        if not isinstance(ent, dict):
            continue
        for key in (ent.get("slug"), ent.get("id"), ent.get("table")):
            if key:
                seg_map.setdefault(str(key).lower(), nm)
    # Bridge friendly routes the entity slug can't reach (/bookings → ClassBooking),
    # keyed off each list page's own dataSource. setdefault → slug mappings win.
    for seg, ent in _datasource_segment_map(output_dir).items():
        if ent in entities or ent in (registry.get("entities") or {}):
            seg_map.setdefault(seg, ent)
    return seg_map


def find_referenced_create_routes(output_dir: str | Path) -> set[str]:
    out = Path(output_dir)
    refs: set[str] = set()
    for f in glob(str(out / "src" / "schemas" / "**" / "*.json"), recursive=True):
        try:
            txt = Path(f).read_text(encoding="utf-8")
        except Exception:
            continue
        for seg in _NEW_REF.findall(txt):
            refs.add(seg)
    return refs


def build_create_page(route: str, entity: str, cols, workflow: str,
                      entities: dict | None = None, output_dir: str | Path | None = None) -> dict:
    """Build a create-form page by delegating to the registry-driven
    `deterministic_pages.build_form_page` — the correct builder (FK→Select+optionsFrom,
    SQL-type→control, `validators.required`, Card + 2-col Grid, FK dataSources).

    `cols` may be a column-metadata dict `{name: meta}` (preferred) or a legacy bare
    name list (best-effort — no metadata → build_form_page infers plain Inputs). The
    returned page's `id` keeps the route-derived form used by callers/dedup.
    `workflow` is accepted for backward compatibility; build_form_page derives the same
    `Create<Entity>` workflow internally."""
    from services.deterministic_pages import build_form_page
    if isinstance(cols, dict):
        columns = cols
    else:
        columns = {c: {} for c in (cols or [])}  # legacy: no metadata → best-effort types
    page = build_form_page(entity, columns, route, design_spec=None, op="create",
                           entities=entities or {},
                           output_dir=str(output_dir) if output_dir else None)
    page["id"] = route.strip("/").replace("/", "-")
    return page


async def ensure_create_pages_llm(
    output_dir: str | Path, registry: dict, plan: dict, domain_context: dict | None = None
) -> list[str]:
    """LLM-first create-page coverage: for each create route that's missing or only a
    husk (an empty form — e.g. the minimal one ensure_create_routes synthesizes),
    generate a design- and domain-aware form via the per-page schema agent, then wire
    its Create<Entity> workflow.

    The per-route agent calls run CONCURRENTLY under a semaphore (FORGE_PAGE_CONCURRENCY,
    same cap as the main page phase) so N create forms cost ~one wave of wall-clock, not
    N sequential calls. Each task writes only its own schemas/<seg>/new.json, so parallel
    writes don't contend. Falls back to the deterministic builder on any failure; an
    existing husk is left for form_scaffold rather than overwritten with plain Inputs."""
    import asyncio
    import os as _os

    out = Path(output_dir)
    schemas = out / "src" / "schemas"
    # Column METADATA per entity (name→meta) so the delegated build_form_page can pick
    # FK Selects / SQL-typed controls / required markers — not just field names.
    cols_meta_ci = {k.lower(): v for k, v in _entity_columns(registry).items()}
    reg_entities = registry.get("entities") or {}
    seg_map = _segment_entity_map(out, registry)

    from agents.page_schema_agent import run_page_schema_agent  # lazy (avoid import cycle)
    from services.schema_pipeline import _apply_plan_binding

    plan_with_entities = {**(plan or {}), "entities": (registry.get("entities") or (plan or {}).get("entities") or {})}

    # Collect the work: a create route that's missing, a husk, OR bound to the WRONG
    # entity. The page's entity must be the ROUTE's registry entity — a page authored
    # with a different `Create<Other>` workflow / another entity's fields is rebuilt
    # deterministically from the route entity. A page already bound to THIS route's
    # entity is left untouched (idempotent).
    work: list[tuple[str, Path, str]] = []
    for seg in sorted(find_referenced_create_routes(out)):
        target = schemas / seg / "new.json"
        entity = seg_map.get(seg.lower())
        if not entity:
            continue
        if target.exists() and _page_bound_to_entity(target, entity, cols_meta_ci.get(entity.lower())):
            continue
        work.append((seg, target, entity))
    if not work:
        return []

    cap = max(1, int(_os.environ.get("FORGE_PAGE_CONCURRENCY", "5")))
    sem = asyncio.Semaphore(cap)
    from services.flag_profile import is_on
    _det_on = is_on("FORGE_DETERMINISTIC_CRUD", default=True)

    async def _gen(seg: str, target: Path, entity: str) -> str | None:
        route = f"/{seg}/new"
        cols = cols_meta_ci.get(entity.lower()) or {}
        # Deterministic-first: a create form is just the entity's fields + its
        # Create<Entity> workflow. Build it directly — 0 LLM calls — mirroring the
        # main page pass, instead of a multi-turn agent (which cost ~2-3 min per
        # /new page, e.g. inbox/new). form_scaffold later refines FK selects / types.
        # Falls back to the LLM only when the entity's columns are unknown.
        if _det_on and cols:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(
                    build_create_page(route, entity, cols, f"Create{entity}", reg_entities, output_dir=out), indent=2))
                if _page_has_fields(target):
                    logger.info("[Schema] ⚡ deterministic create page (no LLM): %s", route)
                    return route
            except Exception:
                logger.warning("[Schema] deterministic create page failed for %s — LLM fallback", route)
        page = {"route": route, "type": "form", "archetype": "form", "entity": entity, "name": f"New {entity}"}
        async with sem:
            try:
                await run_page_schema_agent(str(out), plan_with_entities, page, domain_context=domain_context)
                await _apply_plan_binding(str(out), plan_with_entities,
                                          {**page, "_page_type": "form", "_route": route}, [], [])
            except Exception:
                # LLM failed: leave any existing husk for form_scaffold (adds FK Selects);
                # only synthesize deterministically when nothing exists yet.
                if not target.exists() and cols:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(build_create_page(route, entity, cols, f"Create{entity}", reg_entities, output_dir=out), indent=2))
        return route if (target.exists() and _page_has_fields(target)) else None

    results = await asyncio.gather(*[_gen(*w) for w in work])
    return [r for r in results if r]


def ensure_create_pages(output_dir: str | Path, registry: dict) -> list[str]:
    """Generate a Form page for every referenced-but-missing /{segment}/new route.
    Returns the list of routes created."""
    out = Path(output_dir)
    schemas = out / "src" / "schemas"
    # case-insensitive entity → column METADATA lookup (build_form_page does the filtering)
    cols_meta_ci = {k.lower(): v for k, v in _entity_columns(registry).items()}
    reg_entities = registry.get("entities") or {}
    seg_map = _segment_entity_map(out, registry)

    created: list[str] = []
    for seg in sorted(find_referenced_create_routes(out)):
        target = schemas / seg / "new.json"
        entity = seg_map.get(seg.lower())
        if not entity:
            continue
        cols = cols_meta_ci.get(entity.lower()) or {}
        if not cols:
            continue
        # Leave a page ONLY if it's already bound to THIS route's entity; a missing page
        # or one bound to a different entity (wrong Create<Other> workflow) is (re)built.
        if target.exists() and _page_bound_to_entity(target, entity, cols):
            continue
        page = build_create_page(f"/{seg}/new", entity, cols, f"Create{entity}", reg_entities, output_dir=out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(page, indent=2), encoding="utf-8")
        created.append(f"/{seg}/new")
    return created
