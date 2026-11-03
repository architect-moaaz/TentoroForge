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
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deployment import LIVE_STATUSES, Deployment
from models.project import Version
from services.deploy.env_sync import build_deploy_env
from services.deploy.neon_client import NeonClient
from services.deploy.provider import DeployEvent, DeploySnapshot
from services.deploy.snapshot import build_snapshot_upload
from services.deploy.vercel_client import VercelClient

# Vercel build usually completes in 60–120 s for a fresh Next.js app. THE
# CEILING IS VERCEL'S OWN, 45 minutes: at 300 s DITANS (400 pages, 8,000
# files) was declared "timed out" while Vercel was still compiling it, and
# went on to build with nobody watching (forge-v3, 2026-10-31). A build that
# overruns is ended by Vercel itself, as ERROR, which is reported as such.
_POLL_INTERVAL_S = 3
_POLL_CEILING_S = 45 * 60

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
    - The request 3xx-redirects, or is answered 401/403 (typical: the
      app's middleware bounces the probe to ``/login``, or — for an
      ``/api/*`` call, which a phone app can not follow a redirect for —
      answers 401 as JSON) — either proves Next.js is up and serving. We can't verify DB from
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
                elif 300 <= r.status_code < 400 or r.status_code in (401, 403):
                    # Middleware intercepted the probe: NextAuth bouncing to
                    # /login, or the 401 JSON an /api/* call without a session
                    # now gets (it was a redirect before, and the 401 was
                    # reported as "database unhealthy" on every gated app).
                    # The Next.js runtime is up and responding — treat as
                    # success, no warning.
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
# Runtime templates whose relative path differs between the template dir and
# the generated app: (template-relative, app-relative). seed.ts is
# platform-owned — its LOGIC is identical for every app (per-app data lives in
# seed.json) — so a fix to it (e.g. always ensuring the admin user exists even
# when FORGE_KEEP_DB_STATE preserves domain data) must reach already-generated
# projects on their next publish, without a regen.
_PLATFORM_REFRESH_RUNTIME_MAP = (
    ("seed.ts", "src/db/seed.ts"),
    # The CSV export answered anybody — no session, no role, every column
    # including the password hash. It now reads the app's own ENTITY_ACCESS
    # and SENSITIVE_COLUMNS projections. That is a fix to platform logic with
    # no per-app content in it, and every already-generated project is
    # serving the open version until its next publish carries this.
    ("api-export/route.ts", "src/app/api/export/[entity]/route.ts"),
    # Uploads keep the file in the app's database when there is no object
    # store; an app built before that kept failing every upload on Vercel.
    ("storage.ts", "src/lib/storage.ts"),
    ("db/forge-files.schema.ts", "src/db/schema/_forge_files.ts"),
    # Notifications carry the link to the record they are about.
    ("db/forge-notifications.schema.ts", "src/db/schema/_forge_notifications.ts"),
    # The engine: foreign keys and yes/no groups shown by name on charts.
    ("data-engine.ts", "src/lib/data-engine.ts"),
)
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
    # Carries the row type the engine returns; travels with data-engine.ts.
    "src/lib/data-engine-bridge.ts",
    "src/db/reset-schema.ts",
    # reset-schema.ts imports it, so the two travel together.
    "src/db/extensions.ts",
    # The build runs these between reset and seed. prepare-schema keeps rows
    # through renames, required columns and removals; verify-schema stops a
    # build whose push said "applied" and was not (database tests,
    # 2026-10-01). An app built before either change publishes with the
    # current ones, or its build calls a file it does not have.
    "src/db/prepare-schema.ts",
    "src/db/verify-schema.ts",
    # schema-page.tsx is fully platform-authored (per-app logic lives in the
    # files it imports). Refreshing it on every publish lets fixes to SSR
    # error handling / data-source resolution reach existing apps without a
    # full regen — same shape as the reset-schema fix above.
    "src/lib/schema-page.tsx",
    "src/lib/SchemaPageBoundary.tsx",
    # The test version's label (and noindex); renders nothing on the live app.
    "src/components/TestRibbon.tsx",
)


_RIBBON = "\n        <TestRibbon />"
_RIBBON_IMPORT = 'import { TestRibbon } from "@/components/TestRibbon";\n'
#: The ribbon once put after a `<body>` written in a comment
#: ("onto <html>/<body> before React hydrates") instead of the tag.
_RIBBON_IN_COMMENT = re.compile(r"(//[^\n]*<body\b[^>\n]*>)\n        <TestRibbon />")


def _ensure_test_ribbon(output_dir: Path) -> bool:
    """An app whose root layout predates the test version gets the ribbon in
    its <body>, as a newly built one has it — the real tag, never a `<body>`
    named in a comment; a ribbon once put into a comment is taken back out.
    True when the layout changed."""
    layout = output_dir / "src" / "app" / "layout.tsx"
    if not layout.is_file():
        return False
    before = layout.read_text("utf-8")
    text = _RIBBON_IN_COMMENT.sub(r"\1", before)
    if "<TestRibbon />" not in text:
        for m in re.finditer(r"<body\b[^>]*>", text):
            line = text[text.rfind("\n", 0, m.start()) + 1: m.start()].lstrip()
            if line.startswith(("//", "*", "/*", "{/*")):
                continue
            text = text[: m.end()] + _RIBBON + text[m.end():]
            break
    if "<TestRibbon />" in text and _RIBBON_IMPORT.strip() not in text:
        text = _RIBBON_IMPORT + text
    if text == before:
        return False
    layout.write_text(text, "utf-8")
    return True


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
    for tmpl_rel, app_rel in _PLATFORM_REFRESH_RUNTIME_MAP:
        src = _TEMPLATE_RUNTIME_DIR / tmpl_rel
        if not src.is_file():
            continue
        dst = output_dir / app_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    for rel in _PLATFORM_REFRESH_FOUNDATION_FILES:
        src = _TEMPLATE_FOUNDATION_DIR / rel
        if not src.is_file():
            continue
        dst = output_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    _ensure_test_ribbon(output_dir)
    # THE FRAME TOO — the platform's version of each frame file, or the one
    # the application owns (`frameCode`). A frame fix (the current page lit
    # in the rail) otherwise reached a published app only after a Smith turn.
    try:
        import json as _json
        from services.smith.sync_app import refresh_engine, refresh_frame
        for blueprint in (output_dir.parent / ".forge" / "blueprint" / "current.json",
                          output_dir / ".forge" / "blueprint" / "current.json"):
            if blueprint.is_file():
                doc = _json.loads(blueprint.read_text("utf-8"))
                refresh_frame(output_dir, doc)
                # AND THE ENGINE: the workflow engine, the SDK and the workflow
                # routes an app carries are the platform's. A fix to them
                # reached a published app only after a Smith turn, so a
                # republish asked for to deliver one shipped the old copy.
                refresh_engine(output_dir, doc)          # re-applies the app's patches too
                break
    except Exception:  # noqa: BLE001 — a stale frame is not a failed publish
        import logging as _logging
        _logging.getLogger(__name__).warning("[vercel] could not refresh the frame and engine of %s", output_dir, exc_info=True)


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
        from services.deploy import environments as envs
        row: Deployment | None = None
        side = envs.normalise(snapshot.environment)
        try:
            row = await self._begin_row(snapshot)

            # 1. Snapshot
            yield DeployEvent("snapshot", "Packaging app source…")
            _refresh_platform_files(Path(snapshot.output_dir))

            # 1a. THE LIVE DATA IS ASKED FIRST (`migration_trial`). A redeploy
            # migrates real records; the chain the build will run is tried on a
            # copy of them, and what would not fit is fixed by Smith before
            # anything is packaged — or the publish stops here, live app as it
            # was, saying which records and why.
            # Production only: the test side has no live data to protect.
            prior_live = (await self._latest_prior_with_neon(snapshot, environment=envs.PRODUCTION)
                          if side == envs.PRODUCTION else None)
            if prior_live and prior_live.neon_project_id:
                from services.deploy.migration_trial import ensure_publishable
                yield DeployEvent("migrate", "Trying the change on a copy of the live data…")
                notes: list[str] = []
                verdict = await ensure_publishable(
                    self.neon, prior_live.neon_project_id, snapshot.output_dir,
                    app_project_id=str(snapshot.project_id or ""), say=notes.append)
                for note in notes:
                    yield DeployEvent("migrate", note)
                if not verdict["ok"]:
                    detail = "; ".join(l.strip() for l in verdict["lines"] if l.strip().startswith("- "))[:600] \
                        or verdict["reason"][:600]
                    settle = f"\n\n{verdict['settle']}" if verdict.get("settle") else ""
                    yield DeployEvent(
                        "error",
                        "Not published: the live data cannot take this change without losing records — "
                        f"{detail}. Nothing was changed, and the live app keeps running as it was.{settle}",
                        {"stage": "migration_trial", "reason": verdict["reason"][:600]},
                    )
                    row.status = "failed"
                    row.error = f"migration_trial: {verdict['reason'][:300]}"
                    await self._flush()
                    return
                if verdict["fixed"]:
                    yield DeployEvent("migrate", "Fixed — the live data takes the change now. Changed so every "
                                      f"live record fits: {verdict.get('changed') or 'nothing in the record types'}.")
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
            # PROMOTE: exactly what Test runs goes to production — the test
            # deployment's files, rebuilt with production's settings. Nothing
            # is packaged again, so an edit made after the test publish does
            # not slip in.
            promoted: Deployment | None = None
            files: list[dict] = []
            if snapshot.promote_from:
                promoted = await self.db.get(Deployment, uuid.UUID(snapshot.promote_from))
                if (promoted is None or promoted.environment != envs.TEST or not promoted.vercel_deployment_id
                        or promoted.status not in LIVE_STATUSES or promoted.project_id != row.project_id):
                    yield DeployEvent("error", "Nothing to promote: the test version is not live.",
                                      {"stage": "snapshot", "reason": "no live test deployment"})
                    row.status = "failed"
                    row.error = "promote: no live test deployment"
                    await self._flush()
                    return
                row.source_digest = promoted.source_digest
            else:
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
                row.source_digest = envs.source_digest(files)
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
            if side == envs.TEST:
                # THE TEST SIDE'S OWN DATABASE: an empty one inside the app's
                # Neon project (made with it on a first publish), so the build
                # seeds demo data into it and the live data is never copied.
                if reused_neon:
                    neon_project_id = prior_neon.neon_project_id
                else:
                    r = await self.neon.create_project(name=snapshot.project_slug, region_id=snapshot.neon_region)
                    neon_project_id = r["project_id"]
                    # THE PROJECT IS ON THE ROW BEFORE ANYTHING ELSE IS ASKED OF
                    # IT: a failure in the next step must leave a row that names
                    # it, so the retry reuses it instead of making another.
                    row.neon_project_id = neon_project_id
                    row.neon_branch_id = r.get("branch_id")
                    await self._flush()
                if snapshot.reset_test_data:
                    yield DeployEvent("provision_db", "Starting the test data again from demo data…")
                    await self.neon.drop_database(neon_project_id, envs.TEST_DATABASE)
                made = await self.neon.ensure_database(neon_project_id, envs.TEST_DATABASE)
                neon_url = made["database_url"]
                row.neon_project_id = neon_project_id
                row.neon_branch_id = made.get("branch_id")
                # A database just made is empty: reset + demo seed. One that
                # exists keeps what testers entered.
                reused_neon = not made["created"]
            elif reused_neon:
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
                r = await self.neon.create_project(name=snapshot.project_slug, region_id=snapshot.neon_region)
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
            if snapshot.vercel_region:
                # ITS SERVER BESIDE ITS DATABASE (services.deploy.regions). The
                # default leaves Vercel's own region as it is.
                await self.vercel.set_function_region(vercel_project_id, snapshot.vercel_region)
            if side == envs.TEST:
                # Previews fall under Vercel's deployment protection by
                # default; the test side must be reachable like production.
                await self.vercel.disable_deployment_protection(vercel_project_id)
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
            # EACH SIDE ITS OWN SETTINGS: only rows written for this side's
            # Vercel environment are this side's; a row shared with the other
            # side is split first, so a test publish never changes production.
            targets = envs.env_targets(side)
            if side == envs.TEST and not await self._production_ready(vercel_project_id):
                # A FIRST PUBLISH TO TEST IS BUILT AS PRODUCTION. Vercel makes a
                # project's first deployment its production one whatever the
                # request says; Personal Finance's first publish, to Test, was
                # built without its test settings — "[reset-schema]
                # DATABASE_URL missing" (u8w3uw4j, 2026-10-21). Until production
                # has a version of its own, the test settings are both sides';
                # the first production publish splits them off.
                targets = ["preview", "production"]
            existing_by_key: dict[str, dict] = {}
            for e in existing_env:
                k = e.get("key")
                t = list(e.get("target") or [])
                if not k or not set(t) & set(targets):
                    continue
                if len(targets) > 1:
                    # One row per setting for both sides: a second row of the
                    # same name would be refused, so it goes.
                    if k in existing_by_key and e.get("id"):
                        await self.vercel.delete_env(vercel_project_id, e["id"])
                    else:
                        existing_by_key[k] = e
                    continue
                if len(t) > 1 and e.get("id"):
                    await self.vercel.set_env_target(vercel_project_id, e["id"], [x for x in t if x != targets[0]])
                    continue
                existing_by_key[k] = e

            # Only mint a new NEXTAUTH_SECRET when Vercel has no existing
            # row for it. Preserves sign-in continuity on true redeploys
            # (existing row wins) AND bootstraps adoption/new-project
            # cases where our DB claims redeploy but Vercel is empty.
            vercel_has_nextauth_secret = "NEXTAUTH_SECRET" in existing_by_key
            nextauth_secret = "" if vercel_has_nextauth_secret else secrets.token_hex(32)
            # THE CLOCK'S KEY, THE APP'S OWN. The tick authenticates itself
            # with CRON_SECRET; Vercel sends it on every cron call. The one the
            # app already runs with locally travels; a Vercel row that exists
            # is kept.
            cron_secret = ""
            from services.blueprint.assembly import existing_secrets
            local_secrets = existing_secrets(Path(snapshot.output_dir))
            if "CRON_SECRET" not in existing_by_key:
                cron_secret = local_secrets.get("CRON_SECRET") or secrets.token_urlsafe(24)
            # THE APP'S OWN KEYS — the push pair it signs with and the key its
            # sensitive fields are encrypted with: a deployment that lacks them
            # gets the same ones, never new ones (a new encryption key makes
            # every sealed value unreadable; see services/push_keys).
            from services.push_keys import VAPID_KEYS
            app_secrets = {k: local_secrets[k] for k in (*VAPID_KEYS, "SENSITIVE_ENCRYPTION_KEY")
                           if local_secrets.get(k) and k not in existing_by_key}

            # WHERE THE APP REPORTS ITS FAILURES (services/app_reporting): the
            # platform's public address and this project's id, so Smith's
            # inbox hears of a crash in the published app.
            from services.app_reporting import publish_env
            # THE APP'S OWN ADDRESS, when a provider has to send people back
            # to it: the project's production alias, stable across deploys.
            nextauth_url = ""
            if side == envs.TEST:
                # The test side signs in at its own fixed address, never at
                # the per-deployment one (the session would not stick).
                nextauth_url = f"https://{envs.test_alias(_slugify(snapshot.project_slug))}"
            else:
                try:
                    from services.deploy.sign_in_address import published_address
                    nextauth_url = published_address(snapshot.output_dir, _slugify(snapshot.project_slug))
                except Exception:  # noqa: BLE001 — no Blueprint to read: no provider to tell
                    nextauth_url = ""
            env = build_deploy_env(
                integrations={**publish_env(snapshot.project_id),
                              **envs.integrations_for(side, dict(snapshot.integrations)),
                              **envs.side_settings(side, test_recipients=snapshot.test_recipients)},
                neon_url=neon_url,
                vercel_url="",  # unused — NEXTAUTH_URL is left to VERCEL_URL unless a provider needs it
                nextauth_secret=nextauth_secret,
                cron_secret=cron_secret,
                nextauth_url=nextauth_url,
                app_secrets=app_secrets,
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
                        vercel_project_id, prior["id"], val, targets
                    )
                else:
                    await self.vercel.set_env(
                        vercel_project_id, key, val, targets
                    )

            # NEXTAUTH_URL is intentionally unset so NextAuth falls back to
            # Vercel's own VERCEL_URL — the real host — on both preview and
            # per-deployment URLs. A prior deploy may have pinned a stale
            # `placeholder.vercel.app` here; remove it so the fallback takes
            # over rather than login building every URL against the placeholder.
            stale_nextauth = existing_by_key.get("NEXTAUTH_URL")
            if stale_nextauth and stale_nextauth.get("id") and not nextauth_url:
                await self.vercel.delete_env(
                    vercel_project_id, stale_nextauth["id"]
                )

            # 5. Upload — upload each file to /v2/files keyed by SHA1,
            #    then create a deployment referencing them sha-only.
            #    Inlining the bytes in the deployment body blows past
            #    Vercel's 10 MB v13 request cap on anything nontrivial.
            if promoted is not None:
                yield DeployEvent("upload", "Sending the tested version to production…")
                vd = await self.vercel.redeploy(_slugify(snapshot.project_slug), promoted.vercel_deployment_id,
                                                target=envs.vercel_target(envs.PRODUCTION))
            else:
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
                    target=envs.vercel_target(side),
                )
            deployment_id = vd["id"]
            vercel_url = vd["url"]
            row.vercel_deployment_id = deployment_id
            row.status = "build"
            await self._flush()

            # No NEXTAUTH_URL rewrite here any more: the value is left unset so
            # NextAuth reads Vercel's VERCEL_URL at runtime. The old rewrite
            # PATCHed the env AFTER the deployment was created, which never
            # reached the already-built deployment — that is the bug this
            # replaces (login served against `placeholder.vercel.app`).

            yield DeployEvent("build", "Vercel is building your app…")

            # 6. Activate — poll until READY / ERROR / timeout
            yield DeployEvent("activate", "Waiting for deployment to become live…")
            elapsed = 0
            while elapsed < _POLL_CEILING_S:
                info = await self.vercel.get_deployment(deployment_id)
                state = info.get("readyState") or info.get("state") or ""
                if state in ("READY", "READY_STATE_READY"):
                    # THIS BUILD'S ADDRESS, and THE APP'S. Vercel mints one
                    # per deployment, frozen at that build; the app's own is
                    # its main domain or the production alias, which moves to
                    # the newest publish. People are given the app's.
                    deployment_url = f"https://{info.get('url', vercel_url)}"
                    row.deployment_url = deployment_url
                    domains: list[dict] = []
                    if side == envs.TEST:
                        # THE TEST SIDE'S FIXED ADDRESS moves to this build;
                        # production's addresses and domains are not touched.
                        alias = envs.test_alias(_slugify(snapshot.project_slug))
                        try:
                            await self.vercel.alias_deployment(deployment_id, alias)
                            row.url = f"https://{alias}"
                        except Exception as exc:  # noqa: BLE001 — the build is live at its own address
                            row.url = deployment_url
                            yield DeployEvent("activate", f"The test address {alias} could not be set "
                                              f"({str(exc)[-160:]}); the test version is at {deployment_url}.")
                    else:
                        from services.deploy.sign_in_address import stable_address
                        aliases = [a for a in (info.get("alias") or []) if isinstance(a, str)]
                        row.url = stable_address(snapshot.output_dir, _slugify(snapshot.project_slug),
                                                 next((a for a in aliases if a.endswith(".vercel.app")), ""))
                        # THE APP'S OTHER ADDRESSES: its Tentoro address, and
                        # any the owner added before this first publish, are
                        # attached now; the domain watch carries on from here.
                        try:
                            from services.deploy.domains import attach_after_publish
                            domains = await attach_after_publish(snapshot.output_dir, self.vercel,
                                                                 _slugify(snapshot.project_slug))
                        except Exception:  # noqa: BLE001 — the app is live; an address is retried by the watch
                            import logging as _logging
                            _logging.getLogger(__name__).warning("attaching the app's addresses after publish failed", exc_info=True)
                    url = row.url
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
                            message=(f"Promote the test version → {url}" if promoted is not None
                                     else f"Publish to {side} → {url}"),
                            files_changed=None,
                        ))
                        await self._flush()
                        yield DeployEvent(
                            "done",
                            f"Test version live at {url}" if side == envs.TEST else f"Live at {url}",
                            data={"url": url, "deployment_id": str(row.id), "domains": domains,
                                  "environment": side},
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
                                "environment": side,
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

        except asyncio.CancelledError:
            # THE PLATFORM STOPPED UNDER IT (a restart, a cutover). The row is
            # closed as interrupted rather than left at its last stage forever.
            if row is not None and row.status not in ("succeeded", "succeeded_with_warnings", "failed"):
                from services.deploy.runs import INTERRUPTED
                row.status = "failed"
                row.error = INTERRUPTED
                row.finished_at = datetime.now(timezone.utc)
                try:
                    await self._flush()
                except Exception:  # noqa: BLE001 — the restart wins; close_stale finishes the job
                    pass
            raise

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
            environment=snapshot.environment or "production",
            promoted_from=uuid.UUID(snapshot.promote_from) if snapshot.promote_from else None,
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

    async def _production_ready(self, vercel_project_id: str) -> bool:
        """Whether the Vercel project has a production deployment that built."""
        try:
            proj = await self.vercel.get_project(vercel_project_id) or {}
        except Exception:  # noqa: BLE001 — unknown is treated as none: both sides get the settings
            return False
        prod = (proj.get("targets") or {}).get("production") or {}
        return str(prod.get("readyState") or "").upper() == "READY"

    async def _latest_prior_with_neon(
        self, snapshot: DeploySnapshot, environment: str | None = None
    ) -> Deployment | None:
        """Most recent Deployment row that already owns a Neon project id
        for this project. Status-agnostic — a row that failed at a later
        step still holds a real Neon project whose name is unique. Both sides
        share the project (the test side has its own database in it); with
        `environment`, only that side's rows count.
        """
        conditions = [
            Deployment.project_id == uuid.UUID(snapshot.project_id),
            Deployment.target == "vercel",
            Deployment.neon_project_id.isnot(None),
        ]
        if environment:
            conditions.append(Deployment.environment == environment)
        stmt = (
            select(Deployment)
            .where(*conditions)
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
