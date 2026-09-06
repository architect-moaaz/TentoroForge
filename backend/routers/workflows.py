"""Workflow endpoints — CRUD for workflow definitions, assignment policies, runtime, and apply pipeline."""

import hashlib
import json
import logging
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import (
    AgentJob,
    AgentJobStatus,
    AgentType,
    Conversation,
    MessageRole,
    MessageType,
    Version,
)
from models.workflow import WorkflowAssignmentPolicy
from models.workflow_instance import (
    WorkflowInstance,
    WorkflowInstanceStatus,
    TaskInstance,
    TaskInstanceStatus,
)
from schemas.workflow import (
    AssignmentPolicyCreate,
    AssignmentPolicyResponse,
    AssignmentPolicyUpdate,
    WorkflowListItem,
    WorkflowSave,
    WorkflowStartRequest,
    TaskCompleteRequest,
    WorkflowInstanceResponse,
    WorkflowInstanceDetailResponse,
    TaskInstanceResponse,
    NodeExecutionLogResponse,
)
from services.project_service import get_project_with_auth
from services.git_service import git_commit
from sse_helpers import sse_event, stream_agent_messages

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workflows"])

WORKFLOWS_DIR = "workflows"  # relative to project output_dir


#: Where the Blueprint's `frontend` projection writes workflow definitions,
#: relative to the generated app. Kept in step with projection.py's own
#: `src/lib/workflows/definitions/{slug}.json`.
PROJECTED_WORKFLOWS_DIR = "app/src/lib/workflows/definitions"


def _workflows_path(output_dir: str) -> Path:
    """Where this project's workflows actually are.

    THE PROJECTION WRITES ONE PLACE AND THIS READ ANOTHER. A Blueprint-built
    application emits `app/src/lib/workflows/definitions/*.json`; this looked
    in `<output_dir>/workflows`, created it with the `mkdir` below, and
    returned an empty directory. The endpoint answered `200 []`, so the
    Workflows editor rendered nothing and nothing anywhere reported a problem
    — a project with four workflows on disk looked like a project with none.

    The projected directory wins when it exists. `<output_dir>/workflows`
    stays the fallback for legacy projects, which is the only thing that ever
    wrote there.
    """
    projected = Path(output_dir) / PROJECTED_WORKFLOWS_DIR
    if projected.is_dir():
        return projected
    p = Path(output_dir) / WORKFLOWS_DIR
    p.mkdir(exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Workflow definitions (stored as JSON files in the project)
# ---------------------------------------------------------------------------

def workflow_list_item(data: dict, stem: str) -> WorkflowListItem:
    """Build a list item for a workflow file.

    The id is ALWAYS the filename stem — the canonical id that get_workflow,
    delete_workflow, the /start endpoint and the runtime engine
    (``_load_definition`` → ``workflows/{id}.json``) all resolve by. The JSON's
    internal ``id`` field can diverge from the filename (e.g. a generated file
    ``<hash>.json`` whose body says ``"id": "<slug>"``); using it here made the
    listed id un-openable (404). Always surface the stem.
    """
    definition = data.get("definition", {}) or {}
    steps = definition.get("steps", []) or []
    nodes = definition.get("nodes", []) or []
    trigger = definition.get("trigger", {})
    # step_count: prefer the planner's `steps` when present; otherwise count the
    # operational nodes the editor stores (everything after the trigger).
    # Generated workflows carry `nodes`/`edges`/`trigger` and NO `steps`, so the
    # old `len(steps)` showed a wrong "0 steps" for every workflow in the list.
    if steps:
        step_count = len(steps)
    else:
        step_count = sum(
            1 for n in nodes
            if isinstance(n, dict) and (n.get("type") or "").lower() != "trigger"
        )
    return WorkflowListItem(
        id=stem,
        name=data.get("name", stem),
        description=data.get("description"),
        trigger_type=trigger.get("type") if isinstance(trigger, dict) else None,
        step_count=step_count,
    )


def canonical_workflow(data: dict, stem: str) -> dict:
    """Force a loaded workflow's ``id`` to its filename stem so clients edit and
    simulate it under the same id the engine loads it by (the stored ``id`` may
    diverge from the filename)."""
    data["id"] = stem
    return data


@router.get("/api/projects/{project_id}/workflows", response_model=list[WorkflowListItem])
async def list_workflows(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all workflow definitions for a project."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return []

    wf_dir = _workflows_path(project.output_dir)
    items = []
    for f in sorted(wf_dir.glob("*.json")):
        try:
            items.append(workflow_list_item(json.loads(f.read_text()), f.stem))
        except (json.JSONDecodeError, KeyError):
            continue
    return items


@router.get("/api/projects/{project_id}/workflows/{workflow_id}")
async def get_workflow(
    project_id: uuid.UUID,
    workflow_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single workflow definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    wf_file = _workflows_path(project.output_dir) / f"{workflow_id}.json"
    if not wf_file.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")

    return canonical_workflow(json.loads(wf_file.read_text()), workflow_id)


@router.post("/api/projects/{project_id}/workflows", status_code=201)
async def save_workflow(
    project_id: uuid.UUID,
    req: WorkflowSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a workflow definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    wf_file = _workflows_path(project.output_dir) / f"{req.id}.json"

    # A15-1 — optimistic concurrency.
    #
    # This was a bare whole-file overwrite: two editors (or an editor and a
    # chat-driven edit) saving the same workflow silently destroyed each
    # other's work, with no error and no way to tell it had happened. If the
    # caller tells us which version it read, refuse when the file has moved on.
    payload = req.model_dump()
    client_version = payload.pop("version", None)
    current_version = _workflow_version(wf_file)
    if client_version is not None and wf_file.exists() and client_version != current_version:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Workflow {req.id} changed on the server since you loaded it "
                f"(your version {client_version}, current {current_version}). "
                f"Reload and re-apply your edit — saving now would discard the "
                f"other change."
            ),
        )

    # A15-2 — the interactive save path ran NO validation.
    #
    # Every other write path (generation, self-heal, the fix applier) goes
    # through the graph gate, but a save from the editor wrote straight to disk.
    # So the editor could persist a workflow with no trigger, a dangling edge,
    # or an unknown actionType, and the first anyone heard of it was a runtime
    # failure in the generated app. Validate and report; do NOT silently repair
    # here — this is the author's own explicit save, so their content is
    # returned untouched and the problems are handed back to them.
    # Consult the pipeline's OWN guards at the route (register A15-2).
    #
    # Generation, self-heal and the fix applier all run these; the interactive
    # save consulted none of them and returned {'saved': True} regardless — so
    # the editor could persist a workflow the platform's own validator calls
    # non-executable. The checks live here, at the route that must refuse,
    # rather than buried in a helper.
    from services.workflow_executability import is_executable_workflow
    from services.workflow_graph_gate import validate_and_repair

    problems = _validate_for_save(payload)
    if not is_executable_workflow(payload):
        problems.append(
            "not executable — no action node performs real work (an action with "
            "no actionType/table, or a mutation whose values all resolve to "
            "NULL). This workflow will run and do nothing."
        )
    try:
        # Non-destructive: this is the author's explicit save, so report what
        # the gate WOULD change rather than rewriting their graph under them.
        _, _gate = validate_and_repair(
            {"definition": payload.get("definition") or {}}, drop_unreachable=False,
        )
        problems.extend(_gate.get("errors") or [])
        problems.extend(_gate.get("warnings") or [])
    except Exception as e:  # noqa: BLE001 — never block a save on the gate itself
        logger.warning("workflows.save_workflow: graph gate unavailable: %s", e)

    # Read-modify-WRITE, not blind overwrite.
    #
    # The route wrote `model_dump()` over the whole file, so any top-level key
    # the file carried that is not one of the contract fields was DESTROYED on
    # the first user edit, with no error. That was latent while nothing emitted
    # a sixth key — and then this change added `version`, which is exactly the
    # scenario qa case 15.3 was pinned to warn about. Merge over what is there
    # so an unknown key survives an edit that did not touch it.
    merged: dict = {}
    if wf_file.exists():
        try:
            existing = json.loads(wf_file.read_text())
            if isinstance(existing, dict):
                merged.update(existing)
        except (OSError, ValueError) as e:
            logger.warning(
                "workflows.save_workflow: %s exists but is unreadable (%s) — "
                "saving without preserving its previous contents.", req.id, e,
            )
    merged.update(payload)

    wf_file.write_text(json.dumps(merged, indent=2))

    # A15-4 — both interactive write paths now record history identically.
    #
    # patch_workflow_node committed to git; save_workflow did not. So a node
    # patch was recoverable and a full save was not, which is exactly backwards
    # — the full save is the more destructive of the two.
    try:
        git_commit(project.output_dir, f"edit(workflow): save {req.id}",
                   actor="editor",
                   # SX-3: stage only the workflow this request wrote. Without
                   # `paths` git_commit falls back to `git add -A`, sweeping any
                   # unrelated work in progress under output_dir into this
                   # commit.
                   paths=[str(Path(wf_file).relative_to(project.output_dir))])
    except Exception:
        pass

    return {
        "id": req.id,
        "saved": True,
        "version": _workflow_version(wf_file),
        "problems": problems,
    }


def _workflow_version(wf_file: Path) -> str | None:
    """A cheap content version for optimistic concurrency: the sha256 of the
    bytes on disk. Content-based rather than mtime-based so it is stable across
    filesystems and no-op rewrites."""
    try:
        return hashlib.sha256(wf_file.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def _validate_for_save(payload: dict) -> list[str]:
    """Structural problems with a workflow the editor is about to persist.

    Reported, never silently repaired: this is the author's explicit save, so
    rewriting their graph under them would be worse than telling them. Returns
    [] when the workflow is clean."""
    problems: list[str] = []
    definition = payload.get("definition")
    if not isinstance(definition, dict):
        return ["definition is missing or not an object"]

    nodes = definition.get("nodes")
    edges = definition.get("edges")
    if not isinstance(nodes, list) or not nodes:
        problems.append("definition.nodes is empty — this workflow cannot run")
        nodes = []
    if not isinstance(edges, list):
        problems.append("definition.edges is not a list")
        edges = []

    ids = {n.get("id") for n in nodes if isinstance(n, dict) and n.get("id")}
    idless = sum(1 for n in nodes if not (isinstance(n, dict) and n.get("id")))
    if idless:
        problems.append(f"{idless} node(s) have no id and can never be reached")
    if nodes and not any(
        isinstance(n, dict) and n.get("type") == "trigger" for n in nodes
    ):
        problems.append("no trigger node — the workflow has no entry point")

    for e in edges:
        if not isinstance(e, dict):
            continue
        for end in ("source", "target"):
            ref = e.get(end)
            if ref and ref not in ids:
                problems.append(f"edge {end} {ref!r} does not name a node in this workflow")

    if problems:
        logger.warning(
            "workflows.save_workflow: %s saved with %d structural problem(s): %s",
            payload.get("id"), len(problems), "; ".join(problems),
        )
    return problems


class WorkflowNodePatch(BaseModel):
    """Partial update to a single workflow node — merges into node.data.config."""
    config: dict | None = None
    label: str | None = None


def _find_node(definition: dict, node_id: str) -> dict | None:
    for n in (definition.get("nodes") or []):
        if isinstance(n, dict) and (n.get("id") == node_id or (n.get("data") or {}).get("id") == node_id):
            return n
    return None


def merge_node_config(
    definition: dict,
    node_id: str,
    config: dict | None = None,
    label: str | None = None,
) -> dict | None:
    """Shallow-merge ``config`` into a workflow node's ``data.config`` (and, when
    given, set ``data.label``). Returns the mutated node dict, or ``None`` when the
    node isn't found. Pure in-memory — mutates ``definition`` in place, no I/O.

    This is the single deterministic node-config edit seam: the node PATCH route
    and the fix-applier both call it so they merge identically."""
    node = _find_node(definition, node_id)
    if node is None:
        return None
    node_data = node.setdefault("data", {})
    if config:
        cfg = node_data.setdefault("config", {})
        _deep_merge(cfg, config)
    if label is not None:
        node_data["label"] = label
    return node


def _deep_merge(target: dict, patch: dict) -> None:
    """Recursively merge ``patch`` into ``target`` in place.

    `cfg.update(patch)` was a SHALLOW merge, so patching one key inside a nested
    object REPLACED the whole object (register A15-3). Editing a single entry of
    `values` or `where` — which is what the properties panel does — silently
    dropped every other column in that map, so an update workflow quietly
    stopped writing the fields the author never touched.

    An explicit ``None`` still clears a key: that is how the panel removes one.
    A list is replaced wholesale, since merging positionally would be a guess.
    """
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge(target[k], v)
        else:
            target[k] = v


@router.patch("/api/projects/{project_id}/workflows/{workflow_id}/nodes/{node_id}")
async def patch_workflow_node(
    project_id: uuid.UUID,
    workflow_id: str,
    node_id: str,
    req: WorkflowNodePatch,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Patch a single workflow node's config (e.g. change an ai_extract prompt or
    fields). Deterministic merge — the same seam the editor and chat both use to
    edit node config without regenerating the whole workflow."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    wf_file = _workflows_path(project.output_dir) / f"{workflow_id}.json"
    if not wf_file.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")

    data = json.loads(wf_file.read_text())
    definition = data.get("definition") or {}
    node = merge_node_config(definition, node_id, req.config, req.label)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found in workflow")

    node_data = node.get("data") or {}

    wf_file.write_text(json.dumps(data, indent=2))
    try:
        git_commit(project.output_dir, f"edit(workflow): patch node {node_id} in {workflow_id}",
                   actor="editor",   # S24-9
                   # SX-3: only the patched workflow, not the whole tree.
                   paths=[str(Path(wf_file).relative_to(project.output_dir))])
    except Exception:
        pass
    return {"id": workflow_id, "nodeId": node_id, "config": node_data.get("config", {})}


@router.delete("/api/projects/{project_id}/workflows/{workflow_id}", status_code=204)
async def delete_workflow(
    project_id: uuid.UUID,
    workflow_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a workflow definition."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    wf_file = _workflows_path(project.output_dir) / f"{workflow_id}.json"
    if wf_file.exists():
        wf_file.unlink()


# ---------------------------------------------------------------------------
# Apply workflow to generated app code
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/workflows/{workflow_id}/apply")
async def apply_workflow(
    project_id: uuid.UUID,
    workflow_id: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply workflow engine template to the generated app (deterministic copy, no AI)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    wf_file = _workflows_path(project.output_dir) / f"{workflow_id}.json"
    if not wf_file.exists():
        raise HTTPException(status_code=404, detail="Workflow not found")

    wf_data = json.loads(wf_file.read_text())

    async def event_stream():
        yield sse_event("status", {"message": f"Applying workflow: {wf_data.get('name', workflow_id)}..."})

        try:
            started_at = datetime.now(timezone.utc)
            output_dir = Path(project.output_dir)
            template_dir = Path(__file__).resolve().parent.parent / "templates"

            # 1. Copy workflow engine template → src/lib/workflow-engine/
            yield sse_event("status", {"message": "Copying workflow engine template..."})
            engine_src = template_dir / "workflow-engine"
            engine_dst = output_dir / "src" / "lib" / "workflow-engine"
            shutil.copytree(str(engine_src), str(engine_dst), dirs_exist_ok=True)

            # 2. Copy API routes template → src/app/api/workflows/
            yield sse_event("status", {"message": "Copying workflow API routes..."})
            routes_src = template_dir / "workflow-api-routes"
            routes_dst = output_dir / "src" / "app" / "api" / "workflows"
            shutil.copytree(str(routes_src), str(routes_dst), dirs_exist_ok=True)

            # 3. Copy instrumentation.ts template
            yield sse_event("status", {"message": "Copying instrumentation template..."})
            instrumentation_src = template_dir / "instrumentation.ts"
            instrumentation_dst = output_dir / "src" / "instrumentation.ts"
            if instrumentation_src.exists():
                shutil.copy2(str(instrumentation_src), str(instrumentation_dst))

            # 4. Append workflow schema re-exports to src/db/schema.ts
            yield sse_event("status", {"message": "Adding workflow schema exports..."})
            schema_file = output_dir / "src" / "db" / "schema.ts"
            if schema_file.exists():
                schema_content = schema_file.read_text()
                wf_export_line = "export { wfInstances, wfTaskInstances, wfExecutionLogs, wfInstancesRelations, wfTaskInstancesRelations, wfExecutionLogsRelations } from '@/lib/workflow-engine/infrastructure/schema';"
                if "wfInstances" not in schema_content:
                    schema_file.write_text(schema_content.rstrip() + "\n\n" + wf_export_line + "\n")

            # 5. Add @anthropic-ai/sdk as optional dependency in package.json
            yield sse_event("status", {"message": "Updating dependencies..."})
            pkg_file = output_dir / "package.json"
            if pkg_file.exists():
                pkg_data = json.loads(pkg_file.read_text())
                deps = pkg_data.setdefault("dependencies", {})
                if "@anthropic-ai/sdk" not in deps:
                    deps["@anthropic-ai/sdk"] = "^0.39.0"
                    pkg_file.write_text(json.dumps(pkg_data, indent=2) + "\n")
                    # Install the new dependency
                    subprocess.run(
                        ["npm", "install"],
                        cwd=str(output_dir),
                        capture_output=True,
                        timeout=120,
                    )

            # 6. Run drizzle-kit push to create workflow tables
            yield sse_event("status", {"message": "Pushing workflow tables to database..."})
            push_result = subprocess.run(
                ["npx", "drizzle-kit", "push", "--force"],
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if push_result.returncode != 0:
                yield sse_event("status", {"message": f"DB push warning: {push_result.stderr[:200]}"})

            # 7. Run npm run build to verify
            yield sse_event("status", {"message": "Verifying build..."})
            build_result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(output_dir),
                capture_output=True,
                text=True,
                timeout=180,
            )
            if build_result.returncode != 0:
                yield sse_event("status", {"message": f"Build warning: {build_result.stderr[:300]}"})

            # 8. Git commit
            commit_hash = await git_commit(project.output_dir,
                f"workflow: apply engine template",
            actor="editor")

            completed_at = datetime.now(timezone.utc)
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=f"Apply workflow engine template for '{wf_data.get('name', workflow_id)}'",
                    result={
                        "intent": "WORKFLOW_APPLY",
                        "workflow_id": workflow_id,
                        "method": "template_copy",
                        "num_turns": 0,
                        "cost_usd": 0,
                        "duration_ms": duration_ms,
                    },
                    started_at=started_at,
                    completed_at=completed_at,
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message=f"workflow: apply engine template",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                assistant_msg = Conversation(
                    project_id=project.id,
                    role=MessageRole.assistant,
                    content=f"Applied workflow engine template for: {wf_data.get('name', workflow_id)}",
                    message_type=MessageType.chat,
                    metadata_={
                        "intent": "WORKFLOW_APPLY",
                        "workflow_id": workflow_id,
                        "commit_hash": commit_hash,
                    },
                )
                sess.add(assistant_msg)
                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "workflow_id": workflow_id,
                "method": "template_copy",
                "num_turns": 0,
                "cost_usd": 0,
                "duration_ms": duration_ms,
                "commit_hash": commit_hash,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


async def _resolve_linked_pages(
    wf_data: dict,
    project_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, dict]:
    """For each node with a pageId, fetch the page definition.

    Returns: {node_id: {name, route, html, fields: [...]}} where fields
    are extracted from data-* attributes on form elements in the HTML.
    """
    from models.page import PageDefinition
    import re

    definition = wf_data.get("definition", {})
    nodes = definition.get("nodes", [])

    page_ids: set[str] = set()
    node_page_map: dict[str, str] = {}  # node_id -> page_id

    for node in nodes:
        config = node.get("data", {}).get("config", {})
        page_id = config.get("pageId")
        if page_id:
            page_ids.add(page_id)
            node_page_map[node.get("id", "")] = page_id

    if not page_ids:
        return {}

    # Fetch pages from DB
    result = await db.execute(
        select(PageDefinition).where(
            PageDefinition.project_id == project_id,
            PageDefinition.id.in_([uuid.UUID(pid) for pid in page_ids]),
        )
    )
    pages_by_id = {str(p.id): p for p in result.scalars().all()}

    # Extract form field metadata from data-* attributes in HTML
    linked: dict[str, dict] = {}
    for node_id, page_id in node_page_map.items():
        page = pages_by_id.get(page_id)
        if not page:
            continue

        fields = _extract_form_fields_from_html(page.html or "")
        linked[node_id] = {
            "name": page.name,
            "route": page.route,
            "html": page.html,
            "fields": fields,
        }

    return linked


def _extract_form_fields_from_html(html: str) -> list[dict]:
    """Parse data-* attributes from form elements to get field metadata."""
    import re

    fields: list[dict] = []
    # Match elements with data-field-name attribute
    pattern = re.compile(
        r'<[^>]*'
        r'data-field-name=["\']([^"\']*)["\']'
        r'[^>]*>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(html):
        tag = match.group(0)
        field: dict = {"fieldName": match.group(1)}

        # Extract other data-* attributes
        for attr, key in [
            ("data-required", "required"),
            ("data-process-variable", "processVariable"),
            ("data-help-text", "helpText"),
            ("data-min-length", "minLength"),
            ("data-max-length", "maxLength"),
            ("data-min", "min"),
            ("data-max", "max"),
            ("data-pattern", "pattern"),
            ("data-options", "options"),
        ]:
            attr_match = re.search(
                rf'{attr}=["\']([^"\']*)["\']', tag, re.IGNORECASE
            )
            if attr_match:
                val = attr_match.group(1)
                if attr == "data-required":
                    field[key] = val.lower() in ("true", "1", "on", "data-required")
                else:
                    field[key] = val

        # Detect input type from the tag
        type_match = re.search(r'type=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        if type_match:
            field["type"] = type_match.group(1)
        elif "<textarea" in tag.lower():
            field["type"] = "textarea"
        elif "<select" in tag.lower():
            field["type"] = "select"

        if field.get("fieldName"):
            fields.append(field)

    return fields


def _build_workflow_instruction(wf_data: dict, linked_pages: dict[str, dict] | None = None) -> str:
    """Convert a workflow JSON definition to a natural language instruction."""
    name = wf_data.get("name", "Untitled")
    desc = wf_data.get("description", "")
    definition = wf_data.get("definition", {})
    trigger = definition.get("trigger", {})
    steps = definition.get("steps", [])
    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])

    parts = [
        f'Implement workflow "{name}" in the generated application.',
        "",
    ]

    if desc:
        parts.append(f"Description: {desc}")
        parts.append("")

    # Trigger
    if trigger:
        t_type = trigger.get("type", "manual")
        parts.append(f"## Trigger: {t_type}")
        if t_type == "api_event":
            parts.append(f"Listen for event: {trigger.get('event', '')}")
        elif t_type == "schedule":
            parts.append(f"Run on cron schedule: {trigger.get('cron', '')}")
        elif t_type == "db_change":
            parts.append(f"Trigger on change to model: {trigger.get('model', '')}")
            if trigger.get("field"):
                parts.append(f"Watch field: {trigger.get('field')}")
        elif t_type == "webhook":
            parts.append(f"Register webhook at path: {trigger.get('path', '')}")
        elif t_type == "manual":
            parts.append(f"Manual trigger: {trigger.get('name', 'Start workflow')}")
        parts.append("")

    # Steps / Nodes
    if nodes:
        parts.append("## Workflow Steps:")
        for node in nodes:
            node_type = node.get("type", "action")
            node_data = node.get("data", {})
            label = node_data.get("label", node.get("id", ""))
            parts.append(f"- [{node_type}] {label}")

            config = node_data.get("config", {})
            if node_type == "action":
                if config.get("actionType"):
                    parts.append(f"  Action type: {config['actionType']}")
                if config.get("description"):
                    parts.append(f"  Description: {config['description']}")
            elif node_type == "condition":
                if config.get("expression"):
                    parts.append(f"  Condition: {config['expression']}")
                if config.get("conditionMode"):
                    parts.append(f"  Mode: {config['conditionMode']}")
            elif node_type == "decision":
                dt = config.get("decisionTable")
                if dt:
                    parts.append(f"  Hit Policy: {dt.get('hitPolicy', 'F')}")
                    inputs = dt.get("inputs", [])
                    outputs = dt.get("outputs", [])
                    parts.append(f"  Inputs: {', '.join(i.get('name', '') for i in inputs)}")
                    parts.append(f"  Outputs: {', '.join(o.get('name', '') for o in outputs)}")
                    parts.append(f"  Rules: {len(dt.get('rules', []))} rule(s)")
                    mapping = config.get("outputMapping")
                    if mapping:
                        parts.append("  Output Mapping:")
                        for col, var in mapping.items():
                            parts.append(f"    {col} -> {var}")
            elif node_type in ("assignment", "approval", "task_pool"):
                if config.get("assignType"):
                    parts.append(f"  Assign to: {config['assignType']}")
                assign_type = config.get("assignType")
                if assign_type == "initiator":
                    parts.append("  Target: (auto-assigned to workflow initiator)")
                elif assign_type == "process_variable":
                    if config.get("assignVariablePath"):
                        parts.append(f"  Variable path: {config['assignVariablePath']}")
                elif config.get("assignTargetName"):
                    parts.append(f"  Target: {config['assignTargetName']}")
                elif config.get("assignTarget"):
                    parts.append(f"  Target: {config['assignTarget']}")
                if config.get("approvalType"):
                    parts.append(f"  Approval type: {config['approvalType']}")
                if config.get("slaHours"):
                    parts.append(f"  SLA: {config['slaHours']} hours")
                # Include linked page + form fields
                node_id = node.get("id", "")
                if linked_pages and node_id in linked_pages:
                    page_info = linked_pages[node_id]
                    parts.append(f"  Linked page: \"{page_info['name']}\" at route {page_info['route']}")
                    if page_info.get("fields"):
                        parts.append("  Form fields (auto-bind to workflow variables):")
                        for f in page_info["fields"]:
                            req = " [required]" if f.get("required") else ""
                            pv = f" -> workflow variable: {f['processVariable']}" if f.get("processVariable") else ""
                            parts.append(f"    - {f.get('fieldName', '?')} ({f.get('type', 'text')}){req}{pv}")
            elif node_type == "wait":
                if config.get("duration"):
                    parts.append(f"  Wait: {config['duration']}")
            elif node_type == "escalation":
                if config.get("slaHours"):
                    parts.append(f"  Escalate after: {config['slaHours']} hours")
                if config.get("escalateTo"):
                    parts.append(f"  Escalate to: {config['escalateTo']}")
        parts.append("")

    # Edges
    if edges:
        parts.append("## Connections:")
        for edge in edges:
            edge_type = edge.get("data", {}).get("edgeType", "default")
            parts.append(f"- {edge.get('source', '?')} -> {edge.get('target', '?')} ({edge_type})")
        parts.append("")

    # Implementation requirements
    parts.extend([
        "## Implementation Requirements:",
        "1. Create a workflow runtime file (src/workflows/runtime.ts) with an executor that walks the node graph",
        "2. Create trigger registration (src/workflows/triggers.ts) to listen for the trigger event",
        "3. Create action functions for each action node in src/workflows/actions/",
        "4. For condition nodes: evaluate the expression and branch accordingly",
        "5. For assignment/approval nodes: create a task record and notify the assignee",
        "6. Create a tasks table in the Drizzle schema if it doesn't exist",
        "7. Add task inbox API routes: GET /api/tasks, POST /api/tasks/:id/claim, POST /api/tasks/:id/approve",
        "8. Store workflow definitions in src/workflows/definitions.ts",
    ])

    # If any nodes have linked pages with form fields, add form-task wiring requirements
    if linked_pages:
        parts.append("")
        parts.append("## Form-Task Auto-Binding:")
        parts.append("For each human-in-loop node with a linked page:")
        parts.append("1. The linked page contains form fields. When a task is created for that node,")
        parts.append("   pre-populate the form with current workflow variable values (from task.input_data)")
        parts.append("2. When the user submits the form, POST the form field values to /api/tasks/:id/complete")
        parts.append("   as output_data — this resumes the workflow with the submitted values as new variables")
        parts.append("3. Fields with a processVariable binding should read from / write to that workflow variable name")
        parts.append("4. Fields marked [required] must be validated before submission")
        parts.append("5. The task page should show the task context (workflow name, step label, assignee, SLA)")
        parts.append("6. Navigate the user to the linked page route when they open/claim a task")

        for node_id, page_info in linked_pages.items():
            node_label = ""
            for n in nodes:
                if n.get("id") == node_id:
                    node_label = n.get("data", {}).get("label", node_id)
                    break
            parts.append(f"\n### Task form for \"{node_label}\":")
            parts.append(f"  Route: {page_info['route']}")
            if page_info.get("fields"):
                parts.append("  Variable mapping:")
                for f in page_info["fields"]:
                    pv = f.get("processVariable", f.get("fieldName", ""))
                    parts.append(f"    form.{f.get('fieldName', '?')} <-> workflow.{pv}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Workflow Assignment Policies
# ---------------------------------------------------------------------------

@router.get(
    "/api/projects/{project_id}/workflow-assignments",
    response_model=list[AssignmentPolicyResponse],
)
async def list_assignments(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(WorkflowAssignmentPolicy)
        .where(WorkflowAssignmentPolicy.project_id == project_id)
        .order_by(WorkflowAssignmentPolicy.created_at.desc())
    )
    return result.scalars().all()


@router.post(
    "/api/projects/{project_id}/workflow-assignments",
    response_model=AssignmentPolicyResponse,
    status_code=201,
)
async def create_assignment(
    project_id: uuid.UUID,
    req: AssignmentPolicyCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    policy = WorkflowAssignmentPolicy(
        project_id=project_id,
        workflow_id=req.workflow_id,
        node_id=req.node_id,
        assign_type=req.assign_type,
        assign_target=req.assign_target,
        sla_hours=req.sla_hours,
        escalate_to=req.escalate_to,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


@router.put(
    "/api/projects/{project_id}/workflow-assignments/{policy_id}",
    response_model=AssignmentPolicyResponse,
)
async def update_assignment(
    project_id: uuid.UUID,
    policy_id: uuid.UUID,
    req: AssignmentPolicyUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_with_auth(project_id, user, db)
    result = await db.execute(
        select(WorkflowAssignmentPolicy).where(
            WorkflowAssignmentPolicy.id == policy_id,
            WorkflowAssignmentPolicy.project_id == project_id,
        )
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Assignment policy not found")

    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)

    await db.commit()
    await db.refresh(policy)
    return policy


# ---------------------------------------------------------------------------
# Workflow Runtime — Start, complete tasks, list instances
# ---------------------------------------------------------------------------

@router.post(
    "/api/projects/{project_id}/workflows/start",
    response_model=WorkflowInstanceResponse,
    status_code=201,
)
async def start_workflow(
    project_id: uuid.UUID,
    req: WorkflowStartRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new workflow instance."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    from runtime.engine import WorkflowRuntimeEngine

    engine = WorkflowRuntimeEngine(db)
    try:
        instance = await engine.start_workflow(
            project_id=project.id,
            org_id=project.org_id,
            workflow_id=req.workflow_id,
            output_dir=project.output_dir,
            initiated_by=req.initiated_by,
            variables=req.variables,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return instance


@router.get(
    "/api/projects/{project_id}/workflow-instances",
    response_model=list[WorkflowInstanceResponse],
)
async def list_instances(
    project_id: uuid.UUID,
    status: str | None = Query(None),
    workflow_id: str | None = Query(None),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List workflow instances for a project."""
    await get_project_with_auth(project_id, user, db)

    q = (
        select(WorkflowInstance)
        .where(WorkflowInstance.project_id == project_id)
        .order_by(WorkflowInstance.created_at.desc())
    )
    if status:
        q = q.where(WorkflowInstance.status == status)
    if workflow_id:
        q = q.where(WorkflowInstance.workflow_id == workflow_id)

    result = await db.execute(q)
    return result.scalars().all()


@router.get(
    "/api/projects/{project_id}/workflow-instances/{instance_id}",
    response_model=WorkflowInstanceDetailResponse,
)
async def get_instance(
    project_id: uuid.UUID,
    instance_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a workflow instance with its tasks."""
    await get_project_with_auth(project_id, user, db)

    result = await db.execute(
        select(WorkflowInstance)
        .where(
            WorkflowInstance.id == instance_id,
            WorkflowInstance.project_id == project_id,
        )
        .options(selectinload(WorkflowInstance.task_instances))
    )
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Workflow instance not found")

    return WorkflowInstanceDetailResponse(
        **{
            k: v for k, v in WorkflowInstanceResponse.model_validate(instance).model_dump().items()
        },
        tasks=[
            TaskInstanceResponse.model_validate(t)
            for t in instance.task_instances
        ],
    )


@router.post(
    "/api/projects/{project_id}/workflow-instances/{instance_id}/cancel",
    response_model=WorkflowInstanceResponse,
)
async def cancel_instance(
    project_id: uuid.UUID,
    instance_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running workflow instance."""
    project = await get_project_with_auth(project_id, user, db)

    from runtime.engine import WorkflowRuntimeEngine

    engine = WorkflowRuntimeEngine(db)
    try:
        instance = await engine.cancel_workflow(instance_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return instance


@router.post(
    "/api/projects/{project_id}/tasks/{task_id}/complete",
    response_model=TaskInstanceResponse,
)
async def complete_task(
    project_id: uuid.UUID,
    task_id: uuid.UUID,
    req: TaskCompleteRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete a workflow task and advance the workflow."""
    project = await get_project_with_auth(project_id, user, db)

    from runtime.engine import WorkflowRuntimeEngine

    engine = WorkflowRuntimeEngine(db)
    try:
        task = await engine.complete_task(
            task_id=task_id,
            output_data=req.output_data,
            output_dir=project.output_dir,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return task


@router.get(
    "/api/projects/{project_id}/tasks",
    response_model=list[TaskInstanceResponse],
)
async def list_tasks(
    project_id: uuid.UUID,
    assignee_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    instance_id: uuid.UUID | None = Query(None),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List workflow tasks for a project."""
    await get_project_with_auth(project_id, user, db)

    q = (
        select(TaskInstance)
        .join(WorkflowInstance)
        .where(WorkflowInstance.project_id == project_id)
        .order_by(TaskInstance.created_at.desc())
    )
    if assignee_id:
        q = q.where(TaskInstance.assignee_id == assignee_id)
    if status:
        q = q.where(TaskInstance.status == status)
    if instance_id:
        q = q.where(TaskInstance.workflow_instance_id == instance_id)

    result = await db.execute(q)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Execution Logs — Audit trail for node executions
# ---------------------------------------------------------------------------

@router.get(
    "/api/projects/{project_id}/workflow-instances/{instance_id}/logs",
    response_model=list[NodeExecutionLogResponse],
)
async def list_execution_logs(
    project_id: uuid.UUID,
    instance_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List execution logs for a workflow instance, ordered by started_at."""
    await get_project_with_auth(project_id, user, db)

    from models.node_execution_log import NodeExecutionLog

    result = await db.execute(
        select(NodeExecutionLog)
        .where(
            NodeExecutionLog.workflow_instance_id == instance_id,
        )
        .order_by(NodeExecutionLog.started_at.asc())
    )
    return result.scalars().all()
