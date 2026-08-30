"""Temporary debug router — manually exercises individual pipeline phases.

POST /api/_debug/regen-schemas/{project_short_id}   - re-run schema-mode
POST /api/_debug/regen-rules/{project_short_id}     - re-run rules agent
POST /api/_debug/recompile-tokens/{project_short_id} - re-run design_compiler step
POST /api/_debug/render-page/{project_short_id}     - trigger a page render via render-service
GET  /api/_debug/project-file/{short_id}/{file_path} - serve arbitrary text files from output/<short_id>/

regen-schemas and regen-rules read output/<short_id>/src/contracts/app-model.json
and stream progress. recompile-tokens reads
output/<short_id>/src/contracts/design-spec.json and rewrites
output/<short_id>/src/theme/tokens.custom.json, returning a summary.
"""
from __future__ import annotations
import io
import json
import tarfile
from pathlib import Path
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from sse_starlette.sse import EventSourceResponse

from services.schema_pipeline import run_schema_frontend_pipeline

router = APIRouter()


def _resolve_output_dir(short_id: str) -> Path:
    """Return the absolute path to output/<short_id> relative to the repo root.

    Extracted as a standalone helper so tests can monkeypatch it without
    touching Path.__file__ resolution.
    """
    return Path(__file__).resolve().parent.parent.parent / "output" / short_id


async def _resolve_project_base(project_id: str) -> Path:
    """Resolve an editor project id → its on-disk output base dir.

    The visual editor addresses projects by the DB **UUID** (`project.id`), but
    these debug endpoints live under `output/<short_id>/`. So: try the id as a
    short_id first (dir on disk = source of truth); if that misses and the id is
    a UUID, look up the project's short_id / output_dir in the DB. Without this,
    an editor passing the UUID gets `output/<uuid>/` → nothing → the Canvas can't
    read nav-flow.json/schemas → "No nav-flow." for every generated app.
    """
    import uuid as _uuid

    base = _resolve_output_dir(project_id)
    if base.exists():
        return base

    try:
        pid = _uuid.UUID(str(project_id))
    except (ValueError, AttributeError):
        # Not a UUID and not an existing dir — return the literal path so the
        # caller's own not-found handling produces a 404 (preserves old behaviour).
        return base

    from sqlalchemy import select
    from database import async_session
    from models.project import Project

    async with async_session() as db:
        proj = (await db.execute(select(Project).where(Project.id == pid))).scalar_one_or_none()
    if not proj:
        raise HTTPException(404, "project not found")
    candidates = [proj.short_id, (proj.output_dir or "").rstrip("/").split("/")[-1] or None]
    for cand in candidates:
        if not cand:
            continue
        r = _resolve_output_dir(cand)
        if r.exists():
            return r
    if proj.output_dir and Path(proj.output_dir).exists():
        return Path(proj.output_dir)
    raise HTTPException(404, "project has no output directory on disk")


def _load_plan(short_id: str) -> tuple[Path, dict]:
    output_dir = _resolve_output_dir(short_id)
    plan_path = output_dir / "src/contracts/app-model.json"
    if not plan_path.exists():
        raise HTTPException(404, f"plan not found at {plan_path}")
    return output_dir, json.loads(plan_path.read_text())


@router.post("/api/_debug/regen-schemas/{short_id}")
async def regen_schemas(short_id: str):
    output_dir, plan = _load_plan(short_id)

    async def stream():
        async for evt in run_schema_frontend_pipeline(str(output_dir), plan, plan.get("description", "")):
            yield evt

    return EventSourceResponse(stream())


@router.post("/api/_debug/regen-rules/{short_id}")
async def regen_rules(short_id: str):
    """Run the rules agent against an existing project's plan + registry,
    re-export rules/index.json via runtime_injector, and sync to the
    project_rules DB table. Returns the generated rules as JSON.
    Looks up project_id by matching projects.short_id == short_id."""
    from agents.rules_agent import run_rules_agent
    from services.runtime_injector import _export_rules_to_filesystem  # type: ignore
    from sqlalchemy import select
    from database import async_session
    from models import Project

    output_dir, plan = _load_plan(short_id)

    project_id = None
    async with async_session() as session:
        row = (await session.execute(
            select(Project.id).where(Project.short_id == short_id)
        )).first()
        if row:
            project_id = row[0]

    rules = await run_rules_agent(str(output_dir), plan, project_id=project_id)
    _export_rules_to_filesystem(output_dir)
    return {"count": len(rules), "project_id": str(project_id) if project_id else None, "rules": rules}


@router.post("/api/_debug/recompile-tokens/{short_id}")
async def recompile_tokens(short_id: str):
    """Re-run the design_compiler step against an existing project's design-spec.

    Reads  output/<short_id>/src/contracts/design-spec.json
    Writes output/<short_id>/src/theme/tokens.custom.json

    This endpoint is for development / debugging only — it is not gated behind
    any authentication middleware.  Use it to:
      - Test a hand-edited design-spec without re-running the full pipeline.
      - Recover a corrupted tokens.custom.json.
      - Verify compiler logic changes against an existing project.

    Returns a summary of the compiled token groups so the caller can do a
    quick sanity-check without reading the file directly.
    """
    from services.design_compiler import compile as compile_design_spec

    output_dir = _resolve_output_dir(short_id)
    spec_path = output_dir / "src" / "contracts" / "design-spec.json"

    if not spec_path.exists():
        raise HTTPException(404, f"design-spec not found at {spec_path}")

    try:
        design_spec = json.loads(spec_path.read_text())
    except json.JSONDecodeError:
        raise HTTPException(400, "design-spec is not valid JSON")

    tokens = compile_design_spec(design_spec)

    tokens_path = output_dir / "src" / "theme" / "tokens.custom.json"
    try:
        tokens_path.parent.mkdir(parents=True, exist_ok=True)
        tokens_path.write_text(json.dumps(tokens, indent=2))
    except OSError as exc:
        raise HTTPException(500, f"failed to write tokens file: {exc}")

    color = tokens.get("color") or {}
    summary = {
        "color_groups": len(color),
        "spacing_keys": len(tokens.get("spacing") or {}),
        "radius_keys": len(tokens.get("radius") or {}),
        "shadow_keys": len(tokens.get("shadow") or {}),
        "has_typography": tokens.get("typography") is not None,
        "has_motion": tokens.get("motion") is not None,
        "has_status": "semantic" in tokens and "status" in tokens.get("semantic", {}),
        "has_layout": tokens.get("layout") is not None,
        "total_top_level_keys": len(tokens),
    }

    return {
        "short_id": short_id,
        "design_spec_path": str(spec_path.resolve()),
        "tokens_path": str(tokens_path.resolve()),
        "summary": summary,
    }


@router.post("/api/_debug/render-page/{short_id}")
async def render_page_debug(short_id: str, page_route: str, viewport: str = "desktop"):
    """Trigger a single page render via the render-service. Useful for manual
    testing without going through the editor UI.

    Query params:
      page_route: schema route, e.g. /users/list
      viewport:  mobile | tablet | desktop  (default desktop)
    """
    if viewport not in ("mobile", "tablet", "desktop"):
        raise HTTPException(400, "viewport must be one of mobile|tablet|desktop")

    render_url = "http://localhost:6502/render"
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(render_url, json={
                "projectId": short_id, "pageRoute": page_route, "viewport": viewport,
            })
        except httpx.RequestError as e:
            raise HTTPException(503, f"render-service unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    body = r.json()
    return {
        "short_id": short_id,
        "page_route": page_route,
        "viewport": viewport,
        "render_time_ms": body["renderTimeMs"],
        "png_bytes": body["pngBytes"],
        # Truncate the data URI to keep the response small
        "png_data_uri_preview": f"data:image/png;base64,{body['pngBase64'][:200]}…",
    }


from pydantic import BaseModel


class UpdateRegisterPayload(BaseModel):
    register: str


@router.put("/api/_debug/project-register/{short_id}")
async def update_project_register(short_id: str, payload: UpdateRegisterPayload):
    """Manual register override — updates design-spec.json's register field.
    Designer-only affordance for forcing a register choice."""
    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    spec_path = output_root / short_id / "src" / "contracts" / "design-spec.json"
    if not spec_path.exists():
        raise HTTPException(404, f"design-spec.json not found for {short_id}")

    valid_registers = {"default", "workday", "linear", "stripe", "notion", "figma"}
    if payload.register not in valid_registers:
        raise HTTPException(400, f"invalid register: {payload.register}")

    try:
        spec = json.loads(spec_path.read_text())
    except json.JSONDecodeError:
        raise HTTPException(500, "design-spec.json is corrupted")

    spec["register"] = payload.register
    spec_path.write_text(json.dumps(spec, indent=2))
    return {"register": payload.register, "ok": True}


def _enrich_record(
    record: dict,
    entity_name: str,
    all_records_by_entity: dict[str, list[dict]],
    fk_joins: bool = True,
) -> dict:
    """Generically enrich a fixture record so LLM-emitted Mustache templates
    referencing reasonable-sounding paths resolve cleanly at render time.

    Two enrichments, both data-driven (no domain hardcoding):

    1. **Foreign-key joins.** For every field ending in ``Id`` whose prefix
       matches another entity in the project (e.g. ``userId`` → ``User``),
       look up the matching record by id and attach it under the prefix
       (``user``) plus a small set of common semantic aliases the LLM
       emits — ``employee``, ``author``, ``owner``, ``assignee``, ``createdBy``,
       ``submitter``, ``manager``, ``customer``, ``person``. The runtime
       interpolator falls back to the literal template when a binding doesn't
       exist, so unused aliases cost nothing.

    2. **Field aliases.** Mirrors common DB column names to the synonyms the
       LLM consistently picks (``type`` ↔ ``leaveType``/``requestType``/
       ``category``, ``daysRequested`` ↔ ``durationDays``/``days``,
       ``submittedAt`` ↔ ``submittedDate``/``createdDate``, etc.). Cheap
       defensive aliasing — adds keys, never overwrites existing values.

    The original record is left intact; aliases are layered on top of a copy.
    """
    out = dict(record)

    # --- FK joins (skipped on the metadata-only pre-pass) ---
    # Two-pass enrichment: callers pass fk_joins=False on the first pass so
    # records get their metadata defaults (avatarUrl, status, manager, …)
    # before any record is joined into another. Then the second pass runs
    # with fk_joins=True against those metadata-enriched records, so a join
    # like `leaveRequest.employee.avatarUrl` resolves all the way through.
    fk_alias_names = (
        "user", "employee", "author", "owner", "assignee", "createdBy",
        "submitter", "manager", "customer", "person", "approver",
    )
    if fk_joins:
        for key, value in list(record.items()):
            if not (isinstance(key, str) and key.endswith("Id") and len(key) > 2):
                continue
            if not isinstance(value, str):
                continue
            # `userId` → entity name candidates: "User", "user", "users"
            prefix = key[:-2]  # "user"
            candidates = [
                prefix[:1].upper() + prefix[1:],   # "User"
                prefix,                            # "user"
                prefix + "s",                      # "users"
                prefix[:1].upper() + prefix[1:] + "s",  # "Users"
            ]
            target_records = None
            for c in candidates:
                if c in all_records_by_entity:
                    target_records = all_records_by_entity[c]
                    break
            # Person-alias fallback: if the FK prefix is one of the well-known
            # person-shaped aliases (assigneeId, authorId, ownerId, etc.) and no
            # entity matched by name, fall back to the User entity. The LLM
            # routinely uses `assigneeId` / `authorId` / `createdById` on
            # records even when the project only declares a `User` entity.
            # Without this fallback, every `{{item.assignee.name}}` /
            # `{{item.author.name}}` binding stays literal at render time.
            if not target_records and prefix in fk_alias_names:
                for user_key in ("User", "user", "users", "Users"):
                    if user_key in all_records_by_entity:
                        target_records = all_records_by_entity[user_key]
                        break
            if not target_records:
                continue
            # Find the record whose id matches the FK value
            match = next((r for r in target_records if r.get("id") == value), None)
            if match is None and target_records:
                # FK value didn't match any record (fixture ids are random) — fall
                # back to the first record so the join still produces a usable
                # nested object instead of a literal template at render time.
                match = target_records[0]
            if match is None:
                continue
            # Attach under prefix + common semantic aliases. Only add if absent —
            # never overwrite a real field the entity already defines.
            out.setdefault(prefix, match)
            for alias in fk_alias_names:
                out.setdefault(alias, match)

    # --- Synthetic metadata defaults (entity-agnostic) ---
    # LLM-emitted schemas commonly bind a small constellation of "extra"
    # fields that the registry/Drizzle schema doesn't declare — avatar URLs,
    # contact info, location, employment metadata, totals/counters. Provide
    # plausible placeholders so the bindings resolve to a real value rather
    # than a literal Mustache template at render time. `setdefault` guarantees
    # we never overwrite an actual field the entity defines.
    name = record.get("name") if isinstance(record.get("name"), str) else None
    if name:
        # Stable, deterministic avatar URL derived from the name. ui-avatars
        # is a well-known free placeholder service that returns initials-
        # styled images — works without an API key, doesn't hot-link to
        # anything sensitive.
        from urllib.parse import quote as _quote
        out.setdefault("avatarUrl", f"https://ui-avatars.com/api/?name={_quote(name)}&size=128")
        out.setdefault("avatar", out.get("avatarUrl"))
        out.setdefault("avatarInitials", "".join(w[:1].upper() for w in name.split()[:2]))
    out.setdefault("phone", "+1 (555) 010-0100")
    out.setdefault("location", "San Francisco, CA")
    out.setdefault("timezone", "America/Los_Angeles")
    out.setdefault("jobTitle", record.get("role") or "Member")
    out.setdefault("title", out.get("jobTitle"))
    out.setdefault("tenureYears", 2)
    out.setdefault("employmentType", "full-time")
    out.setdefault("employeeId", record.get("id", ""))
    out.setdefault("directReportsCount", 0)
    out.setdefault("totalDays", record.get("daysRequested", 0))
    out.setdefault("leaveBalance", 15)
    out.setdefault("leaveUsedYTD", 5)
    out.setdefault("emergencyContact", "Jane Doe — +1 (555) 010-0101")
    # Most LLM-emitted "list" pages assume each row has a status. If the
    # entity didn't declare one (User typically doesn't), default to "active"
    # so Avatar/Badge `status` bindings render a real value.
    out.setdefault("status", "active")
    # `startDate` is commonly used as an HR-style join-date / start-of-tenure.
    # Mirror createdAt when present, otherwise leave it to the generic fall-
    # back below.
    if "createdAt" in record:
        out.setdefault("startDate", record["createdAt"])

    # Synthetic `manager` join for person-like records (those with both `name`
    # and `email`). The LLM consistently expects a `manager` on user/employee
    # rows; without a real schema FK to drive enrichment, we pick a different
    # record from the same entity as a stand-in. Same fallback shape the FK
    # enrichment uses for cross-entity joins.
    if name and isinstance(record.get("email"), str):
        siblings = all_records_by_entity.get(entity_name) or []
        for cand in siblings:
            if cand.get("id") != record.get("id"):
                out.setdefault("manager", cand)
                out.setdefault("supervisor", cand)
                out.setdefault("reportsTo", cand)
                break

    # --- Field aliases (entity-agnostic) ---
    aliases = {
        "type":           ("leaveType", "requestType", "category", "kind"),
        "daysRequested":  ("durationDays", "days", "duration"),
        "submittedAt":    ("submittedDate", "submitted"),
        "createdAt":      ("createdDate", "created"),
        "updatedAt":      ("updatedDate", "updated", "lastModified"),
        "approvedAt":     ("approvedDate"),
        "startDate":      ("start", "from"),
        "endDate":        ("end", "to", "until"),
        "name":           ("displayName", "fullName", "label"),
        "email":          ("emailAddress",),
        "department":     ("dept", "team"),
        "role":           ("title", "jobTitle"),
        "status":         ("state",),
        "amount":         ("price", "total", "value"),
        "reason":         ("description", "note", "notes"),
    }
    for src_field, alias_tuple in aliases.items():
        if src_field not in record:
            continue
        # Allow `aliases` value to be a single string or tuple of strings
        targets = (alias_tuple,) if isinstance(alias_tuple, str) else alias_tuple
        for alias_name in targets:
            out.setdefault(alias_name, record[src_field])

    return out


@router.get("/api/_debug/preview-data/{short_id}")
async def get_preview_data(short_id: str):
    """Return fixture data for every entity in the project, for use in
    the editor + render-scaffold preview. Pure Python, no LLM, ~10-50ms."""
    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    proj = output_root / short_id
    if not proj.exists():
        raise HTTPException(404, f"project {short_id} not found")

    # Load entities from registry.json (preferred) or app-model.json (fallback)
    registry_path = proj / "src" / "contracts" / "registry.json"
    app_model_path = proj / "src" / "contracts" / "app-model.json"
    design_spec_path = proj / "src" / "contracts" / "design-spec.json"

    # Determine domain from design-spec.json
    domain = "general"
    if design_spec_path.exists():
        try:
            design_spec = json.loads(design_spec_path.read_text())
            raw_domain = design_spec.get("domain") or design_spec.get("register") or "general"
            # Register names are design registers, not fixture domains — map to closest domain
            register_to_domain = {
                "workday": "hr",
                "linear": "general",
                "stripe": "fintech",
                "notion": "general",
                "figma": "general",
                "default": "general",
            }
            domain = register_to_domain.get(raw_domain, raw_domain)
        except json.JSONDecodeError:
            pass

    # Build entity list; also always parse app-model for overview metadata.
    entities: dict = {}
    app_model_name: str = ""
    app_model_description: str = ""

    if app_model_path.exists():
        try:
            app_model = json.loads(app_model_path.read_text())
            app_model_name = app_model.get("name", "") or ""
            app_model_description = app_model.get("description", "") or ""
            raw_entities = app_model.get("entities", {})
            if isinstance(raw_entities, dict):
                # app-model entities don't have fields arrays — just names
                entities = {name: {} for name in raw_entities}
        except json.JSONDecodeError:
            pass

    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text())
            reg_entities = registry.get("entities", {})
            if isinstance(reg_entities, dict) and reg_entities:
                # Registry is more complete (has field defs) — prefer it
                entities = reg_entities
        except json.JSONDecodeError:
            pass

    # THE BLUEPRINT, WHEN THE LEGACY CONTRACTS ARE NOT THERE.
    #
    # registry.json, app-model.json and design-spec.json are written by
    # routers/generate.py. `services/blueprint/` writes none of the three, so
    # a Blueprint-generated application arrived here with no entities and the
    # visual editors showed an empty project — the schemas were on disk at
    # app/src/schemas/*.json the whole time, and the manifest the editor looks
    # for was simply never produced.
    #
    # An adapter rather than a fourth contract file: the Blueprint stays
    # authoritative and the editor reads a projection of it, so the two cannot
    # drift. Emitting registry.json from the Blueprint pipeline would have been
    # a third copy of facts the Blueprint already holds, and every copy drifts.
    if not entities:
        blueprint_path = proj / ".forge" / "blueprint" / "current.json"
        if blueprint_path.is_file():
            try:
                doc = json.loads(blueprint_path.read_text())
            except (OSError, json.JSONDecodeError):
                doc = {}
            app = doc.get("application") or {}
            app_model_name = app_model_name or app.get("name", "") or ""
            app_model_description = (
                app_model_description or app.get("description", "") or ""
            )
            if domain == "general":
                domain = (app.get("domain") or "general").lower()
            for ent in ((doc.get("data") or {}).get("entities") or []):
                name = ent.get("name")
                if not name or ent.get("status") == "SUPERSEDED":
                    continue
                # The registry shape: a field list per entity, which is what
                # the fixture generator reads to invent plausible rows.
                entities[str(name)] = {
                    "fields": [
                        {"name": f.get("name"), "type": f.get("type") or "text"}
                        for f in (ent.get("fields") or [])
                        if isinstance(f, dict) and f.get("name")
                    ],
                }

    if not entities:
        return {}

    from services.fixtures.dispatcher import provide_records_async
    from services.fixtures.types import FieldHint
    import re as _re

    def _infer_hints_from_schema_file(proj_root: Path, entity_name: str) -> list[FieldHint]:
        """Try to extract field hints from the Drizzle schema TS file for entity_name.

        Converts PascalCase entity name → kebab-case filename, reads the file if it
        exists, and extracts camelCase column names from pgTable column definitions.
        E.g. `LeaveRequest` → `leave-request.ts`, finds lines like
          `userId: uuid("user_id")` → FieldHint("userId", "string").
        Returns an empty list if the file is absent or parsing fails.
        """
        # Convert PascalCase → kebab-case
        kebab = _re.sub(r"(?<!^)(?=[A-Z])", "-", entity_name).lower()
        candidates = [
            proj_root / "src" / "db" / "schema" / f"{kebab}.ts",
            proj_root / "src" / "db" / "schema" / f"{entity_name.lower()}.ts",
        ]
        ts_text = None
        for c in candidates:
            if c.exists():
                ts_text = c.read_text(errors="ignore")
                break
        if ts_text is None:
            return []

        # Match lines like `  fieldName: type("col_name"...` inside pgTable({...})
        hints = []
        drizzle_type_to_fixture = {
            "uuid": "string", "varchar": "string", "text": "string",
            "integer": "integer", "int": "integer", "bigint": "integer",
            "boolean": "boolean", "bool": "boolean",
            "date": "string", "timestamp": "string",
            "jsonb": "string", "json": "string",
            "decimal": "number", "numeric": "number", "real": "number", "doublePrecision": "number",
        }
        for line in ts_text.splitlines():
            m = _re.match(r"^([a-zA-Z][a-zA-Z0-9_]+)\s*:\s*([a-zA-Z]+)\s*\(", line.strip())
            if m:
                field_name = m.group(1)
                drizzle_type = m.group(2)
                if field_name in ("pgTable", "primaryKey", "foreignKey", "index", "unique"):
                    continue
                fixture_type = drizzle_type_to_fixture.get(drizzle_type, "string")
                hints.append(FieldHint(name=field_name, type=fixture_type))
        return hints

    # First pass: generate raw fixture records per entity.
    #
    # Per-entity work is independent, so on cache miss we fire the LLM calls
    # concurrently via `asyncio.gather`. Awaiting the async dispatcher
    # directly (rather than bridging through `asyncio.to_thread`) keeps the
    # Claude Agent SDK's subprocess pipes on the route's own event loop,
    # which is the only context where they reliably stream stdout back.
    # Total wall-clock for a cold project: ~max(T) where T is the slowest
    # LLM call (~5-25s on first SDK warm-up, ~2-5s thereafter). Subsequent
    # calls hit the per-project on-disk cache and return in <1ms.
    import asyncio as _asyncio
    entity_payloads = []
    for entity_name, entity_def in entities.items():
        fields_def = entity_def.get("fields", []) if isinstance(entity_def, dict) else []
        if not isinstance(fields_def, list):
            fields_def = []
        hints = []
        for f in fields_def:
            if isinstance(f, dict) and "name" in f:
                hints.append(FieldHint(name=f["name"], type=f.get("type", "string")))
        if not hints:
            hints = _infer_hints_from_schema_file(proj, entity_name)
        entity_payloads.append((entity_name, hints))

    async def _gen(entity_name: str, hints):
        return entity_name, await provide_records_async(
            domain=domain,
            entity_name=entity_name,
            fields=hints,
            count=10,
            project_root=proj,
        )

    # Parallel — the regular Anthropic HTTP SDK is concurrent-safe (it's
    # httpx-based), so per-entity calls fire simultaneously. Total wall-clock
    # for a cold project ≈ max(T) where T is the slowest LLM round-trip
    # (typically 2-5s for Sonnet on 10 records). After the first request,
    # all calls hit the per-project on-disk cache and return in <1ms total.
    raw: dict[str, list[dict]] = {}
    for entity_name, records in await _asyncio.gather(
        *[_gen(name, hints) for name, hints in entity_payloads]
    ):
        raw[entity_name] = records

    # Second pass: apply only the metadata-default + field-alias enrichments
    # (no FK joins yet). This produces records that already carry `avatarUrl`,
    # `status`, `manager`, `leaveType` etc. — so the third-pass FK lookup
    # joins records that are already complete. Without this split, a join
    # like `leaveRequest.employee.avatarUrl` resolves the User record but
    # finds no `avatarUrl` because the join used the un-enriched record.
    enriched_first: dict[str, list[dict]] = {}
    for entity_name, records in raw.items():
        enriched_first[entity_name] = [
            _enrich_record(r, entity_name, raw, fk_joins=False) for r in records
        ]

    # Third pass: apply FK joins against the metadata-enriched record set.
    # Now `leaveRequest.employee.avatarUrl` etc. resolves through both layers.
    data: dict = {}
    for entity_name, records in enriched_first.items():
        enriched = [
            _enrich_record(r, entity_name, enriched_first, fk_joins=True)
            for r in records
        ]
        data[entity_name] = enriched
        data[entity_name.lower()] = enriched
        plural_key = entity_name[0].lower() + entity_name[1:]
        if not plural_key.endswith("s"):
            plural_key += "s"
        data[plural_key] = enriched

    # Enum enrichment — distribute the values the page schemas actually expect
    # (aggregate metric filters + series groupBy columns) across each entity's
    # rows, so dashboard KPI tiles read non-zero and charts get multiple buckets
    # instead of one. Editor-preview only; runs before stats so they reflect it.
    try:
        from services.fixtures.enum_enrich import enrich_preview_data
        enrich_preview_data(data, str(proj / "src" / "schemas"))
    except Exception:
        pass

    # Synthesize a "stats" object — many generated schemas reference {{stats.X}}
    # for dashboard metrics. Only iterate over PascalCase keys (the canonical entity
    # names) to avoid double-counting records stored under alias keys.
    entity_names_unique = [k for k in data if k and k[0].isupper()]
    stats: dict = {
        "totalCount": sum(len(data[k]) for k in entity_names_unique if isinstance(data[k], list)),
    }
    # Track broader active/pending counts across all entity records.
    _active_vocab = {"active", "approved", "open"}
    _pending_vocab = {"pending", "in-review", "awaiting"}
    _broad_active = 0
    _broad_pending = 0
    for entity_name in entity_names_unique:
        records = data[entity_name]
        if not isinstance(records, list) or not records:
            continue
        stats[f"{entity_name.lower()}Count"] = len(records)
        if records and "status" in records[0]:
            for rec in records:
                status_val = rec.get("status", "unknown")
                key = f"{status_val.lower()}Count" if isinstance(status_val, str) else "unknownCount"
                stats[key] = stats.get(key, 0) + 1
                if isinstance(status_val, str):
                    sv = status_val.lower()
                    if sv in _active_vocab:
                        _broad_active += 1
                    elif sv in _pending_vocab:
                        _broad_pending += 1
        if records and "amount" in records[0]:
            amounts = [r["amount"] for r in records if isinstance(r.get("amount"), (int, float))]
            if amounts:
                stats["avgAmount"] = round(sum(amounts) / len(amounts), 2)
        if records and "remainingDays" in records[0]:
            days = [r["remainingDays"] for r in records if isinstance(r.get("remainingDays"), (int, float))]
            if days:
                stats["avgRemainingDays"] = round(sum(days) / len(days), 1)

    # Synthesize delta/trend pairs for every count-style stat. The LLM emits
    # `{{stats.<status>Delta}}` and `{{stats.<status>Trend}}` for MetricTile
    # delta indicators; without these aliases those bindings render as literal
    # template strings in the rendered page. Faked but plausible values keep
    # the visual target accurate (a real period-over-period delta would
    # require historical data this endpoint doesn't have).
    import random as _random
    rng = _random.Random(short_id)  # stable per project across calls
    for key in list(stats.keys()):
        if not isinstance(key, str) or not key.endswith("Count"):
            continue
        base = key[:-len("Count")]
        # Delta as a fraction in [-0.25, +0.25] — MetricTile.formatDelta
        # renders this as a percent ("+12%" / "−8%").
        if f"{base}Delta" not in stats:
            stats[f"{base}Delta"] = round(rng.uniform(-0.25, 0.25), 3)
        if f"{base}Trend" not in stats:
            d = stats[f"{base}Delta"]
            stats[f"{base}Trend"] = "up" if d > 0.02 else ("down" if d < -0.02 else "flat")

    # Common LLM-emitted "aggregate" aliases that don't always map to real
    # numeric fields. Fall back to a plausible default so MetricTile bindings
    # like `{{stats.avgRemainingDays}}` resolve to a number rather than a
    # literal template.
    stats.setdefault("avgRemainingDays", round(rng.uniform(8, 18), 1))
    stats.setdefault("avgDuration", round(rng.uniform(2, 7), 1))
    stats.setdefault("growthRate", round(rng.uniform(0.05, 0.18), 3))
    # Schemas routinely show an "Overdue" tile that bindings to overdueCount.
    # The fixture LLM doesn't emit a date-derived overdue count, so without
    # this default the tile renders as a literal template. Pick a small
    # plausible number — same deterministic seed so it's stable per project.
    stats.setdefault("overdueCount", rng.randint(0, 5))
    stats.setdefault("dueTodayCount", rng.randint(0, 4))
    stats.setdefault("dueSoonCount", rng.randint(2, 8))
    stats.setdefault("unassignedCount", rng.randint(0, 3))

    # Broader active/pending vocabulary — fall back to rng if no matching records found.
    stats.setdefault("activeCount", _broad_active if _broad_active > 0 else rng.randint(5, 50))
    stats.setdefault("pendingCount", _broad_pending if _broad_pending > 0 else rng.randint(2, 15))

    # Monthly metrics — stable per project via the seeded rng.
    _monthly_count = rng.randint(10, 80)
    _monthly_change = round(rng.uniform(-0.20, 0.30), 3)
    _monthly_trend = "up" if _monthly_change > 0.02 else ("down" if _monthly_change < -0.02 else "flat")
    stats.setdefault("monthlyCount", _monthly_count)
    stats.setdefault("monthlyChange", _monthly_change)
    stats.setdefault("monthlyTrend", _monthly_trend)

    data["stats"] = stats

    # Per-entity stats objects (`<entity>Stats`) — many LLM-emitted schemas
    # bind `{{userStats.X}}` / `{{leaveRequestStats.Y}}` rather than the
    # global `{{stats.X}}`. Synthesize them from the same numbers so the
    # bindings resolve to a real value instead of a literal template. Adds
    # both the camelCase (`userStats`) and PascalCase (`UserStats`) keys for
    # robustness against the LLM's casing variance.
    for entity_name in entity_names_unique:
        records = data.get(entity_name)
        if not isinstance(records, list):
            continue
        camel = entity_name[:1].lower() + entity_name[1:]
        entity_stats = {
            "total":          stats.get(f"{entity_name.lower()}Count", len(records)),
            "count":          len(records),
            "active":         stats.get("activeCount", 0),
            "archived":       stats.get("archivedCount", 0),
            # Heuristic numerics — same pattern the global `stats` synth uses.
            "averageTenure":  round(rng.uniform(1.5, 6.0), 1),
            "departmentCount": rng.randint(3, 12),
            "growthRate":     round(rng.uniform(0.05, 0.18), 3),
            "delta":          round(rng.uniform(-0.15, 0.20), 3),
        }
        # Trend mirrors delta sign — same convention as the global stats.
        entity_stats["trend"] = (
            "up" if entity_stats["delta"] > 0.02
            else "down" if entity_stats["delta"] < -0.02
            else "flat"
        )
        # Pull through any matching `<status>Count` keys from the global stats
        # since LLM dashboards often show status breakdowns per entity.
        for k, v in stats.items():
            if isinstance(k, str) and k.endswith("Count") and k != f"{entity_name.lower()}Count":
                entity_stats[k] = v
        data[f"{camel}Stats"] = entity_stats
        data[f"{entity_name}Stats"] = entity_stats

    # Expose common user binding targets
    data["currentUser"] = (data.get("users") or data.get("Users") or [{}])[0]
    data["user"] = data.get("currentUser", {})

    # Overview — provides {{overview.title}} / {{overview.description}} bindings
    # used by generated dashboard headers. Falls back to short_id if app-model
    # was absent or did not contain a name.
    data["overview"] = {
        "title": app_model_name or short_id,
        "description": app_model_description,
    }

    return data


_EXPORT_EXCLUDE_DIRS = {"node_modules", ".next", ".git", "out", ".fixtures-cache", ".design", "__pycache__"}


@router.get("/api/_debug/project-export/{short_id}")
async def export_project_debug(short_id: str):
    """Stream a tarball of the project's output directory.

    Excludes node_modules / .next / .git / build caches. The user
    extracts the tarball, runs `npm install && npm run dev`, and has
    a working standalone Next.js app powered by @tentoroforge/engine.
    """
    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    project_dir = (output_root / short_id).resolve()
    if not str(project_dir).startswith(str(output_root.resolve())):
        raise HTTPException(403, "path traversal blocked")
    if not project_dir.exists():
        raise HTTPException(404, f"project not found: {short_id}")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in project_dir.rglob("*"):
            if any(part in _EXPORT_EXCLUDE_DIRS for part in p.parts):
                continue
            if p.is_file():
                # arcname relative to the project directory so extraction
                # produces <short_id>/... at the user's cwd
                rel = p.relative_to(project_dir.parent)
                tf.add(p, arcname=str(rel))
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={
            "content-disposition": f'attachment; filename="{short_id}.tar.gz"',
        },
    )


@router.post("/api/_debug/project-ai-edit/{short_id}")
async def ai_edit_project(short_id: str, request: Request):
    """Run the peer patcher against the project's current artifacts +
    a user prompt; stream SSE events back. The final 'artifacts' event
    contains the proposed updated bundle for the editor to commit.

    No auth — matches the other /api/_debug/ routes used by the editor.
    """
    from agents.peer_patcher import run_peer_patcher
    from services.peer_patcher_helpers import (
        load_current_artifacts, registry_snapshot,
        registry_digest, token_vocabulary,
    )

    body = await request.json()
    user_prompt = (body or {}).get("prompt", "").strip()
    if not user_prompt:
        raise HTTPException(400, "prompt is required")

    output_root = Path(__file__).resolve().parent.parent.parent / "output"
    project_dir = (output_root / short_id).resolve()
    if not str(project_dir).startswith(str(output_root.resolve())):
        raise HTTPException(403, "path traversal blocked")
    if not project_dir.exists():
        raise HTTPException(404, f"project not found: {short_id}")

    current = load_current_artifacts(str(project_dir))

    async def event_stream():
        try:
            async for evt in run_peer_patcher(
                user_prompt=user_prompt,
                current_artifacts=current,
                registry_digest=registry_digest(),
                registry=registry_snapshot(),
                token_vocabulary=token_vocabulary(current),
                max_retries=2,
            ):
                yield {"event": evt.get("event", "log"), "data": json.dumps(evt.get("data", {}), default=str)}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"text": f"AI edit failed: {e}"})}

    return EventSourceResponse(event_stream())


@router.get("/api/_debug/project-file/{short_id}/{file_path:path}")
async def get_project_file(short_id: str, file_path: str):
    """Serve arbitrary text files from output/<short_id>/. Read-only, dev-only.

    Used by the editor UI to read project-level files (e.g. design-spec.json)
    without needing a dedicated DB-backed endpoint.

    Security: path traversal is blocked — the resolved path must stay under
    output/<short_id>/. Requests that escape that boundary get 403.
    """
    base_dir = await _resolve_project_base(short_id)
    full = (base_dir / file_path).resolve()
    # Block path traversal
    if not str(full).startswith(str(base_dir.resolve())):
        raise HTTPException(403, "path traversal blocked")
    # THE GENERATED APP IS A SUBDIRECTORY. The Blueprint's projections write to
    # `<output_dir>/app/src/...` while this resolves `<output_dir>/src/...`, and
    # both directories exist — the output root has its own `src`, so nothing
    # looked obviously wrong. Every editor reads its content through here, so
    # nav-flow.json, the schemas and the design spec all 404'd and each panel
    # opened empty for an application whose files were one directory away.
    #
    # Tried second rather than instead: the output root legitimately holds
    # app-model.json and navigation.json, and a caller asking for those must
    # keep getting them. Only a miss falls through to the app.
    if not full.exists():
        nested = (base_dir / "app" / file_path).resolve()
        if str(nested).startswith(str((base_dir / "app").resolve())) \
                and nested.exists():
            full = nested
    # Lazy fallback: the editor's Canvas hard-depends on nav-flow.json to list
    # pages, but apps generated before the plan-driven emitter (or a run where
    # that emit failed) don't have one. Synthesize it from the schemas on first
    # request so any app — old or new — opens in the editor.
    if not full.exists() and file_path.replace("\\", "/") == "src/contracts/nav-flow.json":
        try:
            from services.nav_flow_from_schemas import ensure_nav_flow
            ensure_nav_flow(base_dir)
        except Exception:  # noqa: BLE001 — best-effort; fall through to 404 below
            pass
    if not full.exists():
        raise HTTPException(404, f"file not found: {file_path}")
    try:
        text = full.read_text()
    except Exception as e:
        raise HTTPException(500, f"read failed: {e}")
    if file_path.endswith(".json"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return PlainTextResponse(text)
    return PlainTextResponse(text)


@router.post("/api/_debug/project-file/{short_id}/{file_path:path}")
async def write_project_file(short_id: str, file_path: str, request: Request):
    """Write a text file under output/<short_id>/. Dev-only; mirrors the GET.

    Used by the visual editor's persister to save edited page schemas and
    contracts. Same path-traversal guard as the GET — the resolved path must
    stay under output/<short_id>/. Body: {"content": "<text>"}.
    """
    base_dir = await _resolve_project_base(short_id)
    base = base_dir.resolve()
    full = (base_dir / file_path).resolve()
    if not str(full).startswith(str(base)):
        raise HTTPException(403, "path traversal blocked")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON body")
    content = body.get("content")
    if not isinstance(content, str):
        raise HTTPException(400, "body.content (string) required")
    try:
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    except Exception as e:
        raise HTTPException(500, f"write failed: {e}")
    return {"ok": True, "path": file_path, "bytes": len(content)}
