"""Thin async wrapper on the Neon REST API.

One Neon project per generated app. The pipeline calls create_project()
once on first publish, stores the returned project_id on the Deployment
row, and reuses it on redeploy (a fresh create would orphan the previous
database + break any live users of the app).

Auth: `Authorization: Bearer <NEON_API_KEY>`. Personal API keys work
across every org the user belongs to but require `org_id` on project
creation as of the 2026-07 API — passed via NEON_ORG_ID or the client
kwarg.

Defaults chosen for Tentoro Forge:
    pg_version = 18   Newest stable; probe-verified as supported (2026-07).
    region_id  = aws-us-east-2   Same coast as Vercel `iad1` (~10 ms).
    autoscale  = 0.25 CU min     Free-tier minimum, plenty for MVP apps.
    auto-suspend = 300 s         Idle DB sleeps, saving free-tier hours.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

BASE = "https://console.neon.tech/api/v2"

_DEFAULT_PG_VERSION = 18
_DEFAULT_REGION_ID = "aws-us-east-2"


class NeonClient:
    """Async client — instantiate per publish, `await close()` when done."""

    def __init__(
        self,
        api_key: str | None = None,
        org_id: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ["NEON_API_KEY"]
        # None org_id is valid for delete/list; only create requires it.
        # Left explicit rather than raising in __init__ so read-only ops
        # work without env-var setup.
        self.org_id = org_id or os.environ.get("NEON_ORG_ID")
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    # ── Projects ────────────────────────────────────────────────────

    async def create_project(
        self,
        name: str,
        pg_version: int = _DEFAULT_PG_VERSION,
        region_id: str = _DEFAULT_REGION_ID,
    ) -> dict[str, Any]:
        """Create a fresh Neon project + default branch + main endpoint.

        Returns a small dict with the ids and DATABASE_URL the deploy
        pipeline needs — a lot of Neon's response body is not relevant
        to us, so we don't leak it through.
        """
        payload: dict[str, Any] = {
            "project": {
                "name": name,
                "pg_version": pg_version,
                "region_id": region_id,
            }
        }
        if self.org_id:
            payload["project"]["org_id"] = self.org_id

        r = await self._client.post(f"{BASE}/projects", json=payload)
        if r.status_code == 422:
            # NEON SAID NO TO ANOTHER PROJECT, and its reason is in the body —
            # on the free plan that is the 100-project limit, which 82 orphaned
            # projects from failed publishes reached on 2026-10-19 (FitTrackr2
            # saw "422 Unprocessable Entity" and nothing else).
            try:
                why = str(r.json().get("message") or r.text)
            except Exception:  # noqa: BLE001
                why = r.text
            raise RuntimeError(
                f"Neon would not create a project for the app: {why.strip() or 'no reason given'}. "
                "This usually means the Neon organisation's project limit is reached — remove projects "
                "no app uses, or raise the plan.")
        r.raise_for_status()
        body = r.json()
        project = body["project"]
        # A PROJECT IS NOT READY THE MOMENT IT IS RETURNED. Its branch and
        # endpoint are still being made, and until those operations finish
        # Neon answers every change to it with 423 Locked: a database asked
        # for straight after creation failed four publishes of FitTrackr in
        # eight minutes, each leaving a project behind (qpqhdugb, 2026-10-19).
        await self.wait_until_idle(project["id"])
        # First entry in connection_uris is the pooled write endpoint,
        # which is what the generated app needs for both writes and reads.
        connection_uri = body["connection_uris"][0]["connection_uri"]
        return {
            "project_id": project["id"],
            "database_url": connection_uri,
            "branch_id": project.get("default_branch_id"),
        }

    async def wait_until_idle(self, project_id: str, timeout_s: float = 90.0) -> bool:
        """True once no operation on the project is running or scheduled;
        False when `timeout_s` passed first (the caller then tries, and may
        meet a 423). Never raises: a project whose operations cannot be
        listed is tried as it is."""
        import asyncio, time
        deadline = time.monotonic() + timeout_s
        delay = 1.0
        while True:
            try:
                r = await self._client.get(f"{BASE}/projects/{project_id}/operations", params={"limit": 50})
                ops = r.json().get("operations") or [] if r.is_success else []
            except Exception:  # noqa: BLE001 — not being able to ask is not a reason to stop
                ops = []
            if not any(str(o.get("status")) in ("running", "scheduling", "scheduled", "pending") for o in ops):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 5.0)

    async def _post_when_unlocked(self, project_id: str, url: str, json: dict, attempts: int = 6) -> httpx.Response:
        """POST `url`; on 423 Locked wait for the project's operations and try
        again, up to `attempts` times. The last response is returned as is."""
        import asyncio
        r = await self._client.post(url, json=json)
        for _ in range(attempts - 1):
            if r.status_code != 423:
                break
            await self.wait_until_idle(project_id, timeout_s=30.0)
            await asyncio.sleep(1.0)
            r = await self._client.post(url, json=json)
        return r

    async def delete_project(self, project_id: str) -> None:
        r = await self._client.delete(f"{BASE}/projects/{project_id}")
        r.raise_for_status()

    async def get_connection_uri(
        self,
        project_id: str,
        role_name: str = "neondb_owner",
        database_name: str = "neondb",
        pooled: bool = True,
    ) -> str:
        """Fetch the DATABASE_URL for an existing Neon project without
        rotating credentials. Used on redeploy so we can always push a
        real DATABASE_URL to Vercel instead of relying on a prior deploy
        having left one there.

        Defaults match Neon's create-time defaults (see create_project);
        override only if you customised the project on creation.
        """
        params = {
            "role_name": role_name,
            "database_name": database_name,
            "pooled": "true" if pooled else "false",
        }
        r = await self._client.get(
            f"{BASE}/projects/{project_id}/connection_uri",
            params=params,
        )
        if not r.is_success:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise RuntimeError(
                f"Neon get_connection_uri failed: project={project_id!r} "
                f"status={r.status_code} body={body!r}"
            )
        return r.json()["uri"]

    # ── Branches ────────────────────────────────────────────────────

    async def create_branch(self, project_id: str, name: str) -> dict[str, Any]:
        """A copy of the project's default branch — its data as it is now,
        copy-on-write, in seconds — with its own read-write endpoint.
        Returns ``{"branch_id", "database_url"}``. Used to try a publish's
        migration on the live data without touching the live data."""
        r = await self._client.post(
            f"{BASE}/projects/{project_id}/branches",
            json={"branch": {"name": name}, "endpoints": [{"type": "read_write"}]},
        )
        if not r.is_success:
            raise RuntimeError(f"Neon create_branch failed: project={project_id!r} status={r.status_code}")
        body = r.json()
        uris = body.get("connection_uris") or []
        if not uris:
            raise RuntimeError(f"Neon create_branch returned no connection uri: project={project_id!r}")
        return {"branch_id": body["branch"]["id"], "database_url": uris[0]["connection_uri"]}

    async def delete_branch(self, project_id: str, branch_id: str) -> None:
        r = await self._client.delete(f"{BASE}/projects/{project_id}/branches/{branch_id}")
        r.raise_for_status()

    # ── Databases (the test side's own) ────────────────────────────

    async def default_branch(self, project_id: str) -> str:
        """The id of the project's default (production) branch."""
        r = await self._client.get(f"{BASE}/projects/{project_id}/branches")
        if not r.is_success:
            raise RuntimeError(f"Neon list branches failed: project={project_id!r} status={r.status_code}")
        branches = r.json().get("branches") or []
        chosen = next((b for b in branches if b.get("default") or b.get("primary")), None) or (branches[:1] or [None])[0]
        if not chosen:
            raise RuntimeError(f"Neon project {project_id!r} has no branch")
        return str(chosen["id"])

    async def ensure_database(self, project_id: str, name: str, owner: str = "neondb_owner") -> dict[str, Any]:
        """A database called `name` on the project's default branch, made
        empty when it does not exist: `{"database_url", "created"}`. The test
        side runs on one of these — no copy of the live data, ever."""
        branch = await self.default_branch(project_id)
        r = await self._client.get(f"{BASE}/projects/{project_id}/branches/{branch}/databases")
        if not r.is_success:
            raise RuntimeError(f"Neon list databases failed: project={project_id!r} status={r.status_code}")
        have = {str(d.get("name")) for d in r.json().get("databases") or []}
        created = name not in have
        if created:
            r = await self._post_when_unlocked(project_id, f"{BASE}/projects/{project_id}/branches/{branch}/databases",
                                               json={"database": {"name": name, "owner_name": owner}})
            if not r.is_success:
                raise RuntimeError(f"Neon create database failed: project={project_id!r} status={r.status_code}")
        url = await self.get_connection_uri(project_id, role_name=owner, database_name=name)
        return {"database_url": url, "created": created, "branch_id": branch}

    async def drop_database(self, project_id: str, name: str) -> bool:
        """Remove the database `name` (the test side's, to start it again
        from demo data). False when there was none."""
        branch = await self.default_branch(project_id)
        r = await self._client.delete(f"{BASE}/projects/{project_id}/branches/{branch}/databases/{name}")
        if r.status_code == 404:
            return False
        if not r.is_success:
            raise RuntimeError(f"Neon drop database failed: project={project_id!r} status={r.status_code}")
        return True

    # ── House-keeping ───────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "NeonClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
