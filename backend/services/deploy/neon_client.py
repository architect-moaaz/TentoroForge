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
        r.raise_for_status()
        body = r.json()
        project = body["project"]
        # First entry in connection_uris is the pooled write endpoint,
        # which is what the generated app needs for both writes and reads.
        connection_uri = body["connection_uris"][0]["connection_uri"]
        return {
            "project_id": project["id"],
            "database_url": connection_uri,
            "branch_id": project.get("default_branch_id"),
        }

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

    # ── House-keeping ───────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "NeonClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
