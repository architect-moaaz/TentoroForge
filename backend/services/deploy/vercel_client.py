"""Thin async wrapper on the Vercel REST API.

Kept intentionally lean — one method per endpoint the deploy pipeline
actually calls, no business logic. VercelDeployProvider owns the orchestration.

Every call:
  - passes teamId in the query string (Vercel scopes projects to teams;
    without it, the API creates under your personal account)
  - raises for non-2xx (`r.raise_for_status()`) so the provider can
    catch and translate to a DeployEvent(stage="error")

Auth: `Authorization: Bearer <VERCEL_TOKEN>`. The token is a personal
token scoped to the platform-owned team (see setup docs in the plan).

Endpoints used:
  POST   /v9/projects                            create_project
  POST   /v9/projects/{id}/env                   set_env      (upsert)
  POST   /v2/files                               upload_file  (sha-keyed)
  POST   /v13/deployments                        create_deployment
  GET    /v13/deployments/{id}                   get_deployment
  PATCH  /v13/deployments/{id}/promote           promote_deployment
"""
from __future__ import annotations

import os
from typing import Any

import httpx

BASE = "https://api.vercel.com"


def _raise_with_body(r: httpx.Response, op: str) -> None:
    """Bare `raise_for_status()` on Vercel gives only URL + status; a 400
    could be reserved name, malformed files, quota, permissions… we can't
    tell without seeing Vercel's error body. Include it in the raised
    error so ops can diagnose without re-running with logging.
    """
    if r.is_success:
        return
    try:
        body = r.json()
    except Exception:
        body = r.text
    raise RuntimeError(
        f"Vercel {op} failed: status={r.status_code} url={r.request.url} body={body!r}"
    )


class VercelClient:
    """Async client — instantiate per publish, `await close()` when done."""

    def __init__(
        self,
        token: str | None = None,
        team_id: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.token = token or os.environ["VERCEL_TOKEN"]
        self.team_id = team_id or os.environ.get("VERCEL_TEAM_ID")
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=timeout,
        )

    # ── Projects ────────────────────────────────────────────────────

    async def get_project(self, name_or_id: str) -> dict[str, Any] | None:
        """Look up a project by name or id. Returns the project dict on
        hit, None on 404. Vercel's `GET /v9/projects/{idOrName}` accepts
        either.

        Used by the provider to make create_project idempotent: on a
        re-publish, or after a mid-flight crash between create_project
        succeeding on Vercel and the id being flushed to our DB, this
        avoids a 409 conflict on the next attempt.
        """
        r = await self._client.get(
            f"{BASE}/v9/projects/{name_or_id}",
            params=self._params(),
        )
        if r.status_code == 404:
            return None
        _raise_with_body(r, f"get_project {name_or_id!r}")
        return r.json()

    async def create_project(
        self, name: str, framework: str = "nextjs"
    ) -> dict[str, Any]:
        r = await self._client.post(
            f"{BASE}/v9/projects",
            params=self._params(),
            json={"name": name, "framework": framework},
        )
        _raise_with_body(r, f"create_project name={name!r}")
        return r.json()

    async def get_or_create_project(
        self, name: str, framework: str = "nextjs"
    ) -> tuple[dict[str, Any], bool]:
        """Idempotent create. Returns (project, created) — created=False
        means we reused an existing Vercel project with this name.
        """
        existing = await self.get_project(name)
        if existing is not None:
            return existing, False
        return await self.create_project(name, framework=framework), True

    async def disable_deployment_protection(self, project_id: str) -> None:
        """Turn off Vercel-Auth SSO gating on this project so the deployed
        URL is directly reachable.

        Vercel applies the team's default protection when a project is
        created (POST /v9/projects doesn't accept the field), so we PATCH
        immediately after. Generated apps have their own NextAuth login,
        so Vercel's auth wall was a second layer that just kept end-users
        from reaching the app at all. Best-effort: a 4xx here doesn't
        fail the publish — the user can flip it in the dashboard.
        """
        try:
            r = await self._client.patch(
                f"{BASE}/v9/projects/{project_id}",
                params=self._params(),
                json={"ssoProtection": None},
            )
            r.raise_for_status()
        except Exception:
            # Non-fatal — protection off is preferred but not required
            # for the deploy itself to succeed.
            pass

    # ── Env vars ────────────────────────────────────────────────────

    async def list_env(self, project_id: str) -> list[dict[str, Any]]:
        """Return every env var already set on the project. Used to
        decide POST-vs-PATCH when reconciling our desired env-var map
        against what's already there — Vercel's `upsert=true` query flag
        only handles the exact-same-target case and 403s otherwise.
        """
        r = await self._client.get(
            f"{BASE}/v9/projects/{project_id}/env",
            params=self._params(),
        )
        _raise_with_body(r, f"list_env project={project_id!r}")
        return r.json().get("envs", [])

    async def update_env(
        self,
        project_id: str,
        env_id: str,
        value: str,
        target: list[str],
    ) -> dict[str, Any]:
        """PATCH an existing env row by id — the reliable path when the
        row already exists with a possibly-different target set. Vercel's
        PATCH replaces value+target atomically."""
        r = await self._client.patch(
            f"{BASE}/v9/projects/{project_id}/env/{env_id}",
            params=self._params(),
            json={"value": value, "target": target, "type": "encrypted"},
        )
        if not r.is_success:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise RuntimeError(
                f"Vercel update_env failed: id={env_id!r} status={r.status_code} body={body!r}"
            )
        return r.json()

    async def set_env(
        self,
        project_id: str,
        key: str,
        value: str,
        target: list[str],
    ) -> dict[str, Any]:
        """Upsert an env var. `target` is one or more of
        ["production", "preview", "development"]."""
        r = await self._client.post(
            f"{BASE}/v9/projects/{project_id}/env",
            params={**self._params(), "upsert": "true"},
            json={
                "key": key,
                "value": value,
                "target": target,
                "type": "encrypted",
            },
        )
        if not r.is_success:
            # Bare httpx.HTTPStatusError just gives the URL and status;
            # for env-set we need to see which key failed and Vercel's
            # explanation so the caller can tell "reserved key" from
            # "malformed value" from "quota exhausted".
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise RuntimeError(
                f"Vercel set_env failed: key={key!r} target={target} "
                f"status={r.status_code} body={body!r}"
            )
        return r.json()

    # ── Deployments ─────────────────────────────────────────────────

    async def upload_file(self, sha: str, raw: bytes) -> None:
        """Upload a single file to Vercel's blob store, keyed by SHA1.

        Vercel's POST /v2/files takes the raw bytes as the request body
        with `x-vercel-digest: <sha1>` in the headers; the response is
        empty on success (or a 200/201). Uploads are idempotent by SHA
        — safe to re-upload something Vercel already has.

        Used by the upload-then-deploy flow: for any nontrivial app the
        inline `create_deployment(files=[{file,data}])` shape overshoots
        Vercel's 10 MB v13 request-body cap. Uploading each file first
        and then referencing them sha-only in the deployment body drops
        the deploy request to a few KB regardless of file count.
        """
        r = await self._client.post(
            f"{BASE}/v2/files",
            params=self._params(),
            headers={
                "Content-Type": "application/octet-stream",
                "x-vercel-digest": sha,
            },
            content=raw,
        )
        _raise_with_body(r, f"upload_file sha={sha!r} size={len(raw)}")

    async def create_deployment(
        self,
        name: str,
        project_id: str,
        files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create a deployment referencing `files`.

        Two accepted shapes for each entry:
          - inline: `{file, data, encoding?}` — bytes go in the body
          - upload-ref: `{file, sha, size}` — references a prior upload

        Callers targeting anything above ~5 MB of source must use the
        upload-ref shape; the inline shape hits Vercel's 10 MB v13
        request-body cap. See `upload_file` above.
        """
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
        _raise_with_body(
            r, f"create_deployment name={name!r} project={project_id!r} files={len(files)}"
        )
        return r.json()

    async def get_deployment(self, deployment_id: str) -> dict[str, Any]:
        r = await self._client.get(
            f"{BASE}/v13/deployments/{deployment_id}",
            params=self._params(),
        )
        _raise_with_body(r, f"get_deployment id={deployment_id!r}")
        return r.json()

    async def promote_deployment(self, deployment_id: str) -> dict[str, Any]:
        """Re-promote an earlier deployment — the rollback primitive."""
        r = await self._client.patch(
            f"{BASE}/v13/deployments/{deployment_id}/promote",
            params=self._params(),
        )
        _raise_with_body(r, f"promote_deployment id={deployment_id!r}")
        return r.json()

    # ── House-keeping ───────────────────────────────────────────────

    def _params(self) -> dict[str, str]:
        return {"teamId": self.team_id} if self.team_id else {}

    async def close(self) -> None:
        await self._client.aclose()

    # Context-manager support so callers can `async with VercelClient()`.

    async def __aenter__(self) -> "VercelClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
