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
  POST   /v13/deployments  (deploymentId)        redeploy     (same files, new env)
  POST   /v10/projects/{id}/domains              add_project_domain
  GET    /v9/projects/{id}/domains[/{name}]      list_project_domains / get_project_domain
  POST   /v9/projects/{id}/domains/{name}/verify verify_project_domain
  PATCH  /v9/projects/{id}/domains/{name}        redirect_project_domain
  DELETE /v9/projects/{id}/domains/{name}        remove_project_domain
  GET    /v6/domains/{name}/config               get_domain_config
"""
from __future__ import annotations

import asyncio
import email.utils
import os
import time
from typing import Any, Callable

import httpx

BASE = "https://api.vercel.com"

#: Pauses between retries of one file upload (seconds); its length is the
#: number of retries. Module-level so a test can make them instant.
UPLOAD_BACKOFF_S: tuple[float, ...] = (1.0, 3.0, 8.0)

#: A 429 that says when the limit resets is waited out — one wait at most
#: RATE_LIMIT_MAX_WAIT_S, all waits of one client (one publish) at most
#: RATE_LIMIT_BUDGET_S. Longer than that and the upload fails saying when to
#: try again; the files already uploaded stay on Vercel for that next try.
RATE_LIMIT_MAX_WAIT_S: float = 120.0
RATE_LIMIT_BUDGET_S: float = 300.0
#: Times one upload waits out a 429 before it gives up.
RATE_LIMIT_RETRIES: int = 6

# The clock and the pause, module-level so a test can stand in for both.
_now: Callable[[], float] = time.time
_sleep = asyncio.sleep


class VercelMissingFiles(RuntimeError):
    """A deployment named files Vercel does not hold yet: `missing` lists
    their SHAs. The caller uploads those and asks again."""

    def __init__(self, missing: list[str]):
        super().__init__(f"Vercel is missing {len(missing)} file(s)")
        self.missing = missing


def _rate_limit_wait(r: httpx.Response) -> float | None:
    """Seconds until a 429's limit resets, from `Retry-After` (seconds or an
    HTTP date), `x-ratelimit-reset` (epoch seconds) or the body's
    `error.limit.reset`; None when the answer gives no hint."""
    retry_after = r.headers.get("retry-after")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                return max(0.0, email.utils.parsedate_to_datetime(retry_after).timestamp() - _now())
            except (TypeError, ValueError):
                pass
    reset: Any = r.headers.get("x-ratelimit-reset")
    if reset is None:
        try:
            reset = ((r.json().get("error") or {}).get("limit") or {}).get("reset")
        except Exception:
            reset = None
    try:
        reset = float(reset)
    except (TypeError, ValueError):
        return None
    if reset > 1e12:  # epoch milliseconds
        reset /= 1000.0
    return max(0.0, reset - _now())


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
        # One rate limit for the whole team: when an upload hears a 429, every
        # upload of this client holds off until `_paused_until` (epoch s).
        self._paused_until = 0.0
        self._rate_waited = 0.0

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

    async def set_function_region(self, project_id: str, region: str) -> None:
        """Run the project's functions in `region` (e.g. "sin1")."""
        r = await self._client.patch(
            f"{BASE}/v9/projects/{project_id}",
            params=self._params(),
            json={"serverlessFunctionRegion": region},
        )
        _raise_with_body(r, f"set_function_region project={project_id!r} region={region!r}")

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

    async def set_env_target(self, project_id: str, env_id: str, target: list[str]) -> dict[str, Any]:
        """Change only which of Vercel's environments a setting applies to,
        keeping its value (which listing does not return)."""
        r = await self._client.patch(
            f"{BASE}/v9/projects/{project_id}/env/{env_id}",
            params=self._params(),
            json={"target": target},
        )
        _raise_with_body(r, f"set_env_target project={project_id!r} env={env_id!r}")
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

    async def delete_env(self, project_id: str, env_id: str) -> None:
        """Remove an env row by id. Used to clear a NEXTAUTH_URL a prior
        deploy pinned to a placeholder / a stale per-deployment URL, so
        NextAuth falls back to Vercel's own VERCEL_URL (the real host).
        A 404 is fine — the row is already gone."""
        r = await self._client.delete(
            f"{BASE}/v9/projects/{project_id}/env/{env_id}",
            params=self._params(),
        )
        if r.status_code not in (200, 204, 404):
            _raise_with_body(r, f"delete_env project={project_id!r} id={env_id!r}")

    # ── Deployments ─────────────────────────────────────────────────

    async def upload_file(
        self,
        sha: str,
        raw: bytes,
        on_wait: Callable[[str], None] | None = None,
    ) -> None:
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
        # A PASSING FAULT IS TRIED AGAIN. One 500 from Vercel on one 789-byte
        # file failed Med Tracker's whole publish (forge-v3, 2026-09-29).
        # An upload is idempotent by SHA, so a 5xx, a 429 or a dropped
        # connection is retried with a short backoff; a 4xx is an answer.
        # A 429 THAT SAYS WHEN IS WAITED OUT. DITANS's publish died on
        # `api-upload-paid` (forge-v3, 2026-11-03): three short backoffs are
        # nothing to a limit that resets in a minute. `on_wait` hears each
        # pause once, whichever upload hit it.
        attempts = len(UPLOAD_BACKOFF_S) + 1
        attempt = 0
        rate_waits = 0
        while True:
            await self._hold_while_paused()
            try:
                r = await self._client.post(
                    f"{BASE}/v2/files",
                    params=self._params(),
                    headers={
                        "Content-Type": "application/octet-stream",
                        "x-vercel-digest": sha,
                    },
                    content=raw,
                )
            except httpx.TransportError:
                if attempt == attempts - 1:
                    raise
                await _sleep(UPLOAD_BACKOFF_S[attempt])
                attempt += 1
                continue
            if r.status_code == 429:
                wait = _rate_limit_wait(r)
                if wait is not None and rate_waits < RATE_LIMIT_RETRIES:
                    rate_waits += 1
                    self._pause_for(wait, r, on_wait)
                    continue
            if (r.status_code >= 500 or r.status_code == 429) and attempt < attempts - 1:
                await _sleep(UPLOAD_BACKOFF_S[attempt])
                attempt += 1
                continue
            _raise_with_body(r, f"upload_file sha={sha!r} size={len(raw)}")
            return

    async def _hold_while_paused(self) -> None:
        delay = self._paused_until - _now()
        if delay > 0:
            await _sleep(delay)

    def _pause_for(
        self, wait: float, r: httpx.Response, on_wait: Callable[[str], None] | None
    ) -> None:
        """Hold every upload until the limit resets, or raise when that is
        further off than a publish waits. A pause other uploads already set
        is joined silently; only a new or longer one is told and counted."""
        wait = max(wait, 1.0)
        until = _now() + wait
        if until <= self._paused_until + 1.0:
            return
        if wait > RATE_LIMIT_MAX_WAIT_S or self._rate_waited + wait > RATE_LIMIT_BUDGET_S:
            try:
                body = r.json()
            except Exception:
                body = r.text
            at = time.strftime("%H:%M UTC", time.gmtime(until))
            raise RuntimeError(
                f"Vercel upload_file failed: status=429 — the upload rate limit resets in "
                f"{round(wait)}s (at {at}), longer than a publish waits. The files uploaded "
                f"so far stay on Vercel; publishing again after {at} uploads only the rest. "
                f"body={body!r}"
            )
        self._rate_waited += wait
        self._paused_until = until
        if on_wait is not None:
            on_wait(
                f"Vercel's upload rate limit was reached — waiting {round(wait)}s for it "
                f"to reset, then carrying on."
            )

    async def create_deployment(
        self,
        name: str,
        project_id: str,
        files: list[dict[str, Any]],
        target: str | None = "production",
    ) -> dict[str, Any]:
        """Create a deployment referencing `files` — a production one, or with
        `target=None` a preview (the app's test side).

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
                **({"target": target} if target else {}),
                "projectSettings": {"framework": "nextjs"},
            },
        )
        # ONLY WHAT VERCEL HAS NOT GOT. A deployment that names a file by a
        # SHA Vercel does not hold is refused with `missing_files` and the
        # list of those SHAs — the way to learn which of an app's files are
        # new, so a publish uploads a handful instead of all of them.
        if r.status_code == 400:
            try:
                err = (r.json() or {}).get("error") or {}
            except ValueError:
                err = {}
            if err.get("code") == "missing_files":
                raise VercelMissingFiles([str(s) for s in (err.get("missing") or [])])
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

    async def redeploy(self, project_name: str, deployment_id: str, target: str | None = "production") -> dict[str, Any]:
        """A new deployment of an earlier one's files, built with the project's
        environment as it is now: production by default, or a preview. A
        changed setting (the address sign-in uses) takes effect only in a
        deployment built after it; a test deployment promoted to production is
        this, with production's settings."""
        r = await self._client.post(
            f"{BASE}/v13/deployments",
            params={**self._params(), "forceNew": "1"},
            json={"name": project_name, "deploymentId": deployment_id, **({"target": target} if target else {})},
        )
        _raise_with_body(r, f"redeploy project={project_name!r} from={deployment_id!r}")
        return r.json()

    async def alias_deployment(self, deployment_id: str, alias: str) -> dict[str, Any]:
        """Point `alias` (a fixed address, e.g. the test side's) at this
        deployment. A production publish never moves it: it is not one of the
        project's production domains."""
        r = await self._client.post(
            f"{BASE}/v2/deployments/{deployment_id}/aliases",
            params=self._params(),
            json={"alias": alias},
        )
        _raise_with_body(r, f"alias_deployment {deployment_id!r} -> {alias!r}")
        return r.json()

    async def latest_production_deployment(self, project_id: str) -> dict[str, Any] | None:
        """The project's newest production deployment, or None before the first."""
        r = await self._client.get(
            f"{BASE}/v6/deployments",
            params={**self._params(), "projectId": project_id, "target": "production", "limit": "1"},
        )
        _raise_with_body(r, "latest_production_deployment")
        found = list(r.json().get("deployments") or [])
        return found[0] if found else None

    # ── Domains ─────────────────────────────────────────────────────
    #
    # An address the app answers at besides `<project>.vercel.app`. Vercel
    # issues its certificate once the domain's DNS points at Vercel, and asks
    # for a TXT record first when the domain is claimed by another account.
    # `services.deploy.domains` owns what is said and when; these are the calls.

    async def add_project_domain(self, project_id: str, name: str) -> dict[str, Any]:
        r = await self._client.post(
            f"{BASE}/v10/projects/{project_id}/domains",
            params=self._params(),
            json={"name": name},
        )
        _raise_with_body(r, f"add_project_domain {name!r}")
        return r.json()

    async def get_project_domain(self, project_id: str, name: str) -> dict[str, Any] | None:
        r = await self._client.get(
            f"{BASE}/v9/projects/{project_id}/domains/{name}",
            params=self._params(),
        )
        if r.status_code == 404:
            return None
        _raise_with_body(r, f"get_project_domain {name!r}")
        return r.json()

    async def list_project_domains(self, project_id: str) -> list[dict[str, Any]]:
        r = await self._client.get(
            f"{BASE}/v9/projects/{project_id}/domains",
            params=self._params(),
        )
        _raise_with_body(r, "list_project_domains")
        return list(r.json().get("domains") or [])

    async def verify_project_domain(self, project_id: str, name: str) -> dict[str, Any] | None:
        """Ask Vercel to check the TXT proof again. None when it is still
        not there (Vercel answers 400 for an unverified domain)."""
        r = await self._client.post(
            f"{BASE}/v9/projects/{project_id}/domains/{name}/verify",
            params=self._params(),
        )
        if r.status_code in (400, 409):
            return None
        _raise_with_body(r, f"verify_project_domain {name!r}")
        return r.json()

    async def redirect_project_domain(self, project_id: str, name: str, to: str | None) -> dict[str, Any]:
        """Send requests for `name` to `to` (a permanent redirect), or stop
        redirecting when `to` is None."""
        body: dict[str, Any] = {"redirect": to, "redirectStatusCode": 308 if to else None}
        r = await self._client.patch(
            f"{BASE}/v9/projects/{project_id}/domains/{name}",
            params=self._params(),
            json=body,
        )
        _raise_with_body(r, f"redirect_project_domain {name!r} -> {to!r}")
        return r.json()

    async def remove_project_domain(self, project_id: str, name: str) -> None:
        r = await self._client.delete(
            f"{BASE}/v9/projects/{project_id}/domains/{name}",
            params=self._params(),
        )
        if r.status_code == 404:
            return
        _raise_with_body(r, f"remove_project_domain {name!r}")

    async def get_domain_config(self, name: str) -> dict[str, Any]:
        """How the domain's DNS points: `misconfigured` false once it reaches
        Vercel, with the records Vercel recommends."""
        r = await self._client.get(
            f"{BASE}/v6/domains/{name}/config",
            params=self._params(),
        )
        _raise_with_body(r, f"get_domain_config {name!r}")
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
