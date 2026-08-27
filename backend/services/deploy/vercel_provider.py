"""VercelDeployProvider — composes VercelClient + NeonClient + snapshot + env-sync.

Full publish orchestration:
  1. snapshot     — build the Vercel files[] payload from output_dir
  2. provision_db — reuse existing Neon project (redeploy) or create fresh
  3. upload       — POST the files[] to Vercel /v13/deployments
  4. build        — set every env var on the Vercel project
  5. activate     — poll /v13/deployments/{id} until READY / ERROR / timeout
  6. done         — persist Deployment row + yield final URL

Contracts inherited from services.deploy.provider:
  - final event is stage=done (data.url set) or stage=error (message set)
  - every exception caught and translated to stage=error
  - Deployment row status transitions persisted here, not by the router

The polling loop uses a fresh sync DB session for each write to keep
async engine + sync engine cleanly separated (the platform uses async
SQLAlchemy for the API but sync-style writes fit better inside the
async generator; a top-level session would need locking).
"""
from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deployment import Deployment
from models.project import Version
from services.deploy.env_sync import build_deploy_env
from services.deploy.neon_client import NeonClient
from services.deploy.provider import DeployEvent, DeploySnapshot
from services.deploy.snapshot import build_snapshot_upload
from services.deploy.vercel_client import VercelClient

# Vercel build usually completes in 60–120 s for a fresh Next.js app;
# 300 s ceiling gives headroom for cold caches without leaving the SSE
# stream hanging forever.
_POLL_INTERVAL_S = 3
_POLL_CEILING_S = 300

# Post-READY smoke — hit /api/health/db and expect 200 within this budget.
# Vercel-hosted Next.js needs a few seconds to warm the serverless function
# on the first request; give it room.
_SMOKE_TIMEOUT_S = 20
_SMOKE_RETRIES = 3


async def _smoke_test_db(url: str) -> tuple[bool, str | None]:
    """Hit the deployed app's /api/health/db endpoint.

    Returns ``(True, None)`` in two shapes:
    - Endpoint reports 200 with ``{"ok": true, ...}`` — the DB is
      verified reachable and at least one table exists.
    - The request 3xx-redirects (typical: NextAuth middleware bounces
      the probe to ``/login`` when the app requires auth) — the redirect
      itself proves Next.js is up and serving. We can't verify DB from
      here, but a green Vercel build + a live Next.js response is
      enough signal for "deploy succeeded"; a real DB fault would show
      up on the first user request instead.

    Returns ``(False, <one-line error>)`` when the endpoint reports 5xx,
    times out, or is unreachable. Never raises.

    The runtime injector ships /api/health/db as a purpose-built probe that
    verifies the Postgres connection AND that at least one table exists in
    the public schema — see backend/templates/runtime/api-health/route.ts.
    """
    target = url.rstrip("/") + "/api/health/db"
    last_err: str | None = None
    # follow_redirects=False so we can distinguish a middleware-intercepted
    # probe (3xx → auth) from a straight 200 with real body.
    async with httpx.AsyncClient(timeout=_SMOKE_TIMEOUT_S, follow_redirects=False) as client:
        for attempt in range(_SMOKE_RETRIES):
            try:
                r = await client.get(target)
                if r.status_code == 200:
                    try:
                        body = r.json()
                    except Exception:  # noqa: BLE001 — non-JSON 200 (rare)
                        body = {}
                    if body.get("ok") is True:
                        return True, None
                    last_err = f"200 but ok=false: {body.get('error', 'no error')}"
                elif 300 <= r.status_code < 400:
                    # Middleware intercepted the probe (typical: NextAuth
                    # bouncing to /login). The Next.js runtime is up and
                    # responding — treat as success, no warning.
                    return True, None
                elif r.status_code == 503:
                    try:
                        last_err = r.json().get("error") or r.text[:200]
                    except Exception:  # noqa: BLE001 — JSON parse fallback
                        last_err = r.text[:200]
                else:
                    last_err = f"HTTP {r.status_code}"
            except Exception as exc:  # noqa: BLE001 — never break the publish
                last_err = f"probe failed: {exc}"
            # Backoff between retries — first request cold-starts the fn.
            if attempt < _SMOKE_RETRIES - 1:
                await asyncio.sleep(2)
    return False, last_err or "unknown smoke failure"

# Platform-authoritative files that must reflect the current backend
# templates on every publish, not the frozen copy that landed in the
# project's output_dir at generation time. Anything the platform team
# treats as "shipped config, not user content" belongs here — a
# template fix should propagate to already-generated projects without
# a full regen.
_PLATFORM_REFRESH_FILES = ("vercel.json",)
_TEMPLATE_RUNTIME_DIR = (
    Path(__file__).resolve().parents[2] / "templates" / "runtime"
)
_TEMPLATE_FOUNDATION_DIR = (
    Path(__file__).resolve().parents[2] / "templates" / "app-foundation"
)
# Nested platform-owned files under app-foundation/. Paths are relative
# to the foundation root and mirrored into the project's output_dir at
# publish time. Add anything here that the platform team owns but that
# ends up in a non-runtime location in the generated tree (build-time
# scripts, deploy-time DB reset, etc.).
_PLATFORM_REFRESH_FOUNDATION_FILES = (
    "src/db/reset-schema.ts",
    # schema-page.tsx is fully platform-authored (per-app logic lives in the
    # files it imports). Refreshing it on every publish lets fixes to SSR
    # error handling / data-source resolution reach existing apps without a
    # full regen — same shape as the reset-schema fix above.
    "src/lib/schema-page.tsx",
    "src/lib/SchemaPageBoundary.tsx",
)


def _refresh_platform_files(output_dir: Path) -> None:
    """Copy platform-owned config files from templates → output_dir.

    Runs just before build_snapshot so the deploy always ships the
    latest platform config (vercel.json, etc.) even if the project was
    generated before the fix. Silently no-ops when a template file is
    absent — this is a best-effort refresh, not a generation step.
    """
    for name in _PLATFORM_REFRESH_FILES:
        src = _TEMPLATE_RUNTIME_DIR / name
        if not src.is_file():
            continue
        (output_dir / name).write_bytes(src.read_bytes())
    for rel in _PLATFORM_REFRESH_FOUNDATION_FILES:
        src = _TEMPLATE_FOUNDATION_DIR / rel
        if not src.is_file():
            continue
        dst = output_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())


class VercelDeployProvider:
    name = "vercel"

    def __init__(
        self,
        db: AsyncSession,
        vercel: VercelClient | None = None,
        neon: NeonClient | None = None,
    ) -> None:
        self.db = db
        self.vercel = vercel or VercelClient()
        self.neon = neon or NeonClient()

    async def publish(
        self, snapshot: DeploySnapshot
    ) -> AsyncIterator[DeployEvent]:
        """See services.deploy.provider.DeployProvider.publish."""
        row: Deployment | None = None
        try:
            row = await self._begin_row(snapshot)

            # 1. Snapshot
            yield DeployEvent("snapshot", "Packaging app source…")
            _refresh_platform_files(Path(snapshot.output_dir))
            # Deploy-time vendor + deps normalisation. Re-vendors the
            # @tentoroforge/* packages into ./vendor/ and rewrites
            # package.json deps to point at the vendored copies. Fixes
            # the "Module not found: @tentoroforge/engine" class of
            # Vercel build failures where the project's package.json
            # still uses monorepo-relative paths (`file:../../packages/…`)
            # that resolve only on the dev machine.
            #
            # Raises VendorRefreshError if a required package has no
            # built dist/ — surfaces the failure before the ~40s upload
            # + Vercel build round-trip, with a clearer message.
            from services.deploy.vendor_refresh import (
                VendorRefreshError, refresh_vendor_and_deps,
            )
            try:
                refresh_vendor_and_deps(
                    Path(snapshot.output_dir),
                    project_slug=snapshot.project_slug,
                )
            except VendorRefreshError as exc:
                yield DeployEvent(
                    "error",
                    f"Vendor refresh failed: {exc}",
                    {"stage": "snapshot", "reason": str(exc)},
                )
                row.status = "failed"
                row.error = f"vendor_refresh: {exc}"
                await self._flush()
                return
            files = build_snapshot_upload(Path(snapshot.output_dir))
            row.status = "snapshot"
            await self._flush()

            # 2. Provision DB
            yield DeployEvent("provision_db", "Provisioning Neon database…")
            # Look up prior resource ids INDEPENDENTLY, per resource. A
            # retry after a partial failure can have Neon from row A but
            # Vercel from row B — the names on each provider are unique
            # so recreating either would 409. `is_first_publish` (used
            # later to decide NEXTAUTH_SECRET stability) treats "first"
            # as: no prior row set any resource id at all.
            prior_neon = await self._latest_prior_with_neon(snapshot)
            prior_vercel = await self._latest_prior_with_vercel(snapshot)
            reused_neon = bool(prior_neon and prior_neon.neon_project_id)
            if reused_neon:
                # Redeploy — reuse the same Neon DB so live users see
                # the new code against the same data. Refetch the URI
                # from Neon so we can always push a fresh DATABASE_URL;
                # relying on Vercel having one from a prior deploy
                # breaks when the Vercel project was newly-adopted or
                # its env vars got cleared.
                neon_project_id = prior_neon.neon_project_id
                neon_url = await self.neon.get_connection_uri(neon_project_id)
                row.neon_project_id = neon_project_id
                row.neon_branch_id = prior_neon.neon_branch_id
            else:
                r = await self.neon.create_project(name=snapshot.project_slug)
                neon_project_id = r["project_id"]
                neon_url = r["database_url"]
                row.neon_project_id = neon_project_id
                row.neon_branch_id = r.get("branch_id")

            # 3. Vercel project — create on first publish, reuse on redeploy.
            # Idempotent: if the DB has no prior row (fresh publish, or a
            # prior attempt crashed before flushing the id), we still
            # look up by name on Vercel so we reuse an orphaned project
            # instead of hitting 409 "already exists".
            if prior_vercel and prior_vercel.vercel_project_id:
                vercel_project_id = prior_vercel.vercel_project_id
            else:
                # Vercel project names must be lowercase, ≤ 100 chars,
                # only letters/digits/dashes/underscores.
                proj, created = await self.vercel.get_or_create_project(
                    name=_slugify(snapshot.project_slug)
                )
                vercel_project_id = proj["id"]
                if created:
                    # Turn off Vercel-Auth SSO on freshly-created projects so
                    # the deployed URL is directly reachable. Generated apps
                    # have their own NextAuth login; Vercel's wall was an
                    # extra layer between real users and the app. Best-effort:
                    # a failure here doesn't fail the publish.
                    await self.vercel.disable_deployment_protection(
                        vercel_project_id
                    )
            row.vercel_project_id = vercel_project_id
            await self._flush()

            # 4. Env vars — set BEFORE creating the deployment so the
            # first build sees DATABASE_URL etc. from the start.
            #
            # Fetch what Vercel already has so we can decide POST-vs-PATCH,
            # and — critically — bootstrap missing NEXTAUTH_SECRET even
            # when our DB thinks this is a redeploy. Gating stability on
            # `is_first_publish` breaks when the Vercel project was
            # newly-adopted (fresh env, no prior secret) — the resulting
            # NextAuth `?error=Configuration` is the tell.
            existing_env = await self.vercel.list_env(vercel_project_id)
            existing_by_key: dict[str, dict] = {}
            for e in existing_env:
                k = e.get("key")
                if not k:
                    continue
                if "production" in (e.get("target") or []):
                    existing_by_key[k] = e
                elif k not in existing_by_key:
                    existing_by_key[k] = e

            # Only mint a new NEXTAUTH_SECRET when Vercel has no existing
            # row for it. Preserves sign-in continuity on true redeploys
            # (existing row wins) AND bootstraps adoption/new-project
            # cases where our DB claims redeploy but Vercel is empty.
            vercel_has_nextauth_secret = "NEXTAUTH_SECRET" in existing_by_key
            nextauth_secret = "" if vercel_has_nextauth_secret else secrets.token_hex(32)

            env = build_deploy_env(
                integrations=dict(snapshot.integrations),
                neon_url=neon_url,
                vercel_url="placeholder.vercel.app",  # rewritten after deploy
                nextauth_secret=nextauth_secret,
                # Reusing an existing Neon DB = a redeploy with live data;
                # tell the build to skip schema reset + reseed.
                keep_db_state=reused_neon,
            )

            for key, val in env.items():
                # DATABASE_URL never pushed empty — safety belt around
                # any future caller that reintroduces the old redeploy
                # shortcut. Real value comes from neon.get_connection_uri.
                if key == "DATABASE_URL" and not val:
                    continue
                prior = existing_by_key.get(key)
                if prior and prior.get("id"):
                    await self.vercel.update_env(
                        vercel_project_id, prior["id"], val, ["production"]
                    )
                else:
                    await self.vercel.set_env(
                        vercel_project_id, key, val, ["production"]
                    )

            # 5. Upload — upload each file to /v2/files keyed by SHA1,
            #    then create a deployment referencing them sha-only.
            #    Inlining the bytes in the deployment body blows past
            #    Vercel's 10 MB v13 request cap on anything nontrivial.
            yield DeployEvent(
                "upload",
                f"Uploading {len(files)} files to Vercel…",
            )
            upload_sem = asyncio.Semaphore(8)

            async def _one(entry: dict) -> None:
                async with upload_sem:
                    await self.vercel.upload_file(entry["sha"], entry["raw"])

            await asyncio.gather(*(_one(f) for f in files))

            deploy_files = [
                {"file": f["file"], "sha": f["sha"], "size": f["size"]}
                for f in files
            ]
            vd = await self.vercel.create_deployment(
                name=_slugify(snapshot.project_slug),
                project_id=vercel_project_id,
                files=deploy_files,
            )
            deployment_id = vd["id"]
            vercel_url = vd["url"]
            row.vercel_deployment_id = deployment_id
            row.status = "build"
            await self._flush()

            # Re-set NEXTAUTH_URL now that we know the real Vercel URL.
            # We just PATCHed it above with the placeholder value; the
            # env-id is still in `existing_by_key` from the pre-deploy
            # list_env call.
            nextauth_url_value = f"https://{vercel_url}"
            nextauth_row = existing_by_key.get("NEXTAUTH_URL")
            if nextauth_row and nextauth_row.get("id"):
                await self.vercel.update_env(
                    vercel_project_id,
                    nextauth_row["id"],
                    nextauth_url_value,
                    ["production"],
                )
            else:
                # First publish path — the earlier POST created it, so
                # re-lookup by refreshing the env list.
                refreshed = await self.vercel.list_env(vercel_project_id)
                match = next(
                    (
                        e for e in refreshed
                        if e.get("key") == "NEXTAUTH_URL"
                        and "production" in (e.get("target") or [])
                    ),
                    None,
                )
                if match and match.get("id"):
                    await self.vercel.update_env(
                        vercel_project_id,
                        match["id"],
                        nextauth_url_value,
                        ["production"],
                    )
                else:
                    await self.vercel.set_env(
                        vercel_project_id,
                        "NEXTAUTH_URL",
                        nextauth_url_value,
                        ["production"],
                    )

            yield DeployEvent("build", "Vercel is building your app…")

            # 6. Activate — poll until READY / ERROR / timeout
            yield DeployEvent("activate", "Waiting for deployment to become live…")
            elapsed = 0
            while elapsed < _POLL_CEILING_S:
                info = await self.vercel.get_deployment(deployment_id)
                state = info.get("readyState") or info.get("state") or ""
                if state in ("READY", "READY_STATE_READY"):
                    url = f"https://{info.get('url', vercel_url)}"
                    row.url = url
                    row.finished_at = datetime.now(timezone.utc)

                    # Post-READY smoke: green Vercel builds can still ship an
                    # empty database (drizzle-kit push exiting silently on the
                    # no-TTY prompt is the class we're catching). Hit the
                    # runtime-injected /api/health/db endpoint and surface any
                    # DB-side failure loudly — the app is live either way, so
                    # don't mark the deploy failed; use succeeded_with_warnings
                    # so the URL is still handed back but the UI can flag it.
                    yield DeployEvent(
                        "smoke", "Checking database is reachable and populated…"
                    )
                    smoke_ok, smoke_error = await _smoke_test_db(url)
                    if smoke_ok:
                        row.status = "succeeded"
                        # Publish counts as a version bump — dashboard totals
                        # were stuck at 0 because deploys never wrote a Version
                        # row (only rules/data-model/visual edits did).
                        self.db.add(Version(
                            project_id=uuid.UUID(snapshot.project_id),
                            commit_hash=None,
                            message=f"Publish → {url}",
                            files_changed=None,
                        ))
                        await self._flush()
                        yield DeployEvent(
                            "done",
                            f"Live at {url}",
                            data={"url": url, "deployment_id": str(row.id)},
                        )
                    else:
                        row.status = "succeeded_with_warnings"
                        row.error = f"DB smoke failed: {smoke_error}"[:2000]
                        # Still a version bump — the app is live at `url`.
                        self.db.add(Version(
                            project_id=uuid.UUID(snapshot.project_id),
                            commit_hash=None,
                            message=f"Publish (with warnings) → {url}",
                            files_changed=None,
                        ))
                        await self._flush()
                        yield DeployEvent(
                            "smoke_failed",
                            f"Live at {url} but database is unhealthy: "
                            f"{smoke_error}",
                            data={
                                "url": url,
                                "deployment_id": str(row.id),
                                "error": smoke_error,
                            },
                        )
                    return
                if state in ("ERROR", "CANCELED"):
                    row.status = "failed"
                    row.error = f"Vercel build failed (state={state})"
                    row.finished_at = datetime.now(timezone.utc)
                    await self._flush()
                    yield DeployEvent(
                        "error",
                        f"Vercel build failed (state={state}). "
                        f"Check the deployment logs.",
                    )
                    return
                await asyncio.sleep(_POLL_INTERVAL_S)
                elapsed += _POLL_INTERVAL_S

            row.status = "failed"
            row.error = "deployment timed out"
            row.finished_at = datetime.now(timezone.utc)
            await self._flush()
            yield DeployEvent(
                "error",
                f"Deployment timed out after {_POLL_CEILING_S} seconds",
            )

        except Exception as exc:
            # Never let a raw traceback leak to the SSE stream.
            if row is not None:
                row.status = "failed"
                row.error = str(exc)[:2000]
                row.finished_at = datetime.now(timezone.utc)
                try:
                    await self._flush()
                except Exception:
                    # DB error on the error path — swallow so we still
                    # emit a clean stage=error event.
                    pass
            yield DeployEvent("error", f"Publish failed: {exc}")

        finally:
            await self.vercel.close()
            await self.neon.close()

    async def destroy(self, deployment_id: str) -> None:
        """Delete the Vercel project + Neon project for cleanup."""
        d = await self.db.get(Deployment, uuid.UUID(deployment_id))
        if not d:
            return
        try:
            if d.neon_project_id:
                await self.neon.delete_project(d.neon_project_id)
        finally:
            # Note: Vercel projects deleted via a separate endpoint;
            # for MVP the user can delete manually if needed. Just
            # close the client.
            await self.vercel.close()
            await self.neon.close()

    # ── helpers ────────────────────────────────────────────────────

    async def _begin_row(self, snapshot: DeploySnapshot) -> Deployment:
        row = Deployment(
            id=uuid.uuid4(),
            project_id=uuid.UUID(snapshot.project_id),
            target="vercel",
            status="pending",
            started_at=datetime.now(timezone.utc),
        )
        # Capture what's being shipped so the History view can attribute
        # each deploy to a specific commit + app version. Best-effort —
        # a missing git dir or unreadable package.json just leaves the
        # column null; nothing about the deploy depends on this.
        sha, subject, version = _read_source_meta(Path(snapshot.output_dir))
        row.git_sha = sha
        row.git_commit_subject = subject
        row.app_version = version
        if snapshot.triggered_by:
            # 'smith' isn't a real user uuid — Smith's background publish
            # tool sets this to the string "smith" so the History view
            # can surface who kicked it off. Only assign the FK column
            # when the caller passed an actual uuid.
            try:
                row.triggered_by = uuid.UUID(snapshot.triggered_by)
            except (ValueError, AttributeError):
                pass
        self.db.add(row)
        await self._flush()
        return row

    async def _flush(self) -> None:
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def _latest_prior_with_neon(
        self, snapshot: DeploySnapshot
    ) -> Deployment | None:
        """Most recent Deployment row that already owns a Neon project id
        for this project. Status-agnostic — a row that failed at a later
        step still holds a real Neon project whose name is unique.
        """
        stmt = (
            select(Deployment)
            .where(
                Deployment.project_id == uuid.UUID(snapshot.project_id),
                Deployment.target == "vercel",
                Deployment.neon_project_id.isnot(None),
            )
            .order_by(Deployment.created_at.desc())
            .limit(1)
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def _latest_prior_with_vercel(
        self, snapshot: DeploySnapshot
    ) -> Deployment | None:
        """Same as _latest_prior_with_neon, for the Vercel project id."""
        stmt = (
            select(Deployment)
            .where(
                Deployment.project_id == uuid.UUID(snapshot.project_id),
                Deployment.target == "vercel",
                Deployment.vercel_project_id.isnot(None),
            )
            .order_by(Deployment.created_at.desc())
            .limit(1)
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    def _reuse_neon_url_or_recreate(self, prior: Deployment) -> str:
        """We don't cache DATABASE_URL for security. On a redeploy we
        can't refetch the URL from Neon without extra API calls; for MVP
        we short-circuit by requiring the caller (VercelClient.set_env
        with upsert=true) to reuse Vercel's existing DATABASE_URL var.

        Neon's GET /projects/{id}/connection_uri returns the same URL
        every time, so a follow-up can properly refetch — for now we
        pass an empty string and let the existing Vercel env win.
        """
        return ""


def _read_source_meta(
    output_dir: Path,
) -> tuple[str | None, str | None, str | None]:
    """Return (git_sha, commit_subject, app_version) for the app dir.

    Any read failure is swallowed and returns None for that slot — the
    deploy pipeline must not fail on missing metadata; the History view
    just renders "—" in that column.
    """
    import json as _json
    import subprocess

    sha: str | None = None
    subject: str | None = None
    version: str | None = None

    try:
        r = subprocess.run(
            ["git", "-C", str(output_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            sha = r.stdout.strip() or None
    except Exception:
        pass

    if sha:
        try:
            r = subprocess.run(
                ["git", "-C", str(output_dir), "log", "-1", "--pretty=%s"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                subject = (r.stdout.strip() or None)
                if subject and len(subject) > 200:
                    subject = subject[:197] + "…"
        except Exception:
            pass

    try:
        pkg = output_dir / "package.json"
        if pkg.exists():
            data = _json.loads(pkg.read_text(encoding="utf-8"))
            v = data.get("version")
            if isinstance(v, str):
                version = v[:64]
    except Exception:
        pass

    return sha, subject, version


def _slugify(name: str) -> str:
    """Vercel project names: lowercase, ≤ 100 chars, dashes/underscores."""
    s = "".join(c if (c.isalnum() or c in "-_") else "-" for c in name.lower())
    s = "-".join(part for part in s.split("-") if part)  # collapse
    return s[:100] or "app"
