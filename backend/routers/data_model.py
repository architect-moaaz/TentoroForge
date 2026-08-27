"""Data model endpoints — app-model reader, schema changes, DB browser, seed."""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import OrgMemberRole
from models.project import (
    Project,
    Conversation,
    AgentJob,
    Version,
    MessageRole,
    MessageType,
    AgentType,
    AgentJobStatus,
)
from schemas.data_model import SchemaChangeRequest, SqlQueryRequest, SeedRequest
from services.project_service import get_project_with_auth
from services.git_service import git_commit
from sse_helpers import sse_event, stream_agent_messages
from routers.orgs import _require_org_member

router = APIRouter(tags=["data_model"])


# ---------------------------------------------------------------------------
# App-model reader
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/app-model")
async def get_app_model(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read app-model.json from the project output directory."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no output directory")

    # The schema-mode pipeline writes the canonical app-model to
    # src/contracts/app-model.json (alongside the rest of the contracts).
    # Older runs put it at the output-dir root; honour both for compatibility.
    candidates = [
        Path(project.output_dir) / "src" / "contracts" / "app-model.json",
        Path(project.output_dir) / "app-model.json",
    ]
    model_path = next((p for p in candidates if p.exists()), None)
    if model_path is None:
        raise HTTPException(status_code=404, detail="app-model.json not found — run indexer first")

    try:
        model = json.loads(model_path.read_text())
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="app-model.json is malformed")

    # Synthesise database.tables from registry.json when app-model.json
    # doesn't already include it. The ERD canvas reads database.tables[]
    # with .columns[] (name, type, primaryKey, nullable, references) and
    # tables share relations from registry.relations. The schema-mode
    # pipeline writes column-level data into registry.json, not into
    # app-model.json, so we merge them here for the consumer.
    has_tables = bool(model.get("database", {}).get("tables"))
    if not has_tables:
        registry_path = Path(project.output_dir) / "registry.json"
        if registry_path.exists():
            try:
                registry = json.loads(registry_path.read_text())
            except json.JSONDecodeError:
                registry = {}
            tables = _tables_from_registry(registry)
            if tables:
                model.setdefault("database", {})["tables"] = tables
    return model


def _tables_from_registry(registry: dict) -> list[dict]:
    """Map registry.entities + registry.relations into the ERDCanvas table shape."""
    entities = registry.get("entities", {}) or {}
    relations = registry.get("relations", []) or []
    if not isinstance(entities, dict):
        return []

    # Build a foreignKey → target entity index so we can attach references
    # to the matching column on each entity.
    fk_targets: dict[tuple[str, str], dict] = {}
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        fk = rel.get("foreignKey")
        if not isinstance(fk, str) or not fk:
            continue
        fk_targets[(rel.get("from_entity", ""), fk)] = rel

    tables: list[dict] = []
    for entity_name, entity in entities.items():
        if not isinstance(entity, dict):
            continue
        fields = entity.get("fields", {})
        if not isinstance(fields, dict):
            continue
        columns: list[dict] = []
        for col_name, col_info in fields.items():
            if not isinstance(col_info, dict):
                continue
            col: dict = {
                "name": col_name,
                "type": col_info.get("type", "text"),
                "nullable": bool(col_info.get("nullable", False)),
                "primaryKey": bool(col_info.get("primaryKey", False)),
            }
            rel = fk_targets.get((entity_name, col_name))
            if rel:
                target_entity = rel.get("to_entity")
                if target_entity:
                    target = entities.get(target_entity, {})
                    col["references"] = {
                        "table": target.get("table") or target_entity.lower() + "s",
                        "column": "id",
                    }
            columns.append(col)
        # Attach entity-level relations so ERDCanvas can draw typed edges.
        entity_relations = []
        for rel in relations:
            if isinstance(rel, dict) and rel.get("from_entity") == entity_name:
                entity_relations.append({
                    "type": rel.get("type", "many-to-one"),
                    "target": (entities.get(rel.get("to_entity", ""), {}) or {}).get("table") or
                              rel.get("to_entity", "").lower() + "s",
                    "foreignKey": rel.get("foreignKey"),
                })
        tables.append({
            "name": entity.get("table") or entity_name.lower() + "s",
            "displayName": entity_name,
            "columns": columns,
            "relations": entity_relations,
        })
    return tables


# ---------------------------------------------------------------------------
# Schema change (instruction builder → code_editor → validate → index → commit)
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/schema/apply")
async def apply_schema_change(
    project_id: uuid.UUID,
    req: SchemaChangeRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a schema change instruction via code_editor agent pipeline.

    Streams SSE: code_editor → validator → indexer → drizzle-kit push → git commit.
    """
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no output directory")

    async def event_stream():
        yield sse_event("status", {"message": "Applying schema change..."})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            # Phase 1: Code editor — make the schema change
            from agents.code_editor import run_code_editor
            yield sse_event("status", {"message": "Editing schema..."})

            async for evt in stream_agent_messages(
                run_code_editor(
                    output_dir=project.output_dir,
                    instruction=req.instruction,
                ),
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Phase 2: Validator — ensure build passes
            from agents.validator import run_validator
            yield sse_event("status", {"message": "Validating build..."})

            async for evt in stream_agent_messages(
                run_validator(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Validator] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Phase 3: Indexer — re-produce app-model.json
            from agents.indexer import run_indexer
            yield sse_event("status", {"message": "Indexing application..."})

            async for evt in stream_agent_messages(
                run_indexer(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Indexer] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Phase 4: drizzle-kit push (if preview is running)
            if project.db_port:
                yield sse_event("status", {"message": "Pushing schema to database..."})
                push_proc = await asyncio.create_subprocess_exec(
                    "npx", "drizzle-kit", "push",
                    cwd=project.output_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={
                        **__import__("os").environ,
                        "DATABASE_URL": f"postgresql://postgres:postgres@localhost:{project.db_port}/app",
                    },
                )
                stdout, stderr = await push_proc.communicate()
                if push_proc.returncode == 0:
                    yield sse_event("status", {"message": "Schema pushed to database"})
                else:
                    yield sse_event("log", {
                        "text": f"[drizzle-kit push] Warning: {stderr.decode()[:300]}",
                    })

            # Phase 5: Git commit
            commit_hash = await git_commit(project.output_dir,
                f"schema: {req.instruction[:80]}",
            actor="editor")

            # Persist results
            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=req.instruction,
                    result={
                        "intent": "SCHEMA_CHANGE",
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message=f"schema: {req.instruction[:80]}",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                assistant_msg = Conversation(
                    project_id=project.id,
                    role=MessageRole.assistant,
                    content=f"Schema change applied: {req.instruction[:120]}",
                    message_type=MessageType.chat,
                    metadata_={
                        "intent": "SCHEMA_CHANGE",
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "commit_hash": commit_hash,
                    },
                )
                sess.add(assistant_msg)
                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "num_turns": total_turns,
                "cost_usd": total_cost,
                "duration_ms": total_duration,
                "commit_hash": commit_hash,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


# ---------------------------------------------------------------------------
# Database browser
# ---------------------------------------------------------------------------

def build_rows_query(
    table: str,
    valid_columns: set[str],
    sort: str | None,
    direction: str,
    limit: int,
    offset: int,
) -> tuple[str, list]:
    """Build a safe paginated SELECT for the data viewer.

    `table` is already validated by the caller (its columns were fetched from
    information_schema). `sort`, if given, MUST be a real column — otherwise a
    ValueError is raised (the injection guard). Identifiers are double-quoted;
    limit/offset are bound parameters.
    """
    if sort is not None and sort not in valid_columns:
        raise ValueError(f"Unknown sort column: {sort}")
    direction_sql = "DESC" if str(direction).lower() == "desc" else "ASC"
    order = f' ORDER BY "{sort}" {direction_sql}' if sort else ""
    sql = f'SELECT * FROM "{table}"{order} LIMIT $1 OFFSET $2'
    return sql, [limit, offset]


async def _get_db_connection(project: Project):
    """Create an asyncpg connection to the project's database."""
    if not project.db_port:
        raise HTTPException(status_code=400, detail="No database running — start preview first")

    import asyncpg
    try:
        conn = await asyncpg.connect(
            host="localhost",
            port=project.db_port,
            user="postgres",
            password="postgres",
            database="app",
        )
        return conn
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Cannot connect to database: {e}")


@router.get("/api/projects/{project_id}/db/tables")
async def list_db_tables(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tables in the project's database via information_schema."""
    project = await get_project_with_auth(project_id, user, db)
    await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)
    conn = await _get_db_connection(project)
    try:
        rows = await conn.fetch("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = []
        for row in rows:
            table_name = row["table_name"]
            cols = await conn.fetch("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
            """, table_name)
            count_row = await conn.fetchrow(
                f'SELECT COUNT(*) as cnt FROM "{table_name}"'
            )
            tables.append({
                "name": table_name,
                "row_count": count_row["cnt"] if count_row else 0,
                "columns": [
                    {
                        "name": c["column_name"],
                        "type": c["data_type"],
                        "nullable": c["is_nullable"] == "YES",
                        "default": c["column_default"],
                    }
                    for c in cols
                ],
            })
        return {"tables": tables}
    finally:
        await conn.close()


@router.get("/api/projects/{project_id}/db/rows")
async def get_table_rows(
    project_id: uuid.UUID,
    table: str = Query(...),
    limit: int = Query(50),
    offset: int = Query(0),
    sort: str | None = Query(None),
    dir: str = Query("asc"),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only: paginated, optionally-sorted rows from a project table."""
    project = await get_project_with_auth(project_id, user, db)
    await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)

    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    conn = await _get_db_connection(project)
    try:
        cols = await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position
            """,
            table,
        )
        if not cols:
            raise HTTPException(status_code=404, detail="Table not found")
        valid_columns = {c["column_name"] for c in cols}
        try:
            sql, params = build_rows_query(table, valid_columns, sort, dir, limit, offset)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        rows = await conn.fetch(sql, *params)
        total = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
        columns = list(rows[0].keys()) if rows else [c["column_name"] for c in cols]
        data = [dict(r) for r in rows]
        for row in data:
            for k, v in row.items():
                if not isinstance(v, (str, int, float, bool, type(None), list, dict)):
                    row[k] = str(v)
        return {"columns": columns, "rows": data, "total": total, "limit": limit, "offset": offset}
    finally:
        await conn.close()


@router.get("/api/projects/{project_id}/db/query")
async def query_db_readonly(
    project_id: uuid.UUID,
    sql: str = Query(...),
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute a read-only SELECT query on the project's database."""
    project = await get_project_with_auth(project_id, user, db)
    await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)

    # Basic safety check — only allow SELECT
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Only SELECT queries allowed via GET")

    conn = await _get_db_connection(project)
    try:
        rows = await conn.fetch(sql)
        columns = list(rows[0].keys()) if rows else []
        data = [dict(r) for r in rows]
        # Serialize non-JSON types
        for row in data:
            for k, v in row.items():
                if not isinstance(v, (str, int, float, bool, type(None), list, dict)):
                    row[k] = str(v)
        return {"columns": columns, "rows": data, "row_count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query error: {e}")
    finally:
        await conn.close()


@router.post("/api/projects/{project_id}/db/query")
async def execute_db_write(
    project_id: uuid.UUID,
    req: SqlQueryRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Execute a write SQL statement (INSERT/UPDATE/DELETE) on the project's database."""
    project = await get_project_with_auth(project_id, user, db)
    await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)

    # Block DDL
    normalized = req.sql.strip().upper()
    blocked = ["DROP", "CREATE", "ALTER", "TRUNCATE"]
    if any(normalized.startswith(kw) for kw in blocked):
        raise HTTPException(status_code=400, detail="DDL statements not allowed — use schema editor")

    conn = await _get_db_connection(project)
    try:
        result = await conn.execute(req.sql)
        return {"result": result, "success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Query error: {e}")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Seed data generation
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/db/seed")
async def generate_seed_data(
    project_id: uuid.UUID,
    req: SeedRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and run seed data via the seed_generator agent."""
    project = await get_project_with_auth(project_id, user, db)
    await _require_org_member(project.org_id, user, db, min_role=OrgMemberRole.admin)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="Project has no output directory")

    async def event_stream():
        yield sse_event("status", {"message": "Generating seed data..."})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            from agents.seed_generator import run_seed_generator
            async for evt in stream_agent_messages(
                run_seed_generator(
                    output_dir=project.output_dir,
                    row_count=req.row_count,
                    theme=req.theme,
                    db_port=project.db_port,
                ),
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            # Git commit
            commit_hash = await git_commit(project.output_dir,
                "seed: generate realistic seed data",
            actor="editor")

            # Persist
            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.seed_generator,
                    status=AgentJobStatus.completed,
                    instruction=f"Generate {req.row_count} rows of seed data"
                                + (f" with theme: {req.theme}" if req.theme else ""),
                    result={
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message="seed: generate realistic seed data",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "num_turns": total_turns,
                "cost_usd": total_cost,
                "duration_ms": total_duration,
                "commit_hash": commit_hash,
            })

        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)
