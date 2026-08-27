"""Deterministic env-var merge for the deploy pipeline.

Sources — later wins:
  1. Platform integrations (from PlatformIntegration table, decrypted):
     RESEND_API_KEY / SMTP_* / ANTHROPIC_API_KEY / S3_* / etc.
  2. Deployment-time system vars: DATABASE_URL (Neon), NEXTAUTH_URL
     (Vercel), NEXTAUTH_SECRET (per-project random).
  3. Optional BLOB_READ_WRITE_TOKEN for Vercel Blob.

System vars override the integrations map — an accidental
DATABASE_URL sitting in the user's integrations must not point the
deployed app at the wrong database.

Vercel-reserved variables (NODE_ENV, VERCEL_*, and other System
Environment Variables) are FILTERED OUT before returning. Vercel
manages them automatically and rejects any attempt to set them with
403 ENV_ALREADY_EXISTS.

Pure — no I/O, no side effects. Easy to unit-test.
"""
from __future__ import annotations

# Names Vercel refuses to accept via the env-var API. Set automatically
# by the platform on every build/deploy. Trying to POST any of these
# with upsert=true still returns 403 ENV_ALREADY_EXISTS.
# https://vercel.com/docs/projects/environment-variables/system-environment-variables
_VERCEL_RESERVED_ENV_KEYS = frozenset({
    "NODE_ENV",
    "VERCEL",
    "VERCEL_ENV",
    "VERCEL_URL",
    "VERCEL_REGION",
    "VERCEL_BRANCH_URL",
    "VERCEL_PROJECT_PRODUCTION_URL",
    "VERCEL_GIT_COMMIT_SHA",
    "VERCEL_GIT_COMMIT_MESSAGE",
    "VERCEL_GIT_COMMIT_AUTHOR_LOGIN",
    "VERCEL_GIT_COMMIT_AUTHOR_NAME",
    "VERCEL_GIT_COMMIT_REF",
    "VERCEL_GIT_PROVIDER",
    "VERCEL_GIT_REPO_ID",
    "VERCEL_GIT_REPO_OWNER",
    "VERCEL_GIT_REPO_SLUG",
    "VERCEL_GIT_PREVIOUS_SHA",
    "VERCEL_GIT_PULL_REQUEST_ID",
    "VERCEL_DEPLOYMENT_ID",
})


def build_deploy_env(
    integrations: dict[str, str | None],
    neon_url: str,
    vercel_url: str,
    nextauth_secret: str,
    blob_token: str | None = None,
    keep_db_state: bool = False,
) -> dict[str, str]:
    """Return the env-var map to push to Vercel."""
    env: dict[str, str] = {}

    for key, val in integrations.items():
        if val is None or val == "":
            continue
        env[key] = str(val)

    # System vars WIN — deploy-time truth beats stored user data.
    env["DATABASE_URL"] = neon_url

    # Vercel returns bare hostnames ("acme.vercel.app"); if the caller
    # already prefixed with https:// (or http://), strip it so we don't
    # emit https://https://…
    host = vercel_url
    for scheme in ("https://", "http://"):
        if host.startswith(scheme):
            host = host[len(scheme):]
            break
    env["NEXTAUTH_URL"] = f"https://{host}"

    # Empty NEXTAUTH_SECRET means "redeploy — reuse the secret Vercel already
    # has". Emitting NEXTAUTH_SECRET="" leaves a footgun for any caller that
    # reads the env map without going through vercel_provider's per-key push
    # loop (e.g. for logging or diffing) — a blank secret would silently
    # invalidate every issued JWT. Omit the key entirely instead.
    if nextauth_secret:
        env["NEXTAUTH_SECRET"] = nextauth_secret

    if blob_token:
        env["BLOB_READ_WRITE_TOKEN"] = blob_token

    # Redeploys that reuse an existing Neon project must not wipe live data:
    # reset-schema.ts and seed.ts both honor this flag and skip their
    # destructive steps. First publishes omit it so the initial deploy still
    # gets a clean schema + seed.
    if keep_db_state:
        env["FORGE_KEEP_DB_STATE"] = "1"

    # Drop reserved keys — Vercel rejects them with 403 ENV_ALREADY_EXISTS.
    for k in _VERCEL_RESERVED_ENV_KEYS:
        env.pop(k, None)

    return env
