# Generated-App Publish → Vercel + Neon (One-Click Deploy)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user clicks **Publish** in the Tentoro Forge editor, the platform snapshots the current generated-app state, provisions a Neon Postgres database (or reuses one), pushes the code to a Vercel project, wires every integration secret and the DATABASE_URL as env vars, runs Drizzle migrations at build time, and returns a live public URL — all streamed as SSE progress to the UI.

**Architecture:** Behind a `DeployProvider` interface so a future AWS target slots in without rewriting the publish flow, snapshot logic, `deployments` table, SSE progress stream, or Publish UI. Only the Vercel provider ships in this plan; the interface makes AWS a self-contained follow-up.

**Tech Stack:** FastAPI + SQLAlchemy on the platform, Vercel REST API v13 for deploy + v9 for projects/env, Neon REST API v2 for database provisioning, Vercel Blob for user uploads, existing Drizzle migrations in the generated app.

**Locked decisions (from brainstorm):**
- Platform-owned Vercel org — Tentoro's account hosts every deployed app; billing flows to Tentoro.
- Neon for Postgres — one Neon project per generated app.
- Vercel-only target for MVP; interface designed so AWS is added later.
- Platform hosting stays out of scope (short bootstrap doc lives at `docs/superpowers/plans/2026-07-23-platform-hosting-bootstrap.md`, referenced but not part of this TDD plan).

**Cost expectation per published app at MVP scale:** ~$0–20/mo (Vercel Hobby + Neon Free tier). Scales linearly on Vercel Pro + Neon Launch as users grow.

---

## File structure

Backend (Tentoro Forge platform):
```
backend/
├── models/deployment.py                           # SQLAlchemy: Deployment row
├── alembic/versions/2026_07_23_add_deployments.py # migration
├── services/deploy/
│   ├── __init__.py
│   ├── provider.py           # DeployProvider Protocol + DeployEvent types
│   ├── vercel_client.py      # thin async wrapper on Vercel REST
│   ├── neon_client.py        # thin async wrapper on Neon REST
│   ├── snapshot.py           # (output_dir) → deployable tarball / file map
│   ├── env_sync.py           # integrations + DATABASE_URL → Vercel env vars
│   └── vercel_provider.py    # implements DeployProvider using the above
├── routers/deployments.py    # POST /publish (SSE), GET history, POST rollback
└── tests/deploy/
    ├── test_snapshot.py      # pure logic — file filtering + tar shape
    ├── test_env_sync.py      # pure logic — merge integrations + Neon URL
    ├── test_vercel_provider.py  # integration — mocked HTTP
    └── conftest.py           # httpx mock fixtures
```

Generated-app templates that change:
```
backend/templates/standalone-app/
├── vercel.json.tmpl          # NEW — buildCommand runs migrations first
└── package.json.tmpl         # verify drizzle-kit is a dep (already is)

backend/templates/runtime/
├── storage.ts                # UPDATE — Vercel Blob when BLOB_READ_WRITE_TOKEN set
└── integrations/resolver.ts  # UPDATE — VERCEL_URL as NEXTAUTH_URL fallback
```

Frontend (editor):
```
frontend/src/
├── components/deploy/
│   ├── PublishButton.tsx     # button in the editor header
│   ├── PublishDialog.tsx     # target picker + SSE progress log
│   └── DeploymentHistory.tsx # list past deployments + rollback
├── hooks/useDeployStream.ts  # SSE consumer for progress events
└── lib/api-deploy.ts         # typed wrappers for /publish, /rollback
```

---

## Task 1: `deployments` table + Deployment model

**Files:**
- Create: `backend/models/deployment.py`
- Create: `backend/alembic/versions/2026_07_23_add_deployments.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/deploy/test_deployment_model.py
from models.deployment import Deployment
from models.project import Project

def test_deployment_persists_with_vercel_ids(db_session, sample_project):
    d = Deployment(
        project_id=sample_project.id,
        target="vercel",
        vercel_project_id="prj_abc",
        vercel_deployment_id="dpl_xyz",
        neon_project_id="np_123",
        url="https://acme-a1b2.vercel.app",
        status="succeeded",
    )
    db_session.add(d)
    db_session.commit()
    fetched = db_session.query(Deployment).filter_by(id=d.id).first()
    assert fetched.url == "https://acme-a1b2.vercel.app"
    assert fetched.status == "succeeded"
```

Run: `/usr/local/bin/python3 -m pytest tests/deploy/test_deployment_model.py -v`
Expected: FAIL — module missing.

- [ ] **Step 2: Create the model**

```python
# backend/models/deployment.py
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from models.base import Base

class Deployment(Base):
    __tablename__ = "deployments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    target = Column(String(32), nullable=False)         # "vercel" | "aws"
    status = Column(String(32), nullable=False, default="pending")  # pending|building|deploying|succeeded|failed
    url = Column(Text)
    error = Column(Text)
    # Vercel-specific
    vercel_project_id = Column(String(64))
    vercel_deployment_id = Column(String(64))
    # Neon-specific
    neon_project_id = Column(String(64))
    neon_branch_id = Column(String(64))
    # audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
```

- [ ] **Step 3: Alembic migration**

```python
# backend/alembic/versions/2026_07_23_add_deployments.py
"""add deployments table"""
from alembic import op
import sqlalchemy as sa

revision = "2026_07_23_deployments"
down_revision = "<PREV_HEAD>"  # replace with `alembic heads` output

def upgrade():
    op.create_table("deployments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("target", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("url", sa.Text),
        sa.Column("error", sa.Text),
        sa.Column("vercel_project_id", sa.String(64)),
        sa.Column("vercel_deployment_id", sa.String(64)),
        sa.Column("neon_project_id", sa.String(64)),
        sa.Column("neon_branch_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("triggered_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    op.create_index("deployments_project_created_idx", "deployments", ["project_id", "created_at"])

def downgrade():
    op.drop_index("deployments_project_created_idx", "deployments")
    op.drop_table("deployments")
```

- [ ] **Step 4: Run migration + test PASSES**

```bash
cd backend && alembic upgrade head
/usr/local/bin/python3 -m pytest tests/deploy/test_deployment_model.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/models/deployment.py backend/alembic/versions/2026_07_23_add_deployments.py backend/tests/deploy/test_deployment_model.py
git commit -m "feat(deploy): Deployment model + deployments table"
```

---

## Task 2: DeployProvider interface + DeployEvent types

**Files:**
- Create: `backend/services/deploy/provider.py`

Purpose: define the abstraction so the router and UI don't couple to Vercel. AWS drops in later behind the same interface.

- [ ] **Step 1: Write the interface (no test needed — it's a Protocol)**

```python
# backend/services/deploy/provider.py
from typing import Protocol, AsyncIterator, Literal, Optional
from dataclasses import dataclass

DeployStage = Literal[
    "snapshot",
    "provision_db",
    "migrate",
    "upload",
    "build",
    "activate",
    "done",
    "error",
]

@dataclass
class DeployEvent:
    stage: DeployStage
    message: str
    progress: Optional[float] = None   # 0..1 for the stage
    data: Optional[dict] = None        # stage-specific payload

@dataclass
class DeploySnapshot:
    """What the router hands to the provider — everything needed to publish."""
    project_id: str
    project_slug: str
    output_dir: str                    # /generated-apps/<slug>
    integrations: dict[str, str]       # merged from platform integrations sync
    existing_deployment_id: Optional[str] = None  # None → first publish; str → redeploy

class DeployProvider(Protocol):
    name: str

    async def publish(self, snapshot: DeploySnapshot) -> AsyncIterator[DeployEvent]:
        """Publish an app, yielding progress events. Final event MUST be
        stage='done' (data.url set) or stage='error' (message set)."""
        ...

    async def destroy(self, deployment: "Deployment") -> None:
        """Tear down the deployed resources for cleanup."""
        ...
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/deploy/provider.py backend/services/deploy/__init__.py
git commit -m "feat(deploy): DeployProvider Protocol + DeployEvent + DeploySnapshot"
```

---

## Task 3: Vercel API client (thin async wrapper)

**Files:**
- Create: `backend/services/deploy/vercel_client.py`
- Create: `backend/tests/deploy/test_vercel_client.py`

Purpose: encapsulate every Vercel REST call the provider needs. Kept thin — no business logic, one method per endpoint. All mocked in tests via `httpx-mock` so we never hit Vercel in CI.

Endpoints used:
- `POST /v9/projects` — create project (once, on first publish)
- `POST /v9/projects/{id}/env` — set/replace env vars
- `POST /v13/deployments` — create a deployment from an uploaded file tree
- `GET  /v13/deployments/{id}` — poll status until READY | ERROR
- `PATCH /v13/deployments/{id}/promote` — promote for rollback

- [ ] **Step 1: Write failing tests for each method**

```python
# backend/tests/deploy/test_vercel_client.py
import pytest
from httpx import Response
from services.deploy.vercel_client import VercelClient

@pytest.mark.asyncio
async def test_create_project_calls_v9_projects(respx_mock):
    respx_mock.post("https://api.vercel.com/v9/projects").mock(
        return_value=Response(200, json={"id": "prj_abc", "name": "acme"})
    )
    c = VercelClient(token="tk", team_id="tm")
    r = await c.create_project(name="acme", framework="nextjs")
    assert r["id"] == "prj_abc"

@pytest.mark.asyncio
async def test_set_env_replaces_existing(respx_mock):
    respx_mock.post("https://api.vercel.com/v9/projects/prj_abc/env").mock(
        return_value=Response(200, json={"created": [{"key": "DATABASE_URL"}]})
    )
    c = VercelClient(token="tk", team_id="tm")
    r = await c.set_env("prj_abc", key="DATABASE_URL", value="postgres://…", target=["production", "preview"])
    assert "created" in r

@pytest.mark.asyncio
async def test_create_deployment_uploads_files(respx_mock):
    respx_mock.post("https://api.vercel.com/v13/deployments").mock(
        return_value=Response(200, json={"id": "dpl_xyz", "url": "acme.vercel.app"})
    )
    c = VercelClient(token="tk", team_id="tm")
    files = [{"file": "package.json", "data": "{}"}]
    r = await c.create_deployment(name="acme", project_id="prj_abc", files=files)
    assert r["url"] == "acme.vercel.app"

@pytest.mark.asyncio
async def test_get_deployment_polls_status(respx_mock):
    respx_mock.get("https://api.vercel.com/v13/deployments/dpl_xyz").mock(
        return_value=Response(200, json={"readyState": "READY", "url": "acme.vercel.app"})
    )
    c = VercelClient(token="tk", team_id="tm")
    r = await c.get_deployment("dpl_xyz")
    assert r["readyState"] == "READY"
```

Run: FAIL — module missing.

- [ ] **Step 2: Implement VercelClient**

```python
# backend/services/deploy/vercel_client.py
import os
import httpx
from typing import Any

BASE = "https://api.vercel.com"

class VercelClient:
    def __init__(self, token: str | None = None, team_id: str | None = None):
        self.token = token or os.environ["VERCEL_TOKEN"]
        self.team_id = team_id or os.environ.get("VERCEL_TEAM_ID")
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=60.0,
        )

    def _params(self) -> dict:
        return {"teamId": self.team_id} if self.team_id else {}

    async def create_project(self, name: str, framework: str = "nextjs") -> dict[str, Any]:
        r = await self._client.post(
            f"{BASE}/v9/projects",
            params=self._params(),
            json={"name": name, "framework": framework},
        )
        r.raise_for_status()
        return r.json()

    async def set_env(self, project_id: str, key: str, value: str, target: list[str]) -> dict:
        r = await self._client.post(
            f"{BASE}/v9/projects/{project_id}/env",
            params={**self._params(), "upsert": "true"},
            json={"key": key, "value": value, "target": target, "type": "encrypted"},
        )
        r.raise_for_status()
        return r.json()

    async def create_deployment(self, name: str, project_id: str, files: list[dict]) -> dict:
        # Vercel v13 accepts inline file data for small deploys (< 10 MB).
        # For larger deploys we'd use the upload-first-then-deploy flow;
        # generated apps are ~1–3 MB so inline works.
        r = await self._client.post(
            f"{BASE}/v13/deployments",
            params=self._params(),
            json={
                "name": name,
                "project": project_id,
                "files": files,
                "target": "production",
                "projectSettings": {"framework": "nextjs"},
            },
        )
        r.raise_for_status()
        return r.json()

    async def get_deployment(self, deployment_id: str) -> dict:
        r = await self._client.get(
            f"{BASE}/v13/deployments/{deployment_id}",
            params=self._params(),
        )
        r.raise_for_status()
        return r.json()

    async def promote_deployment(self, deployment_id: str) -> dict:
        r = await self._client.patch(
            f"{BASE}/v13/deployments/{deployment_id}/promote",
            params=self._params(),
        )
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self._client.aclose()
```

- [ ] **Step 3: Tests PASS**

Run: `pytest tests/deploy/test_vercel_client.py -v` → 4 passed.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(deploy): VercelClient — thin async wrapper for Vercel REST"
```

---

## Task 4: Neon API client

**Files:**
- Create: `backend/services/deploy/neon_client.py`
- Create: `backend/tests/deploy/test_neon_client.py`

Endpoints used:
- `POST /api/v2/projects` — create project (one per generated app)
- `GET  /api/v2/projects/{id}/connection_uri` — fetch DATABASE_URL
- `DELETE /api/v2/projects/{id}` — cleanup on destroy

- [ ] **Step 1: Failing tests**

```python
# backend/tests/deploy/test_neon_client.py
import pytest
from httpx import Response
from services.deploy.neon_client import NeonClient

@pytest.mark.asyncio
async def test_create_project_returns_id_and_uri(respx_mock):
    respx_mock.post("https://console.neon.tech/api/v2/projects").mock(
        return_value=Response(200, json={
            "project": {"id": "np_123", "name": "acme"},
            "connection_uris": [{"connection_uri": "postgres://user:pass@ep.neon.tech/main"}]
        })
    )
    c = NeonClient(api_key="nk")
    r = await c.create_project(name="acme", pg_version=16)
    assert r["project_id"] == "np_123"
    assert "postgres://" in r["database_url"]

@pytest.mark.asyncio
async def test_delete_project(respx_mock):
    respx_mock.delete("https://console.neon.tech/api/v2/projects/np_123").mock(
        return_value=Response(200, json={"project": {"id": "np_123"}})
    )
    c = NeonClient(api_key="nk")
    await c.delete_project("np_123")  # should not raise
```

- [ ] **Step 2: Implement NeonClient**

```python
# backend/services/deploy/neon_client.py
import os
import httpx

BASE = "https://console.neon.tech/api/v2"

class NeonClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["NEON_API_KEY"]
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
            timeout=60.0,
        )

    async def create_project(self, name: str, pg_version: int = 16) -> dict:
        r = await self._client.post(
            f"{BASE}/projects",
            json={"project": {"name": name, "pg_version": pg_version}},
        )
        r.raise_for_status()
        body = r.json()
        return {
            "project_id": body["project"]["id"],
            "database_url": body["connection_uris"][0]["connection_uri"],
            "branch_id": body["project"].get("default_branch_id"),
        }

    async def delete_project(self, project_id: str) -> None:
        r = await self._client.delete(f"{BASE}/projects/{project_id}")
        r.raise_for_status()

    async def close(self):
        await self._client.aclose()
```

- [ ] **Step 3: Tests PASS + commit**

---

## Task 5: App snapshot module

**Files:**
- Create: `backend/services/deploy/snapshot.py`
- Create: `backend/tests/deploy/test_snapshot.py`

Purpose: turn `/generated-apps/<slug>/` into the Vercel `files[]` payload — a list of `{file, data}` entries with the on-disk relative path and file contents. Filter out:
- `node_modules/`, `.next/`, `.git/` — Vercel rebuilds these
- `.env`, `.env.local` — secrets flow through env-sync, not the files list
- log files, editor artifacts
- files larger than 100 MB (Vercel per-file limit)

- [ ] **Step 1: Failing test**

```python
# backend/tests/deploy/test_snapshot.py
from pathlib import Path
from services.deploy.snapshot import build_snapshot

def test_snapshot_includes_source_excludes_node_modules(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.tsx").write_text("export default () => null;")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "foo.js").write_text("bar")
    (tmp_path / ".env.local").write_text("SECRET=x")
    (tmp_path / ".next").mkdir()
    (tmp_path / ".next" / "chunk.js").write_text("bar")

    files = build_snapshot(tmp_path)
    paths = {f["file"] for f in files}
    assert "package.json" in paths
    assert "src/app.tsx" in paths
    assert "node_modules/foo.js" not in paths
    assert ".env.local" not in paths
    assert ".next/chunk.js" not in paths

def test_snapshot_encodes_binary_as_base64(tmp_path):
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "logo.png").write_bytes(b"\x89PNG\r\n")
    files = build_snapshot(tmp_path)
    logo = next(f for f in files if f["file"] == "public/logo.png")
    assert logo["encoding"] == "base64"

def test_snapshot_rejects_oversized_file(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"0" * (101 * 1024 * 1024))
    from services.deploy.snapshot import SnapshotTooLarge
    import pytest
    with pytest.raises(SnapshotTooLarge):
        build_snapshot(tmp_path)
```

- [ ] **Step 2: Implement snapshot**

```python
# backend/services/deploy/snapshot.py
import base64
from pathlib import Path
from typing import Iterator

_EXCLUDE_DIRS = {"node_modules", ".next", ".git", ".vercel", "dist", ".turbo", ".cache"}
_EXCLUDE_FILES = {".env", ".env.local", ".env.production", ".DS_Store"}
_MAX_FILE_BYTES = 100 * 1024 * 1024   # Vercel per-file limit
_MAX_TOTAL_BYTES = 250 * 1024 * 1024

class SnapshotTooLarge(Exception):
    pass

def _iter_files(root: Path) -> Iterator[Path]:
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        parts = set(p.relative_to(root).parts)
        if parts & _EXCLUDE_DIRS:
            continue
        if p.name in _EXCLUDE_FILES:
            continue
        yield p

def build_snapshot(root: Path) -> list[dict]:
    files = []
    total = 0
    for path in _iter_files(root):
        raw = path.read_bytes()
        if len(raw) > _MAX_FILE_BYTES:
            raise SnapshotTooLarge(f"{path.relative_to(root)} is {len(raw)} bytes (limit {_MAX_FILE_BYTES})")
        total += len(raw)
        if total > _MAX_TOTAL_BYTES:
            raise SnapshotTooLarge(f"snapshot exceeds {_MAX_TOTAL_BYTES} bytes")
        try:
            text = raw.decode("utf-8")
            files.append({"file": str(path.relative_to(root)), "data": text})
        except UnicodeDecodeError:
            files.append({
                "file": str(path.relative_to(root)),
                "data": base64.b64encode(raw).decode("ascii"),
                "encoding": "base64",
            })
    return files
```

- [ ] **Step 3: PASS + commit**

---

## Task 6: Env-sync — integrations + Neon URL → Vercel env vars

**Files:**
- Create: `backend/services/deploy/env_sync.py`
- Create: `backend/tests/deploy/test_env_sync.py`

Purpose: pure function that takes `(integrations, neon_url, vercel_url, generated_secrets)` and returns a `dict[str, str]` of env vars to set on the Vercel project. Deterministic — same input always produces the same output — so tests are easy.

Sources merged (later wins):
1. Baseline defaults (`NODE_ENV=production`)
2. Platform integrations (from `PlatformIntegration` table decrypted): `RESEND_API_KEY`, `SMTP_*`, `ANTHROPIC_API_KEY`, `S3_*`, etc.
3. Deployment-time system vars: `DATABASE_URL` (from Neon), `NEXTAUTH_URL` (from Vercel deployment URL), `NEXTAUTH_SECRET` (generated once per project)
4. Vercel Blob token: `BLOB_READ_WRITE_TOKEN` (from a `vercel blob store add`)

- [ ] **Step 1: Failing test**

```python
# backend/tests/deploy/test_env_sync.py
from services.deploy.env_sync import build_deploy_env

def test_merges_integrations_and_system_vars():
    env = build_deploy_env(
        integrations={"RESEND_API_KEY": "re_1", "ANTHROPIC_API_KEY": "sk_1"},
        neon_url="postgres://ep.neon.tech/main",
        vercel_url="acme.vercel.app",
        nextauth_secret="deadbeef",
    )
    assert env["DATABASE_URL"] == "postgres://ep.neon.tech/main"
    assert env["NEXTAUTH_URL"] == "https://acme.vercel.app"
    assert env["NEXTAUTH_SECRET"] == "deadbeef"
    assert env["RESEND_API_KEY"] == "re_1"
    assert env["NODE_ENV"] == "production"

def test_system_vars_override_integrations():
    env = build_deploy_env(
        integrations={"DATABASE_URL": "postgres://oldwrong"},  # user mistake
        neon_url="postgres://ep.neon.tech/main",
        vercel_url="acme.vercel.app",
        nextauth_secret="deadbeef",
    )
    assert env["DATABASE_URL"] == "postgres://ep.neon.tech/main"

def test_skips_none_values():
    env = build_deploy_env(
        integrations={"OPTIONAL": None, "SET": "v"},
        neon_url="postgres://x", vercel_url="acme.vercel.app", nextauth_secret="s",
    )
    assert "OPTIONAL" not in env
    assert env["SET"] == "v"
```

- [ ] **Step 2: Implement**

```python
# backend/services/deploy/env_sync.py

def build_deploy_env(
    integrations: dict[str, str | None],
    neon_url: str,
    vercel_url: str,
    nextauth_secret: str,
    blob_token: str | None = None,
) -> dict[str, str]:
    env: dict[str, str] = {"NODE_ENV": "production"}
    for k, v in integrations.items():
        if v is None or v == "":
            continue
        env[k] = str(v)
    # System vars WIN — user-provided integrations can't override these.
    env["DATABASE_URL"] = neon_url
    env["NEXTAUTH_URL"] = f"https://{vercel_url.lstrip('https://').lstrip('http://')}"
    env["NEXTAUTH_SECRET"] = nextauth_secret
    if blob_token:
        env["BLOB_READ_WRITE_TOKEN"] = blob_token
    return env
```

- [ ] **Step 3: PASS + commit**

---

## Task 7: VercelDeployProvider — compose the pieces

**Files:**
- Create: `backend/services/deploy/vercel_provider.py`
- Create: `backend/tests/deploy/test_vercel_provider.py`

Compose the DeploySnapshot flow:
1. `snapshot` — call `build_snapshot()`
2. `provision_db` — if `deployment.neon_project_id` unset, call `neon.create_project()`; else reuse
3. `upload` — call `vercel.create_deployment()` with files
4. `activate` — poll `vercel.get_deployment()` until READY | ERROR
5. Yield DeployEvent per stage
6. Persist stage transitions on the Deployment row

- [ ] **Step 1: Integration test with all HTTP mocked**

```python
# backend/tests/deploy/test_vercel_provider.py
@pytest.mark.asyncio
async def test_publish_full_flow(respx_mock, tmp_path, db_session, sample_project):
    # Set up a minimal generated-app tree
    (tmp_path / "package.json").write_text('{"name":"acme"}')

    # Mock Neon create_project
    respx_mock.post("https://console.neon.tech/api/v2/projects").mock(
        return_value=Response(200, json={
            "project": {"id": "np_123", "default_branch_id": "br_1"},
            "connection_uris": [{"connection_uri": "postgres://ep.neon.tech/main"}]
        })
    )
    # Mock Vercel create_project + set_env + create_deployment + get_deployment
    respx_mock.post("https://api.vercel.com/v9/projects").mock(
        return_value=Response(200, json={"id": "prj_abc"})
    )
    respx_mock.post(url__regex=r"https://api\.vercel\.com/v9/projects/prj_abc/env").mock(
        return_value=Response(200, json={"created": []})
    )
    respx_mock.post("https://api.vercel.com/v13/deployments").mock(
        return_value=Response(200, json={"id": "dpl_xyz", "url": "acme-abc.vercel.app"})
    )
    respx_mock.get("https://api.vercel.com/v13/deployments/dpl_xyz").mock(
        return_value=Response(200, json={"readyState": "READY", "url": "acme-abc.vercel.app"})
    )

    p = VercelDeployProvider(db=db_session)
    snapshot = DeploySnapshot(
        project_id=str(sample_project.id),
        project_slug="acme",
        output_dir=str(tmp_path),
        integrations={"RESEND_API_KEY": "re_1"},
    )
    events = [e async for e in p.publish(snapshot)]
    stages = [e.stage for e in events]
    assert stages[0] == "snapshot"
    assert stages[-1] == "done"
    assert events[-1].data["url"] == "https://acme-abc.vercel.app"
```

- [ ] **Step 2: Implement VercelDeployProvider**

Approx 150 LOC; skeleton:

```python
# backend/services/deploy/vercel_provider.py
import asyncio, secrets
from services.deploy.provider import DeployProvider, DeployEvent, DeploySnapshot
from services.deploy.vercel_client import VercelClient
from services.deploy.neon_client import NeonClient
from services.deploy.snapshot import build_snapshot
from services.deploy.env_sync import build_deploy_env
from models.deployment import Deployment
from pathlib import Path

class VercelDeployProvider:
    name = "vercel"
    def __init__(self, db, vercel: VercelClient = None, neon: NeonClient = None):
        self.db = db
        self.vercel = vercel or VercelClient()
        self.neon = neon or NeonClient()

    async def publish(self, snapshot: DeploySnapshot):
        # Fetch existing deployment row if this is a redeploy
        existing = None
        if snapshot.existing_deployment_id:
            existing = self.db.query(Deployment).get(snapshot.existing_deployment_id)

        yield DeployEvent("snapshot", "Packaging app source…")
        files = build_snapshot(Path(snapshot.output_dir))

        yield DeployEvent("provision_db", "Provisioning Neon database…")
        if existing and existing.neon_project_id:
            neon_project_id = existing.neon_project_id
            neon_url = existing._neon_url_cached   # stored elsewhere or refetched
        else:
            r = await self.neon.create_project(name=snapshot.project_slug)
            neon_project_id = r["project_id"]
            neon_url = r["database_url"]

        # Vercel project — create on first publish, reuse on redeploy
        if existing and existing.vercel_project_id:
            vercel_project_id = existing.vercel_project_id
        else:
            vp = await self.vercel.create_project(name=snapshot.project_slug)
            vercel_project_id = vp["id"]

        yield DeployEvent("upload", "Uploading source to Vercel…")
        vd = await self.vercel.create_deployment(
            name=snapshot.project_slug,
            project_id=vercel_project_id,
            files=files,
        )
        deployment_id = vd["id"]
        vercel_url = vd["url"]

        # Env vars: system + integrations. Set AFTER deployment created but
        # BEFORE the build triggers (Vercel builds when env vars are set on
        # a new deployment).
        env = build_deploy_env(
            integrations=snapshot.integrations,
            neon_url=neon_url,
            vercel_url=vercel_url,
            nextauth_secret=secrets.token_hex(32),
        )
        for k, v in env.items():
            await self.vercel.set_env(vercel_project_id, k, v, ["production"])

        yield DeployEvent("build", "Vercel is building your app…")
        yield DeployEvent("activate", "Activating deployment…")

        # Poll until READY or ERROR (60 s cap)
        for _ in range(60):
            info = await self.vercel.get_deployment(deployment_id)
            state = info["readyState"]
            if state == "READY":
                url = f"https://{info['url']}"
                # Persist deployment row
                row = existing or Deployment(project_id=snapshot.project_id, target="vercel")
                row.vercel_project_id = vercel_project_id
                row.vercel_deployment_id = deployment_id
                row.neon_project_id = neon_project_id
                row.url = url
                row.status = "succeeded"
                self.db.add(row); self.db.commit()
                yield DeployEvent("done", f"Live at {url}", data={"url": url, "deployment_id": str(row.id)})
                return
            if state == "ERROR":
                yield DeployEvent("error", "Vercel build failed. Check deployment logs.")
                return
            await asyncio.sleep(2)
        yield DeployEvent("error", "Deployment timed out after 2 minutes")
```

- [ ] **Step 3: Tests PASS + commit**

---

## Task 8: `vercel.json.tmpl` — buildCommand runs migrations first

**Files:**
- Create: `backend/templates/standalone-app/vercel.json.tmpl`
- Modify: `backend/templates/standalone-app/package.json.tmpl` (already has `drizzle-kit` dep — verify)

- [ ] **Step 1: Add vercel.json to the generated-app template**

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": "nextjs",
  "buildCommand": "npx drizzle-kit push --config drizzle.config.ts && next build",
  "installCommand": "npm install",
  "regions": ["iad1"],
  "functions": {
    "src/app/api/**/route.ts": { "maxDuration": 60 }
  }
}
```

`drizzle-kit push` runs FIRST — creates every table (including `workflow_tasks`, `workflow_execution_log`, and everything the LLM generated) — then `next build`. `DATABASE_URL` is set at build time by env-sync.

- [ ] **Step 2: Wire the template into `runtime_injector.py` or wherever standalone-app assets are emitted**

Add `vercel.json` to the copy list so every generated app has it.

- [ ] **Step 3: Commit**

---

## Task 9: Vercel Blob storage template swap

**Files:**
- Modify: `backend/templates/runtime/storage.ts`

Purpose: when `BLOB_READ_WRITE_TOKEN` is set, `storage.ts` writes to Vercel Blob instead of local disk. Local disk stays the dev-mode fallback. No new template — modify the existing `storage.ts`.

- [ ] **Step 1: Read current storage.ts, add a Vercel Blob branch**

```typescript
// backend/templates/runtime/storage.ts
export async function saveFile(name: string, data: Buffer): Promise<string> {
  const blobToken = process.env.BLOB_READ_WRITE_TOKEN;
  if (blobToken) {
    // Vercel Blob path — used on Vercel-deployed apps
    const { put } = await import("@vercel/blob");
    const res = await put(name, data, {
      access: "public",
      token: blobToken,
    });
    return res.url;
  }
  // Local disk fallback — dev / self-hosted
  // …existing code…
}
```

- [ ] **Step 2: Add `@vercel/blob` to `package.json.tmpl` as an optional dep**

- [ ] **Step 3: Commit**

---

## Task 10: `/api/projects/{id}/publish` route + SSE stream

**Files:**
- Create: `backend/routers/deployments.py`
- Modify: `backend/main.py` (register the router)

- [ ] **Step 1: Test the SSE endpoint**

```python
# backend/tests/deploy/test_publish_route.py
@pytest.mark.asyncio
async def test_publish_streams_events(client, sample_project, mock_provider):
    resp = client.post(f"/api/projects/{sample_project.id}/publish", stream=True)
    events = list(iter_sse_events(resp))
    assert events[0]["stage"] == "snapshot"
    assert events[-1]["stage"] == "done"
    assert "url" in events[-1]["data"]
```

- [ ] **Step 2: Implement router**

```python
# backend/routers/deployments.py
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import json
from services.deploy.vercel_provider import VercelDeployProvider
from services.deploy.provider import DeploySnapshot
from services.platform_integrations import decrypt_org_integrations

router = APIRouter()

@router.post("/api/projects/{project_id}/publish")
async def publish(project_id: str, db=Depends(get_db), user=Depends(current_user)):
    project = require_project(db, project_id, user)
    integrations = decrypt_org_integrations(db, project.org_id)
    snapshot = DeploySnapshot(
        project_id=str(project.id),
        project_slug=project.slug,
        output_dir=project.output_dir,
        integrations=integrations,
        existing_deployment_id=str(_latest_deployment(db, project).id) if _latest_deployment(db, project) else None,
    )
    provider = VercelDeployProvider(db=db)

    async def stream():
        async for evt in provider.publish(snapshot):
            yield f"data: {json.dumps({'stage': evt.stage, 'message': evt.message, 'data': evt.data})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")

@router.get("/api/projects/{project_id}/deployments")
def list_deployments(project_id: str, db=Depends(get_db)):
    rows = db.query(Deployment).filter_by(project_id=project_id).order_by(Deployment.created_at.desc()).limit(20).all()
    return [{"id": str(r.id), "url": r.url, "status": r.status, "created_at": r.created_at.isoformat()} for r in rows]

@router.post("/api/deployments/{deployment_id}/rollback")
async def rollback(deployment_id: str, db=Depends(get_db)):
    d = db.query(Deployment).get(deployment_id)
    if not d or d.target != "vercel" or not d.vercel_deployment_id:
        raise HTTPException(400, "Not rollback-able")
    vc = VercelClient()
    r = await vc.promote_deployment(d.vercel_deployment_id)
    d.status = "succeeded"; d.finished_at = datetime.utcnow()
    db.commit()
    return {"url": d.url}
```

- [ ] **Step 3: Tests PASS + commit**

---

## Task 11: PublishButton + PublishDialog + SSE consumer

**Files:**
- Create: `frontend/src/components/deploy/PublishButton.tsx`
- Create: `frontend/src/components/deploy/PublishDialog.tsx`
- Create: `frontend/src/hooks/useDeployStream.ts`

- [ ] **Step 1: SSE hook**

```typescript
// frontend/src/hooks/useDeployStream.ts
export function useDeployStream(projectId: string, enabled: boolean) {
  const [events, setEvents] = useState<DeployEvent[]>([]);
  useEffect(() => {
    if (!enabled) return;
    const es = new EventSource(`/api/projects/${projectId}/publish`, { withCredentials: true });
    es.onmessage = (m) => setEvents((prev) => [...prev, JSON.parse(m.data)]);
    es.onerror = () => es.close();
    return () => es.close();
  }, [projectId, enabled]);
  return events;
}
```

Note: EventSource is GET-only. Because our endpoint is a POST, use `fetch` with body reader instead — swap the hook to a fetch+reader implementation.

- [ ] **Step 2: PublishDialog**

Renders a modal with:
- Header: "Publish to Vercel"
- Body: staged progress list (Snapshot → Provision DB → Upload → Build → Activate → Done)
- Each stage shows a spinner while active, checkmark when done
- Final stage: card with the live URL + "Open" button + "Copy" button

- [ ] **Step 3: PublishButton**

Header button that opens PublishDialog on click.

- [ ] **Step 4: Wire into the editor toolbar**

- [ ] **Step 5: Commit**

---

## Task 12: DeploymentHistory + rollback UI

**Files:**
- Create: `frontend/src/components/deploy/DeploymentHistory.tsx`

Table with columns: When / URL / Status / Actions (Rollback button on non-current successful deploys). Uses `GET /api/projects/{id}/deployments`.

Rollback button calls `POST /api/deployments/{id}/rollback` and refreshes the list.

- [ ] **Step 1: Test + implement + commit**

---

## Task 13: Live E2E — publish a fresh app and use it

**Files:**
- Create: `docs/superpowers/e2e/2026-07-23-vercel-publish.md`

- [ ] **Step 1: Prerequisites checklist**
  - `VERCEL_TOKEN` in platform `.env` (with team scope; not personal)
  - `VERCEL_TEAM_ID` in platform `.env`
  - `NEON_API_KEY` in platform `.env`
  - Platform running on 6500/6501 with Task 1–12 code deployed

- [ ] **Step 2: Publish flow**
  1. Log in, open any generated app
  2. Click Publish → PublishDialog opens
  3. Watch stages: Snapshot ✓ → Provision DB ✓ → Upload ✓ → Build ✓ → Activate ✓ → Done
  4. Click the returned URL — the app loads at `<slug>-<hash>.vercel.app`

- [ ] **Step 3: Runtime smoke on the deployed app**
  1. Sign up → user row created in Neon
  2. Trigger a workflow that sends an email → check the delivered email (verifies Resend/SMTP integration synced)
  3. Trigger an AI node → check response (verifies ANTHROPIC_API_KEY synced)
  4. Upload a file → check Vercel Blob storage
  5. Complete a user_task → verify workflow resumes

- [ ] **Step 4: Redeploy**
  1. Edit the app on the platform
  2. Click Publish again → new deployment on the same Vercel project
  3. Verify URL unchanged, new code live

- [ ] **Step 5: Rollback**
  1. Open DeploymentHistory → click Rollback on the previous deployment
  2. Verify the earlier code is live at the same URL

- [ ] **Step 6: Record findings in the E2E doc + commit**

---

## Out of scope (deferred)

Real new features, not shortcut deferrals:

- **AWS DeployProvider** — the `DeployProvider` interface is designed for it, but the AwsProvider (CodeBuild + ECR + App Runner + Aurora + Route 53) is its own multi-task plan.
- **Bring-your-own Vercel account** — user connects their own Vercel via OAuth instead of shipping to the platform-owned org. Adds an OAuth dance + per-user token storage.
- **Custom domains** — user adds a CNAME on their DNS pointing to their `*.vercel.app`. Vercel supports it via `POST /v9/projects/{id}/domains`; wire the UI in a follow-up.
- **Preview deploys per branch / commit** — Vercel's native feature; we'd need to expose it in the editor.
- **Deployment logs viewer** — surface Vercel's build logs in the editor via `GET /v2/deployments/{id}/events` streaming.
- **Metered billing pass-through** — reading Vercel usage + Neon usage per app and adding it to the user's Tentoro bill. Requires the billing subsystem, which doesn't exist yet.
- **Platform hosting bootstrap** (single-EC2 story) — separate short doc, not part of this TDD plan.
